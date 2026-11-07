param(
    [Parameter(Mandatory = $true)][string]$Command,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')]
    [string]$ScratchSubdir = 'session'
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if (-not (Test-Path -LiteralPath (Join-Path $root 'AGENTS.md'))) {
    throw 'Cannot identify workspace root.'
}
$scratch = Join-Path $root ('tmp\' + $ScratchSubdir)
foreach ($candidate in @((Join-Path $root 'tmp'), $scratch)) {
    if (Test-Path -LiteralPath $candidate) {
        if ((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Scratch path is a reparse point: $candidate"
        }
    }
}
New-Item -ItemType Directory -Path $scratch -Force | Out-Null
$previousLocation = Get-Location
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
try {
    Set-Location -LiteralPath $root
    $env:TEMP = $scratch
    $env:TMP = $scratch
    # Command is trusted caller-supplied PowerShell, not external data.
    & ([scriptblock]::Create($Command))
}
finally {
    Set-Location -LiteralPath $previousLocation.Path
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
}
