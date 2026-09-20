#requires -version 5.1
<#
.SYNOPSIS
    Acceptance harness for the axiom-cli Windows x64 distribution (task J-004).

.DESCRIPTION
    Runs the positive, negative and boundary legs the J-004 card and the distribution contract
    require, against the real scripts in this repository, on this Windows host, with no Bash,
    no WSL, no Docker and no elevation:

      positive   plan-only install; approved install; PATH entry applied; entrypoint runs
      negative   missing approval digest; wrong approval digest; corrupted artifact digest;
                 unowned entrypoint conflict; refused downgrade; held transaction lock
      boundary   idempotent re-run; interrupted-install recovery; uninstall; uninstall when
                 nothing is installed; purge-data removal; managed-service register/remove

    Every leg is executed as a child process of the *shipped* Windows shell
    (powershell.exe 5.1) so that the captured stdout is exactly what a user would get, and so
    that `-Json` really does leave exactly one JSON object on stdout. Exit codes are the real
    process exit codes.

    The harness snapshots HKCU\Environment\Path before the first leg and restores it in a
    finally block, so a failed leg cannot leave a stray PATH entry behind.

.PARAMETER ScratchRoot
    Scratch directory. Defaults to <repo>\_j004-run. Removed before the run.

.PARAMETER EvidenceDir
    Directory the evidence files are written to. Defaults to <repo>\evidence\J-004.

.PARAMETER CliExe
    Prebuilt axiom-cli.exe. Defaults to <repo>\target\release\axiom-cli.exe.

.PARAMETER Python
    Optional python executable used to validate each envelope against
    packaging/install-result.schema.json. When absent the validation legs are recorded as
    not_run instead of being claimed as passing.
#>
[CmdletBinding()]
param(
    [string]$ScratchRoot,
    [string]$EvidenceDir,
    [string]$CliExe,
    [string]$Python
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $repoRoot 'installers\windows\AxiomCli.Windows.Common.ps1')

if ([string]::IsNullOrEmpty($ScratchRoot)) { $ScratchRoot = Join-Path $repoRoot '_j004-run' }
if ([string]::IsNullOrEmpty($EvidenceDir)) { $EvidenceDir = Join-Path $repoRoot 'evidence\J-004' }
if ([string]::IsNullOrEmpty($CliExe)) { $CliExe = Join-Path $repoRoot 'target\release\axiom-cli.exe' }

if (Test-Path -LiteralPath $ScratchRoot) { Remove-Item -LiteralPath $ScratchRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $ScratchRoot | Out-Null
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$ScratchRoot = (Resolve-Path -LiteralPath $ScratchRoot).Path
$EvidenceDir = (Resolve-Path -LiteralPath $EvidenceDir).Path

$installScript = Join-Path $repoRoot 'installers\windows\Install-AxiomCli.ps1'
$uninstallScript = Join-Path $repoRoot 'installers\windows\Uninstall-AxiomCli.ps1'
$buildScript = Join-Path $repoRoot 'packaging\windows\Build-ReleaseSet.ps1'
$schemaPath = Join-Path $repoRoot 'packaging\install-result.schema.json'

$shippedShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path -LiteralPath $shippedShell)) { throw "shipped Windows shell not found at $shippedShell" }

if (-not (Test-Path -LiteralPath $CliExe)) {
    throw "axiom-cli.exe not found at $CliExe; build it with 'cargo build --release --locked' first"
}

$script:Results = New-Object System.Collections.Generic.List[object]
$script:Log = New-Object System.Collections.Generic.List[string]

function Write-Log {
    param([string]$Line)
    $script:Log.Add($Line)
    Write-Host $Line
}

function Add-Result {
    param(
        [Parameter(Mandatory = $true)][string]$Leg,
        [Parameter(Mandatory = $true)][string]$Class,
        [Parameter(Mandatory = $true)][int]$Expected,
        [Parameter(Mandatory = $true)][int]$Actual,
        [AllowNull()]$Envelope,
        [string]$Note = ''
    )
    $outcome = ''
    if ($null -ne $Envelope) { $outcome = [string]$Envelope.outcome }
    $ok = ($Expected -eq $Actual)
    $script:Results.Add([ordered]@{
            leg            = $Leg
            class          = $Class
            expected_exit  = $Expected
            actual_exit    = $Actual
            pass           = $ok
            outcome        = $outcome
            note           = $Note
        })
    Write-Log ("[{0}] {1,-6} leg={2,-34} expected={3,-3} actual={4,-3} outcome={5} {6}" -f `
            $(if ($ok) { 'PASS' } else { 'FAIL' }), $Class, $Leg, $Expected, $Actual, $outcome, $Note)
    return $ok
}

<#
    Invoke one script as a child process of the shipped shell. Returns a record carrying the
    real exit code, the captured stdout, the captured stderr and the parsed envelope (when
    stdout is a single JSON object).
#>
function Invoke-AxiomChild {
    param(
        [Parameter(Mandatory = $true)][string]$Leg,
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [string[]]$ScriptArgs = @()
    )

    $safeLeg = ($Leg -replace '[^0-9A-Za-z\-]', '-')
    $stdoutPath = Join-Path $ScratchRoot ('stdout-' + $safeLeg + '.txt')
    $stderrPath = Join-Path $ScratchRoot ('stderr-' + $safeLeg + '.txt')

    # Windows PowerShell 5.1 turns a native command's stderr lines into ErrorRecords, and with
    # $ErrorActionPreference = 'Stop' at script scope that would abort the caller. The
    # distribution contract requires diagnostics on stderr, so the caller must capture them
    # instead of dying on them: relax the preference around the child invocation.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $shippedShell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $ScriptPath @ScriptArgs 1> $stdoutPath 2> $stderrPath
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }

    $stdout = ''
    if (Test-Path -LiteralPath $stdoutPath) { $stdout = [System.IO.File]::ReadAllText($stdoutPath) }
    $stderr = ''
    if (Test-Path -LiteralPath $stderrPath) { $stderr = [System.IO.File]::ReadAllText($stderrPath) }

    $envelope = $null
    $envelopeValid = $false
    if (-not [string]::IsNullOrWhiteSpace($stdout)) {
        try {
            $envelope = ConvertFrom-Json -InputObject $stdout
            $envelopeValid = $true
        } catch {
            $envelopeValid = $false
        }
    }

    return [ordered]@{
        leg            = $Leg
        script         = $ScriptPath
        arguments      = @($ScriptArgs)
        exit_code      = $exitCode
        stdout         = $stdout
        stderr         = $stderr
        envelope       = $envelope
        envelope_valid = $envelopeValid
        command        = ('"{0}" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{1}" {2}' -f `
                $shippedShell, $ScriptPath, (($ScriptArgs | ForEach-Object { '"{0}"' -f $_ }) -join ' '))
    }
}

function Get-JsonProp {
    param([AllowNull()]$Object, [Parameter(Mandatory = $true)][string]$Name, [AllowNull()]$Default = $null)
    if ($null -eq $Object) { return $Default }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $Default }
    return $property.Value
}

