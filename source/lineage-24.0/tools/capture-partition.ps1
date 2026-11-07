param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9]+$')][string]$Serial,
    [Parameter(Mandatory=$true)][ValidateSet('recovery_a','recovery_b','boot_b','vendor_boot_b','vbmeta_b','misc')][string]$Partition,
    [string]$Adb = 'C:\Users\wdob\platform-tools\adb.exe'
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$dir = Join-Path $root '.local\goals\device\captures'
New-Item -ItemType Directory -Path $dir -Force | Out-Null
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$file = Join-Path $dir ($Partition + '-' + $stamp + '.img')
$node = '/dev/block/by-name/' + $Partition
$before = & $Adb -s $Serial shell "su -c 'sha256sum $node'"
if ($LASTEXITCODE -ne 0 -or $before -notmatch '^([a-f0-9]{64})\s') { throw 'Cannot hash partition before capture' }
$expected = $Matches[1]
$size = & $Adb -s $Serial shell "su -c 'blockdev --getsize64 $node'"
if ($LASTEXITCODE -ne 0 -or $size.Trim() -notmatch '^\d+$') { throw 'Cannot determine partition size' }
$info = New-Object Diagnostics.ProcessStartInfo
$info.FileName = $Adb
$info.Arguments = '-s {0} exec-out "su -c ''cat /dev/block/by-name/{1}''"' -f $Serial,$Partition
$info.UseShellExecute = $false
$info.CreateNoWindow = $true
$info.RedirectStandardOutput = $true
$info.RedirectStandardError = $true
$process = New-Object Diagnostics.Process
$process.StartInfo = $info
[void]$process.Start()
$errorTask = $process.StandardError.ReadToEndAsync()
$stream = [IO.File]::Open($file,[IO.FileMode]::CreateNew)
try { $process.StandardOutput.BaseStream.CopyTo($stream) } finally { $stream.Dispose() }
$process.WaitForExit()
$stderr = $errorTask.Result
if ($process.ExitCode -ne 0) { throw "Capture failed; incomplete file retained: $stderr" }
$actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLower()
$after = & $Adb -s $Serial shell "su -c 'sha256sum $node'"
if ($LASTEXITCODE -ne 0 -or $after -notmatch '^([a-f0-9]{64})\s') { throw 'Cannot hash partition after capture' }
if ($Matches[1] -ne $expected -or $actual -ne $expected -or (Get-Item $file).Length -ne [long]$size.Trim()) {
    throw "Capture not stable/identical; file retained for investigation: $file"
}
[pscustomobject]@{serial=$Serial;partition=$Partition;capturedUtc=$stamp;sha256=$actual;bytes=[long]$size.Trim();file=$file;method='adb exec-out raw stream; on-device hashes before and after; no device-side temporary file'} |
    ConvertTo-Json | Set-Content -LiteralPath ($file + '.json') -Encoding UTF8
Write-Output "VERIFIED $Partition $actual $file"
