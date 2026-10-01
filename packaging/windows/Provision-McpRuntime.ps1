#requires -version 5.1
<# Bootstrap the owned MCP runtime without relying on an installed Python. #>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidateSet('provision', 'status', 'rollback', 'remove')][string]$Action,
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$RuntimeArchive,
    [Parameter(Mandatory = $true)][string]$RuntimeSha256,
    [string]$PipWheel,
    [string]$PipSha256,
    [string]$Inputs,
    [string]$InputsSha256,
    [string]$SourceRevision,
    [string]$Version = '0.1.1',
    [switch]$InterruptBeforeActivate
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

function Assert-Digest {
    param([string]$Path, [string]$Expected)
    if ($Expected -cnotmatch '^[0-9a-f]{64}$') { throw 'digest must be lowercase SHA-256' }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'runtime input is missing' }
    $stream = [System.IO.File]::OpenRead($Path)
    $hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $actual = [System.BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $stream.Dispose()
        $hasher.Dispose()
    }
    if ($actual -cne $Expected) { throw 'runtime input digest mismatch' }
}

try {
    if (-not [System.IO.Path]::IsPathRooted($Root)) { throw 'root must be absolute' }
    $rootPath = [System.IO.Path]::GetFullPath($Root)
    $runtimeRoot = Join-Path $rootPath 'mcp-runtime'
    $bootstrapRoot = Join-Path $runtimeRoot 'bootstrap'
    Assert-Digest -Path $RuntimeArchive -Expected $RuntimeSha256
    New-Item -ItemType Directory -Force -Path $bootstrapRoot | Out-Null
    $nonce = [guid]::NewGuid().ToString('N')
    $stage = Join-Path $bootstrapRoot $nonce
    $fullBootstrap = [System.IO.Path]::GetFullPath($bootstrapRoot).TrimEnd('\') + '\'
    $fullStage = [System.IO.Path]::GetFullPath($stage)
    if (-not $fullStage.StartsWith($fullBootstrap, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'bootstrap stage escapes the owned runtime root'
    }
    New-Item -ItemType Directory -Path $stage | Out-Null
    $marker = Join-Path $stage 'k304-owned.marker'
    [System.IO.File]::WriteAllText($marker, $nonce)
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [System.IO.Compression.ZipFile]::ExtractToDirectory($RuntimeArchive, $stage)
        $python = Join-Path $stage 'python.exe'
        if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
            throw 'pinned runtime archive has no python.exe'
        }
        $script = Join-Path $PSScriptRoot 'Provision-McpRuntime.py'
        $arguments = @($script, $Action, '--root', $rootPath)
        if ($Action -eq 'provision') {
            Assert-Digest -Path $PipWheel -Expected $PipSha256
            Assert-Digest -Path $Inputs -Expected $InputsSha256
            $arguments += @('--version', $Version, '--source-revision', $SourceRevision,
                            '--runtime', $RuntimeArchive, '--runtime-sha256', $RuntimeSha256,
                            '--pip-wheel', $PipWheel, '--pip-wheel-sha256', $PipSha256,
                            '--inputs', $Inputs, '--inputs-sha256', $InputsSha256)
            if ($InterruptBeforeActivate) { $arguments += '--interrupt-before-activate' }
        }
        & $python @arguments
        $code = $LASTEXITCODE
        if ($code -ne 0) { exit $code }
    }
    finally {
        if ((Test-Path -LiteralPath $stage) -and
            (Test-Path -LiteralPath $marker -PathType Leaf) -and
            ([System.IO.File]::ReadAllText($marker) -ceq $nonce) -and
            ($fullStage.StartsWith($fullBootstrap, [StringComparison]::OrdinalIgnoreCase))) {
            Remove-Item -LiteralPath $stage -Recurse -Force
        }
    }
    exit 0
}
catch {
    [Console]::Error.WriteLine('runtime bootstrap refused: ' + $_.Exception.Message)
    exit 9
}