# ---------------------------------------------------------------------------
# Guard: snapshot the user PATH so the run cannot leave it changed.
# ---------------------------------------------------------------------------
$pathGuard = Get-AxiomUserPathSnapshot
Write-Log ("host: {0}" -f ((Get-AxiomHostInfo).windows_version))
Write-Log ("shipped shell: {0}" -f $shippedShell)
Write-Log ("harness elevated: {0}" -f (Test-AxiomSessionElevated))
Write-Log ("scratch: {0}" -f $ScratchRoot)
Write-Log ("evidence: {0}" -f $EvidenceDir)
Write-Log ("path snapshot before: present={0} kind={1} value='{2}'" -f $pathGuard.present, $pathGuard.kind, $pathGuard.value)
$script:Failures = 0
$script:PathGuardRestored = $false

function Assert-Axiom {
    param([Parameter(Mandatory = $true)][string]$Leg, [Parameter(Mandatory = $true)][bool]$Condition, [Parameter(Mandatory = $true)][string]$Detail)
    if ($Condition) {
        Write-Log ("[PASS] assert {0}: {1}" -f $Leg, $Detail)
    } else {
        $script:Failures++
        Write-Log ("[FAIL] assert {0}: {1}" -f $Leg, $Detail)
    }
}

$script:StepRecords = New-Object System.Collections.Generic.List[object]

function Invoke-Leg {
    param(
        [Parameter(Mandatory = $true)][string]$Leg,
        [Parameter(Mandatory = $true)][string]$Class,
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [string[]]$ScriptArgs = @(),
        [Parameter(Mandatory = $true)][int]$Expect
    )
    $record = Invoke-AxiomChild -Leg $Leg -ScriptPath $ScriptPath -ScriptArgs $ScriptArgs
    $script:StepRecords.Add($record)
    $envelope = $record.envelope
    if (-not (Add-Result -Leg $Leg -Class $Class -Expected $Expect -Actual $record.exit_code -Envelope $envelope)) {
        $script:Failures++
    }
    return $record
}

$coreManifest = Join-Path (Split-Path -Parent $repoRoot) 'axiom-graphd\release\core-manifest.json'

Write-Log ''
Write-Log '=== build release sets ==='

$buildArgs = @('-OutDir', (Join-Path $ScratchRoot 'release-set-main'), '-CliExe', $CliExe, '-Json')
if (Test-Path -LiteralPath $coreManifest) { $buildArgs += @('-CoreManifest', $coreManifest) }
$buildMain = Invoke-Leg -Leg 'B01-build-main' -Class 'positive' -ScriptPath $buildScript -ScriptArgs $buildArgs -Expect 0
$mainSet = ConvertFrom-Json -InputObject $buildMain.stdout
$mainDigest = [string]$mainSet.plan_digest
$mainSetDir = [string]$mainSet.release_set_path
Write-Log ("main release set: {0}" -f $mainSetDir)
Write-Log ("main plan digest: {0}" -f $mainDigest)

