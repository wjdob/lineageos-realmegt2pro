param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [string]$AdbPath,
    [string]$Serial,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
$repoRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$privateRoot = [IO.Path]::Combine($repoRoot, '.local') + [IO.Path]::DirectorySeparatorChar
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
if (-not $outputRoot.StartsWith($privateRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Backup output must be under repository .local.'
}
$bundlePath = [IO.Path]::Combine($outputRoot, 'frp-pairing.dpapi')
$manifestPath = [IO.Path]::Combine($outputRoot, 'manifest.json')
$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$currentSid = $currentIdentity.User.Value

function Hash-Bytes([byte[]]$Data) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($Data))).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose() }
}
function Same-Bytes([byte[]]$Left, [byte[]]$Right) {
    if ($Left.Length -ne $Right.Length) { return $false }
    $difference = 0
    for ($index = 0; $index -lt $Left.Length; $index++) {
        $difference = $difference -bor ($Left[$index] -bxor $Right[$index])
    }
    return $difference -eq 0
}
function Get-Entropy($Metadata) {
    return ,([Text.Encoding]::UTF8.GetBytes('realmegt2pro-next:frp-pairing:v1|' +
        $Metadata.sid + '|' + $Metadata.serial + '|' + $Metadata.nonce))
}
function Read-AdbBytes([string]$Arguments) {
    # All callers below supply fixed read-only commands. No shell is launched on Windows.
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $AdbPath
    $start.Arguments = '-s ' + $Serial + ' ' + $Arguments
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $start
    $memory = New-Object IO.MemoryStream
    try {
        if (-not $process.Start()) { throw 'ADB process did not start.' }
        $copy = $process.StandardOutput.BaseStream.CopyToAsync($memory)
        $errors = $process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(30000)) {
            $process.Kill()
            $process.WaitForExit()
            throw 'Read-only ADB command timed out; no backup promoted.'
        }
        [void]$copy.GetAwaiter().GetResult()
        $stderr = $errors.GetAwaiter().GetResult()
        if ($process.ExitCode -ne 0) { throw ('Read-only ADB command failed: ' + $stderr.Trim()) }
        if ($memory.Length -gt 65536) { throw 'Unexpected read-only response size.' }
        return ,($memory.ToArray())
    } finally {
        if ($memory.Capacity) { [Array]::Clear($memory.GetBuffer(), 0, $memory.GetBuffer().Length) }
        $memory.Dispose()
        $process.Dispose()
    }
}
function Read-AdbText([string]$Command) {
    $data = Read-AdbBytes ('shell ' + $Command)
    try { return [Text.Encoding]::UTF8.GetString($data).Trim() }
    finally { [Array]::Clear($data, 0, $data.Length) }
}

