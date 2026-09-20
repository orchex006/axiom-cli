<#
    Run one full axiom-cli install + uninstall cycle from a non-elevated session.

    AC1 of card J-004 requires that the Windows install path "requires no elevation". The acceptance
    harness itself runs in whatever session invoked it, which may be elevated, so an install executed
    there cannot prove that clause. This helper is the payload the harness launches through a
    `Limited` run-level scheduled task: it records the token's elevation state, performs the
    transaction and writes the observed exit codes and raw stdout/stderr for the harness to assert on.

    It is invoked by tests/windows/Invoke-AxiomCliWindowsDistributionTests.ps1 and is not a shipped
    installer entrypoint.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InstallScript,
    [Parameter(Mandatory = $true)][string]$UninstallScript,
    [Parameter(Mandatory = $true)][string]$ReleaseSet,
    [Parameter(Mandatory = $true)][string]$ApproveDigest,
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$ResultPath
)

$ErrorActionPreference = 'Continue'
$workDir = Split-Path -Parent $ResultPath

function Invoke-ShippedScript {
    param([string]$ScriptPath, [string[]]$ScriptArgs, [string]$Tag)
    $outPath = Join-Path $workDir ('unelevated-' + $Tag + '-stdout.json')
    $errPath = Join-Path $workDir ('unelevated-' + $Tag + '-stderr.txt')
    $shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    & $shell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $ScriptPath @ScriptArgs 1> $outPath 2> $errPath
    $code = $LASTEXITCODE
    return [ordered]@{
        exit_code = $code
        stdout    = $(if (Test-Path -LiteralPath $outPath) { [System.IO.File]::ReadAllText($outPath) } else { '' })
        stderr    = $(if (Test-Path -LiteralPath $errPath) { [System.IO.File]::ReadAllText($errPath) } else { '' })
    }
}

$result = [ordered]@{
    is_elevated       = $null
    user              = $null
    install           = $null
    uninstall_plan    = $null
    uninstall_apply   = $null
    error             = $null
}

try {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    $result.is_elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    $result.user = $identity.Name

    $result.install = Invoke-ShippedScript -ScriptPath $InstallScript -Tag 'install' -ScriptArgs @(
        '-ReleaseSet', $ReleaseSet, '-InstallRoot', $InstallRoot, '-Apply', '-ApproveDigest', $ApproveDigest, '-Json')

    $plan = Invoke-ShippedScript -ScriptPath $UninstallScript -Tag 'uninstall-plan' -ScriptArgs @(
        '-InstallRoot', $InstallRoot, '-Json')
    $result.uninstall_plan = $plan

    $planDigest = ''
    if ($plan.exit_code -eq 0 -and -not [string]::IsNullOrWhiteSpace($plan.stdout)) {
        try { $planDigest = [string](ConvertFrom-Json -InputObject $plan.stdout).plan_digest } catch { }
    }

    $result.uninstall_apply = Invoke-ShippedScript -ScriptPath $UninstallScript -Tag 'uninstall-apply' -ScriptArgs @(
        '-InstallRoot', $InstallRoot, '-Apply', '-ApproveDigest', $planDigest, '-Json')
} catch {
    $result.error = [string]$_.Exception.Message
}

[System.IO.File]::WriteAllText($ResultPath, (($result | ConvertTo-Json -Depth 8) + "`n"), (New-Object System.Text.UTF8Encoding($false)))

if ($null -ne $result.error) { exit 8 }
if ($result.install.exit_code -ne 0) { exit 8 }
if ($result.uninstall_plan.exit_code -ne 0) { exit 8 }
if ($result.uninstall_apply.exit_code -ne 0) { exit 8 }
exit 0