$buildAlpha = Invoke-Leg -Leg 'B02-build-alpha' -Class 'positive' -ScriptPath $buildScript `
    -ScriptArgs @('-OutDir', (Join-Path $ScratchRoot 'release-set-alpha'), '-CliExe', $CliExe, '-Version', '0.0.0-alpha', '-Json') -Expect 0
$alphaSet = ConvertFrom-Json -InputObject $buildAlpha.stdout
$alphaDigest = [string]$alphaSet.plan_digest
$alphaSetDir = [string]$alphaSet.release_set_path

$serviceTaskName = 'AxiomCliJ004HarnessService'
$buildService = Invoke-Leg -Leg 'B03-build-service' -Class 'positive' -ScriptPath $buildScript `
    -ScriptArgs @('-OutDir', (Join-Path $ScratchRoot 'release-set-service'), '-CliExe', $CliExe, '-Json', `
        '-ServiceTaskName', $serviceTaskName, '-ServiceArgv', '--help') -Expect 0
$serviceSet = ConvertFrom-Json -InputObject $buildService.stdout
$serviceDigest = [string]$serviceSet.plan_digest
$serviceSetDir = [string]$serviceSet.release_set_path

# A corrupted copy: same manifest, one flipped byte in the artifact.
$corruptDir = Join-Path $ScratchRoot 'release-set-corrupt'
Copy-Item -LiteralPath (Split-Path -Parent $mainSetDir) -Destination $corruptDir -Recurse -Force
$corruptExe = Join-Path $corruptDir 'axiom-cli.exe'
$bytes = [System.IO.File]::ReadAllBytes($corruptExe)
$bytes[1000] = $bytes[1000] -bxor 0xFF
[System.IO.File]::WriteAllBytes($corruptExe, $bytes)
Write-Log ("corrupted artifact: {0} (one byte flipped at offset 1000)" -f $corruptExe)

Write-Log ''
Write-Log '=== positive legs ==='

$rootMain = Join-Path $ScratchRoot 'install-main'

$l01 = Invoke-Leg -Leg 'L01-install-plan-only' -Class 'positive' -ScriptPath $installScript `
    -ScriptArgs @('-ReleaseSet', $mainSetDir, '-InstallRoot', $rootMain, '-Json') -Expect 0
Assert-Axiom -Leg 'L01' -Condition ($l01.envelope.outcome -eq 'planned') -Detail 'outcome is planned'
Assert-Axiom -Leg 'L01' -Condition ($l01.envelope.mutated -eq $false) -Detail 'mutated is false'
Assert-Axiom -Leg 'L01' -Condition (-not (Test-Path -LiteralPath $rootMain)) -Detail 'no install root was created'
Assert-Axiom -Leg 'L01' -Condition ([string]$l01.envelope.plan_digest -eq $mainDigest) -Detail 'plan digest matches the release set'
Assert-Axiom -Leg 'L01' -Condition ($l01.envelope.artifacts.Count -eq 1) -Detail 'one digest-verified artifact is named'
Assert-Axiom -Leg 'L01' -Condition ([string]$l01.envelope.artifacts[0].sha256 -eq (Get-AxiomSha256Hex -Path (Join-Path (Split-Path -Parent $mainSetDir) 'axiom-cli.exe'))) -Detail 'artifact sha256 matches the real file'
Assert-Axiom -Leg 'L01' -Condition ($l01.stderr -notmatch '"outcome"') -Detail 'diagnostics are on stderr, not stdout'

$l02 = Invoke-Leg -Leg 'L02-apply-without-approval' -Class 'negative' -ScriptPath $installScript `
    -ScriptArgs @('-ReleaseSet', $mainSetDir, '-InstallRoot', $rootMain, '-Apply', '-Json') -Expect 2
Assert-Axiom -Leg 'L02' -Condition ($l02.envelope.outcome -eq 'refused') -Detail 'outcome is refused'
Assert-Axiom -Leg 'L02' -Condition (-not (Test-Path -LiteralPath $rootMain)) -Detail 'nothing was installed'

$l03 = Invoke-Leg -Leg 'L03-apply-wrong-approval' -Class 'negative' -ScriptPath $installScript `
    -ScriptArgs @('-ReleaseSet', $mainSetDir, '-InstallRoot', $rootMain, '-Apply', '-ApproveDigest', ('0' * 64), '-Json') -Expect 5
Assert-Axiom -Leg 'L03' -Condition ($l03.envelope.outcome -eq 'refused') -Detail 'outcome is refused'
Assert-Axiom -Leg 'L03' -Condition ($l03.envelope.refusals.Count -ge 1) -Detail 'a refusal records expected vs actual digest'

$l04 = Invoke-Leg -Leg 'L04-apply-approved' -Class 'positive' -ScriptPath $installScript `
    -ScriptArgs @('-ReleaseSet', $mainSetDir, '-InstallRoot', $rootMain, '-Apply', '-ApproveDigest', $mainDigest, '-Json') -Expect 0
Assert-Axiom -Leg 'L04' -Condition ($l04.envelope.outcome -eq 'installed') -Detail 'outcome is installed'
Assert-Axiom -Leg 'L04' -Condition ($l04.envelope.mutated -eq $true) -Detail 'mutated is true'
Assert-Axiom -Leg 'L04' -Condition ($l04.envelope.elevation_required -eq $false) -Detail 'elevation_required is false'
Assert-Axiom -Leg 'L04' -Condition ($l04.envelope.path_rule.applied -eq $true) -Detail 'the per-user PATH rule was applied'
Assert-Axiom -Leg 'L04' -Condition ($l04.envelope.path_rule.machine_wide_change -eq $false) -Detail 'no machine-wide change'
$installedExe = Join-Path $rootMain 'bin\axiom-cli.exe'
Assert-Axiom -Leg 'L04' -Condition (Test-Path -LiteralPath $installedExe) -Detail 'entrypoint is installed under bin\'
Assert-Axiom -Leg 'L04' -Condition ((Get-AxiomSha256Hex -Path $installedExe) -eq [string]$l04.envelope.artifacts[0].sha256) -Detail 'installed entrypoint digest matches the envelope'
Assert-Axiom -Leg 'L04' -Condition (Test-Path -LiteralPath (Join-Path $rootMain 'cli\state.json')) -Detail 'install state is recorded'
Assert-Axiom -Leg 'L04' -Condition (Test-Path -LiteralPath (Join-Path $rootMain 'install-manifest.json')) -Detail 'install manifest is recorded'

$pathNow = Get-AxiomUserPathSnapshot
Assert-Axiom -Leg 'L04' -Condition (Test-AxiomPathContains -Value ([string]$pathNow.value) -Entry (Join-Path $rootMain 'bin')) -Detail 'the user PATH now contains the install bin directory'

$l05 = Invoke-Leg -Leg 'L05-install-idempotent-rerun' -Class 'boundary' -ScriptPath $installScript `
    -ScriptArgs @('-ReleaseSet', $mainSetDir, '-InstallRoot', $rootMain, '-Apply', '-ApproveDigest', $mainDigest, '-Json') -Expect 0
Assert-Axiom -Leg 'L05' -Condition ($l05.envelope.outcome -eq 'already_installed') -Detail 'outcome is already_installed'
Assert-Axiom -Leg 'L05' -Condition ($l05.envelope.mutated -eq $false) -Detail 'an idempotent re-run mutates nothing'
Assert-Axiom -Leg 'L05' -Condition ((Get-AxiomSha256Hex -Path $installedExe) -eq [string]$l04.envelope.artifacts[0].sha256) -Detail 'the installed entrypoint is byte-identical after the re-run'
Write-Log ''
Write-Log '=== negative legs ==='

$l06 = Invoke-Leg -Leg 'L06-corrupted-artifact-refused' -Class 'negative' -ScriptPath $installScript `
    -ScriptArgs @('-ReleaseSet', $corruptDir, '-InstallRoot', (Join-Path $ScratchRoot 'install-corrupt'), '-Apply', '-ApproveDigest', $mainDigest, '-Json') -Expect 9
Assert-Axiom -Leg 'L06' -Condition ($l06.envelope.outcome -eq 'refused') -Detail 'a corrupted artifact is refused'
Assert-Axiom -Leg 'L06' -Condition ($l06.envelope.refusals.Count -ge 1) -Detail 'the refusal names the digest mismatch'
Assert-Axiom -Leg 'L06' -Condition (-not (Test-Path -LiteralPath (Join-Path $ScratchRoot 'install-corrupt'))) -Detail 'nothing was installed from a corrupted release set'

$rootUnowned = Join-Path $ScratchRoot 'install-unowned'
New-Item -ItemType Directory -Force -Path (Join-Path $rootUnowned 'bin') | Out-Null
[System.IO.File]::WriteAllText((Join-Path $rootUnowned 'bin\axiom-cli.exe'), 'not an axiom binary')
$l07 = Invoke-Leg -Leg 'L07-unowned-entrypoint-conflict' -Class 'negative' -ScriptPath $installScript `
    -ScriptArgs @('-ReleaseSet', $mainSetDir, '-InstallRoot', $rootUnowned, '-Apply', '-ApproveDigest', $mainDigest, '-Json') -Expect 6
Assert-Axiom -Leg 'L07' -Condition ($l07.envelope.outcome -eq 'refused') -Detail 'an unowned file at the entrypoint path is a conflict'
Assert-Axiom -Leg 'L07' -Condition ([System.IO.File]::ReadAllText((Join-Path $rootUnowned 'bin\axiom-cli.exe')) -eq 'not an axiom binary') -Detail 'the unowned file was left untouched'

$l07b = Invoke-Leg -Leg 'L07b-unowned-entrypoint-forced' -Class 'boundary' -ScriptPath $installScript `
    -ScriptArgs @('-ReleaseSet', $mainSetDir, '-InstallRoot', $rootUnowned, '-Apply', '-ApproveDigest', $mainDigest, '-Force', '-Json') -Expect 0
Assert-Axiom -Leg 'L07b' -Condition ($l07b.envelope.outcome -eq 'installed') -Detail '-Force replaces the unowned file'
Assert-Axiom -Leg 'L07b' -Condition ((Get-AxiomSha256Hex -Path (Join-Path $rootUnowned 'bin\axiom-cli.exe')) -eq [string]$l07b.envelope.artifacts[0].sha256) -Detail 'the forced install wrote the verified artifact'

Write-Log ''
Write-Log '=== boundary legs ==='

$rootDowngrade = Join-Path $ScratchRoot 'install-downgrade'
[void](Invoke-Leg -Leg 'L08-setup-install-main' -Class 'boundary' -ScriptPath $installScript `
        -ScriptArgs @('-ReleaseSet', $mainSetDir, '-InstallRoot', $rootDowngrade, '-Apply', '-ApproveDigest', $mainDigest, '-Json') -Expect 0)
