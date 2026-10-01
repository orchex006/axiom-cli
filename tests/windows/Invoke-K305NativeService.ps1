#requires -version 5.1
<# Native, per-user Scheduled Task exercise for an installed candidate daemon. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$ScratchRoot,
    [Parameter(Mandatory = $true)][ValidatePattern('^AxiomK305[A-Za-z0-9]+$')][string]$TaskName
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$root = [System.IO.Path]::GetFullPath($InstallRoot)
$scratch = [System.IO.Path]::GetFullPath($ScratchRoot)
if (-not $root.StartsWith(($scratch.TrimEnd('\') + '\'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'installed root must be inside the named test scratch directory'
}
$daemon = Join-Path $root 'cli\generations\0.1.1\axiom-graphd.exe'
$state = Join-Path $root 'cli\state.json'
if (-not (Test-Path -LiteralPath $daemon -PathType Leaf) -or -not (Test-Path -LiteralPath $state -PathType Leaf)) {
    throw 'installed daemon or distribution state is missing'
}
$installed = [System.IO.File]::ReadAllText($state) | ConvertFrom-Json
$row = @($installed.artifacts | Where-Object { [string]$_.name -ceq 'axiom-graphd.exe' })
if ($row.Count -ne 1) { throw 'daemon ownership record is missing' }
$sha = [System.BitConverter]::ToString(([System.Security.Cryptography.SHA256]::Create()).ComputeHash([System.IO.File]::ReadAllBytes($daemon))).Replace('-', '').ToLowerInvariant()
if ($sha -cne [string]$row[0].sha256) { throw 'installed daemon differs from ownership record' }
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    throw 'test task name is already owned; refusing to replace it'
}
$source = Join-Path $scratch 'source-repo\src\Widget.cs'
$catalog = Join-Path $scratch 'source-repo\.axiom\graph\windows-demo\_catalog\live\current.json'
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'real source fixture is missing' }
$wrapper = Join-Path $scratch 'Start-K305Graphd.ps1'
if (Test-Path -LiteralPath $wrapper) { throw 'test wrapper already exists' }
$quotedRoot = $root.Replace("'", "''")
$quotedDaemon = $daemon.Replace("'", "''")
$systemBin = (Join-Path $env:SystemRoot 'System32').Replace("'", "''")
$script = @"
`$env:AXIOM_HOME = '$quotedRoot'
`$env:PATH = '$systemBin'
& '$quotedDaemon' serve --json
exit `$LASTEXITCODE
"@
[System.IO.File]::WriteAllText($wrapper, $script)
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$shell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$action = New-ScheduledTaskAction -Execute $shell -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $wrapper + '"')
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$registered = $false
$started = $false
$stopped = $false
$first = $null
$second = $null
try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Principal $principal -Trigger $trigger -Settings $settings | Out-Null
    $registered = $true
    $task = Get-ScheduledTask -TaskName $TaskName
    if ([string]$task.Principal.RunLevel -ne 'Limited') { throw 'task is not Limited' }
    Start-ScheduledTask -TaskName $TaskName
    for ($n = 0; $n -lt 60; $n++) {
        if ((Get-ScheduledTask -TaskName $TaskName).State -eq 'Running' -and (Test-Path -LiteralPath $catalog -PathType Leaf)) {
            $first = ([System.IO.File]::ReadAllText($catalog) | ConvertFrom-Json).generation_id
            break
        }
        [System.Threading.Thread]::Sleep(500)
    }
    if (-not $first) { throw 'scheduled daemon did not publish initial catalog' }
    [System.IO.File]::AppendAllText($source, 'public sealed class WatcherAdded { }' + [Environment]::NewLine)
    for ($n = 0; $n -lt 60; $n++) {
        if (Test-Path -LiteralPath $catalog -PathType Leaf) {
            $observed = ([System.IO.File]::ReadAllText($catalog) | ConvertFrom-Json).generation_id
            if ($observed -and $observed -cne $first) { $second = $observed; break }
        }
        [System.Threading.Thread]::Sleep(500)
    }
    if (-not $second) { throw 'scheduled daemon watcher did not advance the catalog' }
    if ((Get-ScheduledTask -TaskName $TaskName).State -ne 'Running') { throw 'daemon task stopped before explicit stop' }
    $started = $true
    Stop-ScheduledTask -TaskName $TaskName
    for ($n = 0; $n -lt 30; $n++) {
        if ((Get-ScheduledTask -TaskName $TaskName).State -ne 'Running') { $stopped = $true; break }
        [System.Threading.Thread]::Sleep(500)
    }
    if (-not $stopped) { throw 'scheduled daemon did not stop' }
}
finally {
    if ($registered) {
        try { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue } catch { }
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction Stop
    }
    $processes = @(Get-CimInstance Win32_Process -Filter "name='axiom-graphd.exe'" -ErrorAction SilentlyContinue |
        Where-Object { [string]$_.ExecutablePath -ieq $daemon })
    foreach ($process in $processes) { Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop }
}
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { throw 'owned task remained after removal' }
if (-not (Test-Path -LiteralPath (Join-Path $root 'user-data\sentinel.txt') -PathType Leaf)) {
    throw 'user data sentinel was removed'
}
[pscustomobject]@{ status = 'passed'; task_name = $TaskName; registered = $registered; started = $started;
    stopped = $stopped; removed = $true; run_level = 'Limited'; first_generation = $first;
    updated_generation = $second; installed_daemon_sha256 = $sha; user_data_preserved = $true } |
    ConvertTo-Json -Compress