if (-not $VerifyOnly) {
    if (-not $AdbPath -or -not (Test-Path -LiteralPath $AdbPath -PathType Leaf) -or
        $Serial -notmatch '^[A-Za-z0-9]+$' -or (Test-Path -LiteralPath $outputRoot)) {
        throw 'Provide an existing ADB executable, exact serial and NEW private backup directory.'
    }
    $AdbPath = [IO.Path]::GetFullPath($AdbPath)
    if ((Read-AdbText 'id') -notmatch 'uid=0\(root\)') { throw 'Authorized root ADB is required.' }
    if ((Read-AdbText 'getprop ro.product.model') -ne 'RMX3301') { throw 'Wrong device model.' }
    $blockSize = Read-AdbText 'blockdev --getsize64 /dev/block/by-name/frp'
    if ($blockSize -ne '524288') { throw 'Unreviewed FRP layout; no key read attempted.' }
    # dumpsys uses printSecrets=false in the reviewed Android service; do not use cmd status.
    $status = Read-AdbText 'dumpsys persistent_data_block'
    if ($status -notmatch '(?m)^FRP state: false\r?$' -or
        $status -notmatch '(?m)^Enforcement enabled: true\r?$') {
        throw 'FRP pairing must already be authenticated and inactive.'
    }
    $metadata = Read-AdbText 'stat -c %s:%u:%g:%a /data/system/frp_secret'
    $label = Read-AdbText 'ls -lZ /data/system/frp_secret'
    if ($metadata -ne '32:1000:1000:600' -or $label -notmatch 'u:object_r:system_data_file:s0') {
        throw 'Unexpected pairing-file metadata or SELinux label.'
    }
    $blockHash = ((Read-AdbText 'sha256sum /dev/block/by-name/frp') -split '\s+')[0]
    $secret = $null; $again = $null; $blockSecret = $null; $region = $null; $roundTrip = $null
    try {
        $secret = Read-AdbBytes 'exec-out cat /data/system/frp_secret'
        # Validate the public 8-byte magic and read its 32-byte secret; no of=.
        # exec-out merges stderr into stdout, so suppress dd's transfer statistics.
        $region = Read-AdbBytes 'exec-out dd if=/dev/block/by-name/frp bs=1 skip=513247 count=40 status=none'
        $magic = [byte[]]@(0xda,0xc2,0xfc,0xcd,0xb9,0x1b,0x09,0x88)
        if ($region.Length -ne 40 -or -not (Same-Bytes ([byte[]]$region[0..7]) $magic)) {
            throw 'Reviewed protected-secret layout was not recognized.'
        }
        $blockSecret = New-Object byte[] 32
        [Array]::Copy($region, 8, $blockSecret, 0, 32)
        $again = Read-AdbBytes 'exec-out cat /data/system/frp_secret'
        if ($secret.Length -ne 32 -or -not (Same-Bytes $secret $again) -or
            -not (Same-Bytes $secret $blockSecret)) {
            throw 'Pairing bytes changed or do not match the current protected secret.'
        }
        $afterHash = ((Read-AdbText 'sha256sum /dev/block/by-name/frp') -split '\s+')[0]
        if ($blockHash -ne $afterHash) { throw 'Protected block changed during read-only backup.' }
        $manifest = [ordered]@{
            schema=1; purpose='authenticated-ordinary-FRP-pairing-file-backup';
            protection='Windows DPAPI CurrentUser'; sid=$currentSid; account=$currentIdentity.Name;
            serial=$Serial; model='RMX3301'; created_utc=[DateTime]::UtcNow.ToString('o');
            nonce=[Guid]::NewGuid().ToString('N'); source='/data/system/frp_secret';
            source_bytes=32; source_metadata=$metadata; source_label='u:object_r:system_data_file:s0';
            paired_with_current_protected_secret=$true; protected_block_sha256=$blockHash;
            limits='Same Windows profile is required; this shares the physical host drive. No automatic restore or protected-block write is provided. It is not a PIN, FBE-key or complete user-data backup.'
        }
        $entropy = Get-Entropy $manifest
        $encrypted = [Security.Cryptography.ProtectedData]::Protect($secret, $entropy, [Security.Cryptography.DataProtectionScope]::CurrentUser)
        $roundTrip = [Security.Cryptography.ProtectedData]::Unprotect($encrypted, $entropy, [Security.Cryptography.DataProtectionScope]::CurrentUser)
        if (-not (Same-Bytes $secret $roundTrip)) { throw 'DPAPI round-trip comparison failed.' }
        $manifest.encrypted_sha256 = Hash-Bytes $encrypted
        [void][IO.Directory]::CreateDirectory($outputRoot)
        [IO.File]::WriteAllBytes($bundlePath, $encrypted)
        [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding($false)))
    } finally {
        foreach ($buffer in @($secret, $again, $blockSecret, $region, $roundTrip)) {
            if ($null -ne $buffer) { [Array]::Clear($buffer, 0, $buffer.Length) }
        }
    }
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.schema -ne 1 -or $manifest.sid -ne $currentSid -or $manifest.source_bytes -ne 32 -or
    $manifest.source -ne '/data/system/frp_secret' -or -not $manifest.paired_with_current_protected_secret) {
    throw 'Backup identity/schema mismatch.'
}
$encrypted = [IO.File]::ReadAllBytes($bundlePath)
if ((Hash-Bytes $encrypted) -ne $manifest.encrypted_sha256) { throw 'Encrypted backup hash mismatch.' }
$plain = [Security.Cryptography.ProtectedData]::Unprotect($encrypted, (Get-Entropy $manifest), [Security.Cryptography.DataProtectionScope]::CurrentUser)
try {
    if ($plain.Length -ne 32) { throw 'Decrypted pairing length mismatch.' }
} finally { [Array]::Clear($plain, 0, $plain.Length) }
@{verified=$true; encrypted_bundle=$bundlePath; encrypted_sha256=$manifest.encrypted_sha256;
    source_bytes=32; account=$manifest.account; limits=$manifest.limits} | ConvertTo-Json