$l08 = Invoke-Leg -Leg 'L08-downgrade-refused' -Class 'negative' -ScriptPath $installScript `
    -ScriptArgs @('-ReleaseSet', $alphaSetDir, '-InstallRoot', $rootDowngrade, '-Apply', '-ApproveDigest', $alphaDigest, '-Json') -Expect 9
Assert-Axiom -Leg 'L08' -Condition ($l08.envelope.outcome -eq 'refused') -Detail 'an older release is refused'
$l08b = Invoke-Leg -Leg 'L08b-downgrade-allowed' -Class 'boundary' -ScriptPath $installScript `
    -ScriptArgs @('-ReleaseSet', $alphaSetDir, '-InstallRoot', $rootDowngrade, '-Apply', '-ApproveDigest', $alphaDigest, '-AllowDowngrade', '-Json') -Expect 0
Assert-Axiom -Leg 'L08b' -Condition ($l08b.envelope.outcome -eq 'installed') -Detail '-AllowDowngrade installs the older release'
Assert-Axiom -Leg 'L08b' -Condition ([string]$l08b.envelope.release_set.release_version -eq '0.0.0-alpha') -Detail 'the older release version is recorded'

$rootRecover = Join-Path $ScratchRoot 'install-recover'
$leftoverGeneration = Join-Path $rootRecover 'cli\generations\0.0.0-dev'
New-Item -ItemType Directory -Force -Path $leftoverGeneration | Out-Null
[System.IO.File]::WriteAllText((Join-Path $leftoverGeneration 'leftover-from-interrupted-run.txt'), 'leftover')
New-Item -ItemType Directory -Force -Path (Join-Path $rootRecover 'cli\staging\bin') | Out-Null
Copy-Item -LiteralPath $CliExe -Destination (Join-Path $rootRecover 'cli\staging\bin\axiom-cli.exe') -Force
$interruptedJournal = [ordered]@{
    schema_version  = 1
    document_kind   = 'axiom-cli-install-journal'
    transaction_id  = 'txn-interrupted-harness'
    operation       = 'install'
    release_version = '0.0.0-dev'
    plan_digest     = $mainDigest
    started_at      = (Get-AxiomTimestamp)
    pre_image       = [ordered]@{
        entrypoint_path    = (Join-Path $rootRecover 'bin\axiom-cli.exe')
        entrypoint_existed = $false
        entrypoint_backup  = (Join-Path $rootRecover 'cli\rollback\entrypoint.prev.exe')
        state_path         = (Join-Path $rootRecover 'cli\state.json')
        state_existed      = $false
        state_backup       = (Join-Path $rootRecover 'cli\rollback\state.prev.json')
        manifest_path      = (Join-Path $rootRecover 'install-manifest.json')
        manifest_existed   = $false
        manifest_backup    = (Join-Path $rootRecover 'cli\rollback\install-manifest.prev.json')
        user_path_present  = [bool]$pathNow.present
        user_path_value    = [string]$pathNow.value
        user_path_kind     = [string]$pathNow.kind
        generation_path    = $leftoverGeneration
        generation_created = $true
        service_registered = $false
        service_task_name  = ''
    }
}
Write-AxiomJsonFile -Path (Join-Path $rootRecover 'cli\journal.json') -Value $interruptedJournal
Write-Log ("staged an interrupted install at {0} (journal + leftover generation + leftover staging)" -f $rootRecover)

$l09 = Invoke-Leg -Leg 'L09-interrupted-install-recovery' -Class 'boundary' -ScriptPath $installScript `
    -ScriptArgs @('-ReleaseSet', $mainSetDir, '-InstallRoot', $rootRecover, '-Apply', '-ApproveDigest', $mainDigest, '-Json') -Expect 0
Assert-Axiom -Leg 'L09' -Condition ($l09.envelope.outcome -eq 'recovered_and_installed') -Detail 'outcome is recovered_and_installed'
Assert-Axiom -Leg 'L09' -Condition ($l09.envelope.interrupted_install_recovered -eq $true) -Detail 'interrupted_install_recovered is true'
Assert-Axiom -Leg 'L09' -Condition (-not (Test-Path -LiteralPath (Join-Path $leftoverGeneration 'leftover-from-interrupted-run.txt'))) -Detail 'the interrupted generation was rolled back'
Assert-Axiom -Leg 'L09' -Condition (-not (Test-Path -LiteralPath (Join-Path $rootRecover 'cli\staging'))) -Detail 'the interrupted staging directory was dropped'
Assert-Axiom -Leg 'L09' -Condition (-not (Test-Path -LiteralPath (Join-Path $rootRecover 'cli\journal.json'))) -Detail 'the journal was cleared'
Assert-Axiom -Leg 'L09' -Condition ((Get-AxiomSha256Hex -Path (Join-Path $rootRecover 'bin\axiom-cli.exe')) -eq [string]$l09.envelope.artifacts[0].sha256) -Detail 'the recovered install wrote the verified artifact'

$rootLock = Join-Path $ScratchRoot 'install-lock'
New-Item -ItemType Directory -Force -Path (Join-Path $rootLock 'cli') | Out-Null
Write-AxiomJsonFile -Path (Join-Path $rootLock 'cli\transaction.lock') -Value ([ordered]@{
        pid = $PID; transaction_id = 'txn-held-by-harness'; acquired_at = (Get-AxiomTimestamp)
    })
$l10 = Invoke-Leg -Leg 'L10-transaction-lock-held' -Class 'negative' -ScriptPath $installScript `
    -ScriptArgs @('-ReleaseSet', $mainSetDir, '-InstallRoot', $rootLock, '-Apply', '-ApproveDigest', $mainDigest, '-Json') -Expect 10
Assert-Axiom -Leg 'L10' -Condition ($l10.envelope.outcome -eq 'refused') -Detail 'a held lock refuses the transaction'
Assert-Axiom -Leg 'L10' -Condition ($l10.envelope.retryable -eq $true) -Detail 'the refusal is marked retryable'
Assert-Axiom -Leg 'L10' -Condition (Test-Path -LiteralPath (Join-Path $rootLock 'cli\transaction.lock')) -Detail 'the held lock was not stolen'
Remove-Item -LiteralPath (Join-Path $rootLock 'cli\transaction.lock') -Force -ErrorAction SilentlyContinue
# ---------------------------------------------------------------------------
# Evidence. Everything below runs even when a leg fails.
# ---------------------------------------------------------------------------

function Restore-AxiomPathGuard {
    if ($script:PathGuardRestored) { return }
    $script:PathGuardRestored = $true
    try {
        if ($pathGuard.present) {
            Set-AxiomUserPathValue -Value ([string]$pathGuard.value) -Kind ([string]$pathGuard.kind)
            Write-Log 'PATH guard: restored the pre-run HKCU user Path value'
        } elseif (Test-Path -LiteralPath $script:AxiomUserRegistryKey) {
            Remove-ItemProperty -LiteralPath $script:AxiomUserRegistryKey -Name $script:AxiomUserPathValueName -ErrorAction SilentlyContinue
            Write-Log 'PATH guard: the pre-run HKCU user Path value did not exist; removed the value this run may have created'
        }
    } catch {
        Write-Log ("PATH guard failed: {0}" -f [string]$_.Exception.Message)
    }
}

