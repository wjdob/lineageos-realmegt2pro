<#
.SYNOPSIS
Read and verify current system/product images before an optional-app trial.
.DESCRIPTION
Requires the reviewed serial, slot and incremental build, existing rooted ADB,
Enforcing LineageOS 23.2, read-only ext4 sources and no pending virtual A/B merge.
Rechecks boot identity, mappings and source hashes. Partial files and an incomplete
receipt remain on failure. No device changes, ADB root request or restore operation.
Sequential reads are not an atomic snapshot, personal-data or full-device backup.
.EXAMPLE
./tools/device/backup_oem_os.ps1 -OutputDirectory <new-private-directory> -AdbPath <adb.exe> -Serial <serial> -ExpectedSlot b -ExpectedIncremental <reviewed-build>
#>
param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$true)][string]$AdbPath,
    [Parameter(Mandatory=$true)][string]$Serial,
    [Parameter(Mandatory=$true)][ValidateSet('a','b')][string]$ExpectedSlot,
    [Parameter(Mandatory=$true)][string]$ExpectedIncremental
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Split-Path (Split-Path $PSScriptRoot -Parent) -Parent))
$output = [IO.Path]::GetFullPath($OutputDirectory)
$privatePrefix = [IO.Path]::Combine($repo, '.local') + [IO.Path]::DirectorySeparatorChar
if (-not $output.StartsWith($privatePrefix, [StringComparison]::OrdinalIgnoreCase) -or
    (Test-Path -LiteralPath $output) -or $Serial -notmatch '^[A-Za-z0-9]+$' -or
    $ExpectedIncremental -notmatch '^[A-Za-z0-9._-]+$') {
    throw 'Use an exact serial and a NEW directory under repository .local.'
}
$AdbPath = [IO.Path]::GetFullPath($AdbPath)
if (-not (Test-Path -LiteralPath $AdbPath -PathType Leaf)) { throw 'ADB executable missing.' }
[void](New-Item -ItemType Directory -Path $output)
$record = [ordered]@{
    observed_utc = [DateTime]::UtcNow.ToString('o')
    serial = $Serial
    expected_slot = $ExpectedSlot
    expected_incremental = $ExpectedIncremental
    complete = $false
    commands = @()
    captures = @()
    scope = 'Read-only verified current system/product image backups; sequential, not an atomic snapshot or userdata backup. No device write, wipe, slot or firmware operation.'
}
function Read-Text([string]$Command) {
    $text = (& $AdbPath -s $Serial shell $Command | Out-String).Replace("`r`n", "`n").Trim()
    $exitCode = $LASTEXITCODE
    $record.commands += [ordered]@{ command = $Command; exit_code = $exitCode; stdout = $text }
    if ($exitCode -ne 0) { throw ('Read-only ADB failed: ' + $Command) }
    return $text
}
function Save-Record {
    $record | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $output 'capture.json') -Encoding UTF8
}
function Check-State {
    if ((Read-Text 'getprop ro.product.model') -ne 'RMX3301' -or
        (Read-Text 'getprop ro.product.device') -ne 'RED8ACL1' -or
        (Read-Text 'getprop sys.boot_completed') -ne '1' -or
        (Read-Text 'getprop ro.lineage.version') -notlike '23.2-*' -or
        (Read-Text 'getprop ro.build.version.incremental') -ne $ExpectedIncremental -or
        (Read-Text 'getprop ro.boot.slot_suffix') -ne ('_'+$ExpectedSlot) -or
        (Read-Text 'getprop ro.boot.vbmeta.device_state') -ne 'unlocked' -or
        (Read-Text 'getenforce') -ne 'Enforcing' -or
        (Read-Text 'id') -notmatch 'uid=0\(root\)' -or
        (Read-Text 'snapshotctl dump') -notmatch '^Update state: none(\n|$)') {
        throw 'Expected device/build/slot/root/enforcement/snapshot state changed.'
    }
    $bootId = Read-Text 'cat /proc/sys/kernel/random/boot_id'
    if ($bootId -notmatch '^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$' -or
        ($record.Contains('boot_id') -and $record.boot_id -ne $bootId)) {
        throw 'Device rebooted or boot identity unavailable during capture.'
    }
    $record.boot_id = $bootId
}
function Read-Source([string]$Part) {
    if ($Part -notin @('system','product')) { throw 'Unexpected partition.' }
    $block = '/dev/block/mapper/'+$Part+'_'+$ExpectedSlot
    $real = Read-Text ('readlink -f '+$block)
    if ($real -notmatch '^/dev/block/dm-[0-9]+$') { throw 'Unexpected mapper target.' }
    if ((Read-Text ('cat /sys/class/block/'+(Split-Path $real -Leaf)+'/dm/name')) -ne ($Part+'_'+$ExpectedSlot)) {
        throw 'Mapper identity mismatch.'
    }
    $mountPoint = if ($Part -eq 'system') { '/' } else { '/product' }
    $mount = @((Read-Text 'cat /proc/mounts') -split "`n" | ForEach-Object { ,($_ -split '\s+') } |
        Where-Object { $_[1] -eq $mountPoint })
    if ($mount.Count -ne 1 -or $mount[0][2] -ne 'ext4' -or
        ($mount[0][3] -split ',') -notcontains 'ro') { throw 'Source is not mounted read-only ext4.' }
    if ((Read-Text ('readlink -f '+$mount[0][0])) -ne $real) { throw 'Mounted source mismatch.' }
    $size = [long](Read-Text ('blockdev --getsize64 '+$block))
    if ($size -le 0 -or $size -gt 8GB) { throw 'Unexpected source size.' }
    return @{partition=$Part+'_'+$ExpectedSlot;source=$block;resolved=$real;bytes=$size}
}
function Compare-Source($Expected) {
    $part = $Expected.partition -replace '_[ab]$',''
    $current = Read-Source $part
    if ($current.source -ne $Expected.source -or $current.resolved -ne $Expected.resolved -or
        $current.bytes -ne $Expected.bytes) { throw 'Source mapping or size changed during capture.' }
}
function Copy-AdbBlock([string]$Block, [string]$Destination) {
    # Fixed allowlisted read source; no Windows shell and no text conversion of image bytes.
    if ($Block -notmatch '^/dev/block/mapper/(system|product)_[ab]$') { throw 'Unexpected block source.' }
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $AdbPath
    $start.Arguments = '-s ' + $Serial + ' exec-out cat ' + $Block
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    $stream = [IO.File]::Open($Destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        if (-not $process.Start()) { throw 'ADB reader did not start.' }
        $copy = $process.StandardOutput.BaseStream.CopyToAsync($stream, 1048576)
        $errors = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(600000)) {
            $process.Kill()
            $process.WaitForExit()
            throw 'Read-only image transfer timed out; partial file retained.'
        }
        [void]$copy.GetAwaiter().GetResult()
        $stderr = $errors.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) { throw ('Image reader failed: ' + $stderr) }
        $stream.Flush()
    } finally {
        $stream.Dispose()
        $process.Dispose()
    }
}
try {
    Check-State
    $record.slot = '_'+$ExpectedSlot
    $disk = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($output))
    foreach ($part in @('system', 'product')) {
        Check-State
        $source = Read-Source $part
        $block = $source.source; $real = $source.resolved; $size = $source.bytes
        if ($disk.AvailableFreeSpace -lt ($size + 5GB)) { throw 'Backup would breach the 5-GiB disk floor.' }
        $before = ((Read-Text ('sha256sum ' + $block)) -split '\s+')[0]
        if ($before -notmatch '^[0-9a-f]{64}$') { throw 'Invalid source SHA-256.' }
        $file = Join-Path $output ($source.partition+'.img')
        Copy-AdbBlock $block $file
        Check-State
        Compare-Source $source
        $after = ((Read-Text ('sha256sum ' + $block)) -split '\s+')[0]
        $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        if ((Get-Item -LiteralPath $file).Length -ne $size -or $before -ne $after -or $hash -ne $before) {
            throw 'Image size or before/after/off-device hash mismatch.'
        }
        $record.captures += [ordered]@{ partition = $source.partition; source = $block; resolved = $real;
            bytes = $size; sha256 = $hash; file = $file.Substring($repo.Length + 1).Replace('\', '/') }
        Save-Record
        Write-Output ('Verified current '+$source.partition)
    }
    Check-State
    foreach ($capture in $record.captures) {
        Compare-Source $capture
        $final = ((Read-Text ('sha256sum '+$capture.source)) -split '\s+')[0]
        if ($final -ne $capture.sha256) { throw 'Earlier source changed before backup-set completion.' }
    }
    Check-State
    $record.complete = $true
} catch {
    $record.error = $_.Exception.Message
    throw
} finally {
    $record.finished_utc = [DateTime]::UtcNow.ToString('o')
    $record.tool_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Save-Record
}