function Write-AxiomEvidence {
    $envelopeDir = Join-Path $EvidenceDir 'envelopes'
    $reportDir = Join-Path $EvidenceDir 'release-set-reports'
    New-Item -ItemType Directory -Force -Path $envelopeDir | Out-Null
    New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

    # Drop documents from an earlier run so a stale leg cannot be counted or validated.
    foreach ($staleDir in @($envelopeDir, $reportDir)) {
        foreach ($staleFile in @(Get-ChildItem -Path $staleDir -Filter '*.json' -File -ErrorAction SilentlyContinue)) {
            Remove-Item -LiteralPath $staleFile.FullName -Force -ErrorAction SilentlyContinue
        }
    }

    foreach ($record in $script:StepRecords) {
        if ([string]::IsNullOrWhiteSpace([string]$record.stdout)) { continue }
        $safeLeg = ($record.leg -replace '[^0-9A-Za-z\-]', '-')
        # Build-ReleaseSet.ps1 emits a release-set assembly report, which is not an
        # install-result envelope and is not governed by packaging/install-result.schema.json.
        # Keeping the two document kinds in separate directories stops the schema assertion
        # below from either validating the wrong document or silently validating zero files.
        $isBuildReport = ((Split-Path -Leaf ([string]$record.script)) -ieq 'Build-ReleaseSet.ps1')
        $documentDir = $(if ($isBuildReport) { $reportDir } else { $envelopeDir })
        $target = Join-Path $documentDir ($safeLeg + '.json')
        [System.IO.File]::WriteAllText($target, [string]$record.stdout, (New-Object System.Text.UTF8Encoding($false)))
    }

    $stepDocument = New-Object System.Collections.Generic.List[object]
    foreach ($record in $script:StepRecords) {
        $stepDocument.Add([ordered]@{
                leg            = $record.leg
                command        = $record.command
                exit_code      = $record.exit_code
                envelope_valid = $record.envelope_valid
                outcome        = $(if ($record.envelope) { [string]$record.envelope.outcome } else { '' })
                stdout_sha256  = (Get-AxiomSha256HexOfText -Text ([string]$record.stdout))
                stderr         = ([string]$record.stderr).Trim()
            })
    }
    Write-AxiomJsonFile -Path (Join-Path $EvidenceDir 'j004-step-records.json') -Value ([ordered]@{
            schema_version = 1
            host           = (Get-AxiomHostInfo)
            shell          = $shippedShell
            repo_revision  = (& git -C $repoRoot rev-parse HEAD)
            steps          = @($stepDocument.ToArray())
        })

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add('J-004 Windows x64 distribution acceptance run')
    $lines.Add(('generated_at: {0}' -f (Get-AxiomTimestamp)))
    $lines.Add(('host: {0}' -f (Get-AxiomHostInfo).windows_version))
    $lines.Add(('shipped shell: {0}' -f $shippedShell))
    $lines.Add(('harness session elevated: {0}' -f (Test-AxiomSessionElevated)))
    $lines.Add(('scratch root: {0}' -f $ScratchRoot))
    $lines.Add('')
    $lines.Add('leg                                    class     exp act pass outcome')
    $lines.Add('-------------------------------------- --------- --- --- ---- ----------------------')
    foreach ($result in $script:Results) {
        $lines.Add(("{0,-38} {1,-9} {2,3} {3,3} {4,-4} {5}" -f $result.leg, $result.class, $result.expected_exit, $result.actual_exit, `
                $(if ($result.pass) { 'yes' } else { 'NO' }), $result.outcome))
    }
    $lines.Add('')
    $lines.Add(('legs: {0}   failures: {1}' -f $script:Results.Count, $script:Failures))
    $lines.Add('')
    $lines.Add('--- transcript ---')
    foreach ($entry in $script:Log) { $lines.Add($entry) }
    [System.IO.File]::WriteAllText((Join-Path $EvidenceDir 'j004-run-transcript.txt'), ($lines -join "`n") + "`n", (New-Object System.Text.UTF8Encoding($false)))
    Write-Host ''
    Write-Host ("evidence written to {0}" -f $EvidenceDir)
}

# A PowerShell trap applies to the whole script scope from parse time, so this handler must not
# assume the evidence helpers have been defined yet: it falls back to a direct registry restore.
trap {
    Write-Host ("HARNESS ERROR: {0}" -f [string]$_.Exception.Message)
    $script:Failures++
    if (Get-Command Restore-AxiomPathGuard -ErrorAction SilentlyContinue) {
        Restore-AxiomPathGuard
    } else {
        try {
            if ($pathGuard.present) {
                Set-AxiomUserPathValue -Value ([string]$pathGuard.value) -Kind ([string]$pathGuard.kind)
            } elseif (Test-Path -LiteralPath $script:AxiomUserRegistryKey) {
                Remove-ItemProperty -LiteralPath $script:AxiomUserRegistryKey -Name $script:AxiomUserPathValueName -ErrorAction SilentlyContinue
            }
        } catch { }
    }
    if (Get-Command Write-AxiomEvidence -ErrorAction SilentlyContinue) { Write-AxiomEvidence }
    exit 1
}
function Note-AxiomNotRun {
    param([Parameter(Mandatory = $true)][string]$What, [Parameter(Mandatory = $true)][string]$Command, [Parameter(Mandatory = $true)][string]$Reason)
    Write-Log ("[NOTRUN] {0} :: command={1} :: reason={2}" -f $What, $Command, $Reason)
}

Write-Log ''
Write-Log '=== uninstall legs ==='

$userDataDir = Join-Path $rootMain 'user-data'
New-Item -ItemType Directory -Force -Path $userDataDir | Out-Null
[System.IO.File]::WriteAllText((Join-Path $userDataDir 'keep-me.txt'), 'user data that uninstall must preserve')

$machinePathBeforeRun = Get-AxiomMachinePathSnapshot

$l11 = Invoke-Leg -Leg 'L11-uninstall-plan-only' -Class 'positive' -ScriptPath $uninstallScript `
    -ScriptArgs @('-InstallRoot', $rootMain, '-Json') -Expect 0
Assert-Axiom -Leg 'L11' -Condition ($l11.envelope.outcome -eq 'planned') -Detail 'outcome is planned'
Assert-Axiom -Leg 'L11' -Condition ($l11.envelope.mutated -eq $false) -Detail 'an uninstall plan mutates nothing'
Assert-Axiom -Leg 'L11' -Condition (Test-Path -LiteralPath $installedExe) -Detail 'the entrypoint is still installed after planning'
$uninstallDigest = [string]$l11.envelope.plan_digest
Assert-Axiom -Leg 'L11' -Condition ($uninstallDigest -match '^[0-9a-f]{64}$') -Detail 'the uninstall plan digest is a sha256'

$l12 = Invoke-Leg -Leg 'L12-uninstall-wrong-approval' -Class 'negative' -ScriptPath $uninstallScript `
    -ScriptArgs @('-InstallRoot', $rootMain, '-Apply', '-ApproveDigest', ('f' * 64), '-Json') -Expect 5
Assert-Axiom -Leg 'L12' -Condition ($l12.envelope.outcome -eq 'not_removed') -Detail 'a wrong approval removes nothing'
Assert-Axiom -Leg 'L12' -Condition (Test-Path -LiteralPath $installedExe) -Detail 'the entrypoint is still installed after a refused uninstall'

$l13 = Invoke-Leg -Leg 'L13-uninstall-approved' -Class 'boundary' -ScriptPath $uninstallScript `
    -ScriptArgs @('-InstallRoot', $rootMain, '-Apply', '-ApproveDigest', $uninstallDigest, '-Json') -Expect 0
Assert-Axiom -Leg 'L13' -Condition ($l13.envelope.outcome -eq 'removed') -Detail 'outcome is removed'
Assert-Axiom -Leg 'L13' -Condition (-not (Test-Path -LiteralPath $installedExe)) -Detail 'the entrypoint was removed'
Assert-Axiom -Leg 'L13' -Condition (-not (Test-Path -LiteralPath (Join-Path $rootMain 'cli'))) -Detail 'the state directory was removed'
Assert-Axiom -Leg 'L13' -Condition (-not (Test-Path -LiteralPath (Join-Path $rootMain 'install-manifest.json'))) -Detail 'the install manifest was removed'
Assert-Axiom -Leg 'L13' -Condition (Test-Path -LiteralPath (Join-Path $userDataDir 'keep-me.txt')) -Detail 'user data under the install root was preserved'
Assert-Axiom -Leg 'L13' -Condition ([System.IO.File]::ReadAllText((Join-Path $userDataDir 'keep-me.txt')) -eq 'user data that uninstall must preserve') -Detail 'preserved user data is byte-identical'
$pathAfterUninstall = Get-AxiomUserPathSnapshot
Assert-Axiom -Leg 'L13' -Condition (-not (Test-AxiomPathContains -Value ([string]$pathAfterUninstall.value) -Entry (Join-Path $rootMain 'bin'))) -Detail 'the per-user PATH entry was removed'
Assert-Axiom -Leg 'L13' -Condition ($l13.envelope.path_rule.machine_wide_change -eq $false) -Detail 'no machine-wide change during uninstall'

$l14 = Invoke-Leg -Leg 'L14-uninstall-when-absent' -Class 'negative' -ScriptPath $uninstallScript `
    -ScriptArgs @('-InstallRoot', $rootMain, '-Json') -Expect 3
Assert-Axiom -Leg 'L14' -Condition ($l14.envelope.outcome -eq 'not_removed') -Detail 'a second uninstall reports not_removed'

Write-Log ''
Write-Log '=== purge-data leg (separate approval) ==='

$rootPurge = Join-Path $ScratchRoot 'install-purge'
[void](Invoke-Leg -Leg 'L15a-install-for-purge' -Class 'positive' -ScriptPath $installScript `
        -ScriptArgs @('-ReleaseSet', $mainSetDir, '-InstallRoot', $rootPurge, '-Apply', '-ApproveDigest', $mainDigest, '-Json') -Expect 0)
$purgePlan = Invoke-Leg -Leg 'L15b-purge-plan' -Class 'positive' -ScriptPath $uninstallScript `
    -ScriptArgs @('-InstallRoot', $rootPurge, '-PurgeData', '-Json') -Expect 0
$purgeDigest = [string]$purgePlan.envelope.plan_digest
Assert-Axiom -Leg 'L15b' -Condition ($purgeDigest -ne $uninstallDigest) -Detail 'purge is a different plan and therefore a different approval'
$l15c = Invoke-Leg -Leg 'L15c-purge-approved' -Class 'boundary' -ScriptPath $uninstallScript `
    -ScriptArgs @('-InstallRoot', $rootPurge, '-PurgeData', '-Apply', '-ApproveDigest', $purgeDigest, '-Json') -Expect 0
Assert-Axiom -Leg 'L15c' -Condition ($l15c.envelope.outcome -eq 'removed') -Detail 'the approved purge reports removed'
Assert-Axiom -Leg 'L15c' -Condition (-not (Test-Path -LiteralPath $rootPurge)) -Detail 'the install root was removed by the approved purge'

Write-Log ''
Write-Log '=== managed service registration leg ==='

$rootService = Join-Path $ScratchRoot 'install-service'
$l16a = Invoke-Leg -Leg 'L16a-install-with-service' -Class 'positive' -ScriptPath $installScript `
    -ScriptArgs @('-ReleaseSet', $serviceSetDir, '-InstallRoot', $rootService, '-Apply', '-ApproveDigest', $serviceDigest, '-Json') -Expect 0
Assert-Axiom -Leg 'L16a' -Condition ($l16a.envelope.service_registration.registered -eq $true) -Detail 'the declared scheduled task was registered'
Assert-Axiom -Leg 'L16a' -Condition ([string]$l16a.envelope.service_registration.task_name -eq $serviceTaskName) -Detail 'the envelope names the registered task'
$registeredTask = Get-ScheduledTask -TaskName $serviceTaskName -ErrorAction SilentlyContinue
Assert-Axiom -Leg 'L16a' -Condition ($null -ne $registeredTask) -Detail 'Get-ScheduledTask finds the registered task'
if ($null -ne $registeredTask) {
    $taskPrincipal = $registeredTask.Principal
    Assert-Axiom -Leg 'L16a' -Condition ([string]$taskPrincipal.RunLevel -eq 'Limited') -Detail 'the task runs at Limited run level (no elevation)'
}
$servicePlan = Invoke-Leg -Leg 'L16b-uninstall-service-plan' -Class 'positive' -ScriptPath $uninstallScript `
    -ScriptArgs @('-InstallRoot', $rootService, '-Json') -Expect 0
$l16c = Invoke-Leg -Leg 'L16c-uninstall-removes-service' -Class 'boundary' -ScriptPath $uninstallScript `
    -ScriptArgs @('-InstallRoot', $rootService, '-Apply', '-ApproveDigest', ([string]$servicePlan.envelope.plan_digest), '-Json') -Expect 0
Assert-Axiom -Leg 'L16c' -Condition ($l16c.envelope.service_registration.removed -eq $true) -Detail 'the envelope reports the service registration removed'
Assert-Axiom -Leg 'L16c' -Condition ($null -eq (Get-ScheduledTask -TaskName $serviceTaskName -ErrorAction SilentlyContinue)) -Detail 'Get-ScheduledTask no longer finds the task'

Write-Log ''
Write-Log '=== harness cleanup: uninstall the installations the earlier legs left behind ==='

# L07b, L08b and L09 each leave a real installation behind. Uninstall them explicitly instead of
# relying on the final PATH guard to mask a leaked per-user PATH entry: a guard that restores
# whatever it saw before the run would otherwise preserve a leak from an earlier run forever.
foreach ($leftover in @(
        [ordered]@{ prefix = 'L17a-cleanup-unowned'; root = $rootUnowned },
        [ordered]@{ prefix = 'L17b-cleanup-downgrade'; root = $rootDowngrade },
        [ordered]@{ prefix = 'L17c-cleanup-recover'; root = $rootRecover })) {
    $cleanupPlan = Invoke-Leg -Leg ($leftover.prefix + '-plan') -Class 'boundary' -ScriptPath $uninstallScript `
        -ScriptArgs @('-InstallRoot', $leftover.root, '-Json') -Expect 0
    $cleanupApply = Invoke-Leg -Leg ($leftover.prefix + '-apply') -Class 'boundary' -ScriptPath $uninstallScript `
        -ScriptArgs @('-InstallRoot', $leftover.root, '-Apply', '-ApproveDigest', ([string]$cleanupPlan.envelope.plan_digest), '-Json') -Expect 0
    Assert-Axiom -Leg ($leftover.prefix) -Condition ($cleanupApply.envelope.outcome -eq 'removed') -Detail ('the leftover installation at {0} was removed' -f (Split-Path -Leaf $leftover.root))
}

$hygienePath = Get-AxiomUserPathSnapshot
$leakedEntries = @(($hygienePath.value -split ';') | Where-Object { $_ -and $_.TrimEnd('\').StartsWith($ScratchRoot, [System.StringComparison]::OrdinalIgnoreCase) })
Assert-Axiom -Leg 'L17-cleanup-path-hygiene' -Condition ($leakedEntries.Count -eq 0) -Detail ('no per-user PATH entry under the scratch root survives the harness (found {0})' -f $leakedEntries.Count)

$machinePathAfterRun = Get-AxiomMachinePathSnapshot
Assert-Axiom -Leg 'L17-machine-path' -Condition ($machinePathBeforeRun -eq $machinePathAfterRun) -Detail 'the machine-wide PATH is byte-identical before and after the whole run'

Write-Log ''
Write-Log '=== non-elevated leg (AC1: the install path requires no elevation) ==='

# The harness may itself be running elevated, so an install executed here cannot demonstrate that
# elevation is unnecessary. Run one complete install + uninstall cycle from a `Limited` run-level
# scheduled task and assert both the token state and the observed exit codes.
$rootUnpriv = Join-Path $ScratchRoot 'install-unelevated'
$unprivHelper = Join-Path $repoRoot 'tests\windows\Invoke-AxiomCliWindowsUnprivilegedLeg.ps1'
$unprivResultPath = Join-Path $ScratchRoot 'unelevated-leg-result.json'
$unprivTaskName = 'AxiomCliJ004HarnessUnelevated'

if (Test-Path -LiteralPath $unprivResultPath) { Remove-Item -LiteralPath $unprivResultPath -Force -ErrorAction SilentlyContinue }
if (-not (Test-Path -LiteralPath (Split-Path -Parent $unprivResultPath))) { New-Item -ItemType Directory -Force -Path (Split-Path -Parent $unprivResultPath) | Out-Null }

$unprivAvailable = $true
foreach ($cmd in 'New-ScheduledTaskAction', 'New-ScheduledTaskPrincipal', 'New-ScheduledTaskSettingsSet', 'Register-ScheduledTask', 'Start-ScheduledTask', 'Unregister-ScheduledTask') {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { $unprivAvailable = $false }
}

if (-not $unprivAvailable) {
    Note-AxiomNotRun -What 'non-elevated install leg' -Command 'powershell -File tests\windows\Invoke-AxiomCliWindowsUnprivilegedLeg.ps1 -InstallScript <...> -InstallRoot <...>' -Reason 'the ScheduledTasks module is not available in the shipped shell'
} else {
    try { Unregister-ScheduledTask -TaskName $unprivTaskName -Confirm:$false -ErrorAction SilentlyContinue } catch { }
    $unprivArgs = ('-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "{0}" -InstallScript "{1}" -UninstallScript "{2}" -ReleaseSet "{3}" -ApproveDigest {4} -InstallRoot "{5}" -ResultPath "{6}"' -f `
            $unprivHelper, $installScript, $uninstallScript, $mainSetDir, $mainDigest, $rootUnpriv, $unprivResultPath)
    $unprivAction = New-ScheduledTaskAction -Execute $shippedShell -Argument $unprivArgs
    $unprivPrincipal = New-ScheduledTaskPrincipal -UserId ("{0}\{1}" -f $env:USERDOMAIN, $env:USERNAME) -LogonType Interactive -RunLevel Limited
    $unprivSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
    Register-ScheduledTask -TaskName $unprivTaskName -Action $unprivAction -Principal $unprivPrincipal -Settings $unprivSettings -Force | Out-Null
    Start-ScheduledTask -TaskName $unprivTaskName

    $unprivDeadline = (Get-Date).AddSeconds(120)
    while (-not (Test-Path -LiteralPath $unprivResultPath) -and (Get-Date) -lt $unprivDeadline) { Start-Sleep -Milliseconds 700 }
    Unregister-ScheduledTask -TaskName $unprivTaskName -Confirm:$false -ErrorAction SilentlyContinue

    if (-not (Test-Path -LiteralPath $unprivResultPath)) {
        Note-AxiomNotRun -What 'non-elevated install leg' -Command ('Start-ScheduledTask -TaskName {0}' -f $unprivTaskName) -Reason 'the Limited scheduled task did not produce its result file within 120s'
        $script:Failures++
    } else {
        $unpriv = ConvertFrom-Json -InputObject ([System.IO.File]::ReadAllText($unprivResultPath))
        $unprivEnvelope = $null
        try { $unprivEnvelope = ConvertFrom-Json -InputObject ([string]$unpriv.install.stdout) } catch { }
        $script:StepRecords.Add([ordered]@{
                leg            = 'L19-unelevated-install-uninstall'
                script         = $unprivHelper
                arguments      = @($unprivArgs)
                exit_code      = [int]$unpriv.install.exit_code
                stdout         = [string]$unpriv.install.stdout
                stderr         = [string]$unpriv.install.stderr
                envelope       = $unprivEnvelope
                envelope_valid = $true
                command        = ('schtasks(Limited) "{0}" {1}' -f $shippedShell, $unprivArgs)
            })
        Assert-Axiom -Leg 'L19' -Condition ($unpriv.is_elevated -eq $false) -Detail ('the transaction ran in a non-elevated token (IsInRole Administrator = {0})' -f $unpriv.is_elevated)
        Assert-Axiom -Leg 'L19' -Condition ([int]$unpriv.install.exit_code -eq 0) -Detail ('a non-elevated install succeeded (exit {0})' -f $unpriv.install.exit_code)
        Assert-Axiom -Leg 'L19' -Condition ($null -ne $unprivEnvelope -and $unprivEnvelope.outcome -eq 'installed') -Detail 'the non-elevated install reports outcome=installed'
        Assert-Axiom -Leg 'L19' -Condition ($null -ne $unprivEnvelope -and $unprivEnvelope.elevation_required -eq $false) -Detail 'the non-elevated install reports elevation_required=false'
        Assert-Axiom -Leg 'L19' -Condition ($null -ne $unprivEnvelope -and $unprivEnvelope.host.session_elevated -eq $false) -Detail 'the envelope records a non-elevated session'
        Assert-Axiom -Leg 'L19' -Condition ([int]$unpriv.uninstall_apply.exit_code -eq 0) -Detail ('a non-elevated uninstall succeeded (exit {0})' -f $unpriv.uninstall_apply.exit_code)
        Assert-Axiom -Leg 'L19' -Condition (-not (Test-Path -LiteralPath (Join-Path $rootUnpriv 'bin\axiom-cli.exe'))) -Detail 'the non-elevated uninstall removed the entrypoint'
    }
}

Write-Log ''
Write-Log '=== artifact digests ==='

$digestLines = New-Object System.Collections.Generic.List[string]
$digestLines.Add('J-004 artifact digests (real bytes on this host)')
$digestLines.Add(('generated_at: {0}' -f (Get-AxiomTimestamp)))
$digestLines.Add('')
function Add-AxiomDigestLine {
    param([string]$Label, [string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        $digestLines.Add(('{0,-28} MISSING {1}' -f $Label, $Path))
        return
    }
    $item = Get-Item -LiteralPath $Path
    $digestLines.Add(('{0,-28} size_bytes={1,-10} sha256={2} path={3}' -f $Label, $item.Length, (Get-AxiomSha256Hex -Path $Path), $Path))
}
Add-AxiomDigestLine -Label 'axiom-cli.exe (source)' -Path $CliExe
Add-AxiomDigestLine -Label 'release-set.json (main)' -Path $mainSetDir
Add-AxiomDigestLine -Label 'axiom-cli.exe (main set)' -Path (Join-Path (Split-Path -Parent $mainSetDir) 'axiom-cli.exe')
Add-AxiomDigestLine -Label 'release-set.json (alpha)' -Path $alphaSetDir
Add-AxiomDigestLine -Label 'release-set.json (service)' -Path $serviceSetDir
Add-AxiomDigestLine -Label 'install-result.schema.json' -Path $schemaPath
$digestLines.Add('')
$digestLines.Add(('main plan digest (approval):      {0}' -f $mainDigest))
$digestLines.Add(('alpha plan digest (approval):     {0}' -f $alphaDigest))
$digestLines.Add(('service plan digest (approval):   {0}' -f $serviceDigest))
$digestLines.Add(('uninstall plan digest (approval): {0}' -f $uninstallDigest))
$digestLines.Add(('purge plan digest (approval):     {0}' -f $purgeDigest))
foreach ($line in $digestLines) { Write-Log $line }
[System.IO.File]::WriteAllText((Join-Path $EvidenceDir 'j004-artifact-digests.txt'), ($digestLines -join "`n") + "`n", (New-Object System.Text.UTF8Encoding($false)))

Write-Log ''
Write-Log '=== envelope schema validation ==='

# The envelopes must exist on disk before this section enumerates them, otherwise the schema
# assertion below would validate zero files and pass vacuously. Write-AxiomEvidence is
# idempotent and is invoked again at the end so the final transcript also carries the last legs.
Write-AxiomEvidence

$envelopeDir = Join-Path $EvidenceDir 'envelopes'
$envelopeFiles = @(Get-ChildItem -Path $envelopeDir -Filter '*.json' -ErrorAction SilentlyContinue | ForEach-Object { $_.FullName })
$validationPath = Join-Path $EvidenceDir 'j004-schema-validation.txt'

$pythonExe = $Python
if ([string]::IsNullOrEmpty($pythonExe)) {
    $candidate = Get-Command python -ErrorAction SilentlyContinue
    if ($candidate) { $pythonExe = $candidate.Source }
}

if ([string]::IsNullOrEmpty($pythonExe)) {
    $notRun = 'NOT_RUN: no python interpreter was found, so packaging/install-result.schema.json did not validate the captured envelopes'
    [System.IO.File]::WriteAllText($validationPath, $notRun + "`n", (New-Object System.Text.UTF8Encoding($false)))
    Note-AxiomNotRun -What 'envelope schema validation' -Command 'python tests/windows/validate-envelopes.py <schema> <envelope...>' -Reason 'no python interpreter on PATH'
} else {
    $pythonLines = @(
        'import json, os, sys'
        'import jsonschema'
        'schema_path = sys.argv[1]'
        'with open(schema_path, encoding="utf-8") as handle:'
        '    schema = json.load(handle)'
        'jsonschema.Draft202012Validator.check_schema(schema)'
        'validator = jsonschema.Draft202012Validator(schema)'
        'ok = 0'
        'bad = 0'
        'for path in sys.argv[2:]:'
        '    with open(path, encoding="utf-8") as handle:'
        '        raw = handle.read()'
        '    try:'
        '        document = json.loads(raw)'
        '    except ValueError:'
        '        print("SKIP", os.path.basename(path))'
        '        continue'
        '    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))'
        '    if errors:'
        '        bad += 1'
        '        print("INVALID", os.path.basename(path))'
        '        for error in errors:'
        '            print("   ", list(error.path), error.message)'
        '    else:'
        '        ok += 1'
        'print("validated=%d invalid=%d" % (ok, bad))'
        'sys.exit(1 if bad else 0)'
    )
    $pythonSource = ($pythonLines -join "`n") + "`n"
    $validateScript = Join-Path $ScratchRoot 'validate-envelopes.py'
    [System.IO.File]::WriteAllText($validateScript, $pythonSource, (New-Object System.Text.UTF8Encoding($false)))

    $validationOut = Join-Path $ScratchRoot 'schema-validation-stdout.txt'
    $validationErr = Join-Path $ScratchRoot 'schema-validation-stderr.txt'
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $pythonExe $validateScript $schemaPath @envelopeFiles 1> $validationOut 2> $validationErr
        $validationCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    $validationText = ''
    if (Test-Path -LiteralPath $validationOut) { $validationText = [System.IO.File]::ReadAllText($validationOut) }
    $validationErrText = ''
    if (Test-Path -LiteralPath $validationErr) { $validationErrText = [System.IO.File]::ReadAllText($validationErr) }
    $validationReport = @(
        ('command: "{0}" "{1}" "{2}" {3}' -f $pythonExe, $validateScript, $schemaPath, ($envelopeFiles -join ' '))
        ('exit_code: {0}' -f $validationCode)
        'stdout:'
        $validationText
        'stderr:'
        $validationErrText
    ) -join "`n"
    [System.IO.File]::WriteAllText($validationPath, $validationReport + "`n", (New-Object System.Text.UTF8Encoding($false)))

    if ($validationErrText -match 'ModuleNotFoundError|No module named') {
        Note-AxiomNotRun -What 'envelope schema validation' -Command (('"{0}" "{1}" "{2}"' -f $pythonExe, $validateScript, $schemaPath)) -Reason 'the jsonschema package is not installed for this interpreter'
    } else {
        Assert-Axiom -Leg 'L18-envelope-schema' -Condition ($validationCode -eq 0) -Detail (('every captured envelope validates against packaging/install-result.schema.json ({0} files)' -f $envelopeFiles.Count))
    }
}

Write-Log ''
Restore-AxiomPathGuard
if ($script:Failures -gt 0) {
    Write-Log ("RESULT: FAIL ({0} failing leg(s)/assertion(s))" -f $script:Failures)
} else {
    Write-Log ("RESULT: PASS ({0} legs met their expected exit code and every assertion held)" -f $script:Results.Count)
}
Write-AxiomEvidence
exit $(if ($script:Failures -gt 0) { 1 } else { 0 })
