param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [string]$KeyDirectory,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Security
Add-Type -AssemblyName System.IO.Compression
$repoRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$privateRoot = [IO.Path]::Combine($repoRoot, '.local') + [IO.Path]::DirectorySeparatorChar
$outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
if (-not $outputRoot.StartsWith($privateRoot, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Backup output must be under repository .local; private files are never committed.'
}
function Hash-Bytes([byte[]]$Data) {
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($Data))).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose() }
}
$bundlePath = [IO.Path]::Combine($outputRoot, 'signing-keys.dpapi')
$manifestPath = [IO.Path]::Combine($outputRoot, 'manifest.json')
if (-not $VerifyOnly) {
    if (-not $KeyDirectory -or (Test-Path -LiteralPath $outputRoot)) {
        throw 'Provide the private source directory and a NEW backup directory.'
    }
    $names = 'releasekey','platform','shared','media','networkstack','sdk_sandbox','bluetooth','nfc'
    $pinnedCertificate = [IO.File]::ReadAllBytes([IO.Path]::Combine($repoRoot, 'certs/rmx3301-releasekey.x509.pem'))
    $sourceCertificate = [IO.File]::ReadAllBytes([IO.Path]::Combine($KeyDirectory, 'releasekey.x509.pem'))
    if ((Hash-Bytes $pinnedCertificate) -ne (Hash-Bytes $sourceCertificate)) { throw 'Release certificate differs from pinned identity.' }
    $memory = New-Object IO.MemoryStream
    $rows = @()
    $zip = New-Object IO.Compression.ZipArchive($memory, [IO.Compression.ZipArchiveMode]::Create, $true)
    try {
        foreach ($name in $names) {
            foreach ($extension in '.pk8','.x509.pem') {
                $filename = $name + $extension
                $data = [IO.File]::ReadAllBytes([IO.Path]::Combine($KeyDirectory, $filename))
                try {
                    if ($data.Length -eq 0 -or $data.Length -gt 32768) { throw 'Unexpected signing file size.' }
                    $rows += @{ name=$filename; bytes=$data.Length; sha256=(Hash-Bytes $data) }
                    $entry = $zip.CreateEntry($filename)
                    $stream = $entry.Open()
                    try { $stream.Write($data, 0, $data.Length) } finally { $stream.Dispose() }
                } finally { [Array]::Clear($data, 0, $data.Length) }
            }
        }
    } finally { $zip.Dispose() }
    $plain = $memory.ToArray()
    try {
        $encrypted = [Security.Cryptography.ProtectedData]::Protect($plain, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
        $manifest = @{ schema=1; protection='Windows DPAPI CurrentUser'; account=$identity.Name;
            sid=$identity.User.Value; created_utc=[DateTime]::UtcNow.ToString('o'); files=$rows;
            encrypted_sha256=(Hash-Bytes $encrypted); plaintext_zip_sha256=(Hash-Bytes $plain);
            limits='Independent of WSL container, same physical drive. Recovery requires this Windows user profile/DPAPI keys.' }
        [IO.Directory]::CreateDirectory($outputRoot) | Out-Null
        [IO.File]::WriteAllBytes($bundlePath, $encrypted)
        [IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json -Depth 5))
    } finally {
        [Array]::Clear($plain, 0, $plain.Length)
        [Array]::Clear($memory.GetBuffer(), 0, $memory.GetBuffer().Length)
        $memory.Dispose()
    }
}
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if ($manifest.sid -ne $currentSid -or $manifest.schema -ne 1) { throw 'Backup schema or Windows identity mismatch.' }
$encrypted = [IO.File]::ReadAllBytes($bundlePath)
if ((Hash-Bytes $encrypted) -ne $manifest.encrypted_sha256) { throw 'Encrypted backup hash mismatch.' }
$plain = [Security.Cryptography.ProtectedData]::Unprotect($encrypted, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)
$memory = New-Object IO.MemoryStream(,$plain)
try {
    if ((Hash-Bytes $plain) -ne $manifest.plaintext_zip_sha256) { throw 'Decrypted backup hash mismatch.' }
    $zip = New-Object IO.Compression.ZipArchive($memory, [IO.Compression.ZipArchiveMode]::Read, $true)
    try {
        if ($zip.Entries.Count -ne 16 -or $manifest.files.Count -ne 16) { throw 'Incomplete signing backup.' }
        $seen = @{}
        foreach ($entry in $zip.Entries) {
            if ($seen.ContainsKey($entry.FullName)) { throw 'Duplicate signing backup entry.' }
            $seen[$entry.FullName] = $true
            $expected = @($manifest.files | Where-Object { $_.name -eq $entry.FullName })
            if ($expected.Count -ne 1 -or $entry.Length -ne $expected[0].bytes -or $entry.Length -gt 32768) { throw 'Unexpected signing backup entry.' }
            $entryStream = $entry.Open()
            $copy = New-Object IO.MemoryStream
            try {
                $entryStream.CopyTo($copy)
                $data = $copy.ToArray()
                try { if ((Hash-Bytes $data) -ne $expected[0].sha256) { throw 'Signing backup content mismatch.' } }
                finally { [Array]::Clear($data, 0, $data.Length) }
            } finally { $entryStream.Dispose(); [Array]::Clear($copy.GetBuffer(),0,$copy.GetBuffer().Length); $copy.Dispose() }
        }
    } finally { $zip.Dispose() }
} finally { [Array]::Clear($plain,0,$plain.Length); $memory.Dispose() }
@{ verified=$true; files=16; encrypted_bundle=$bundlePath; account=$manifest.account;
    encrypted_sha256=$manifest.encrypted_sha256; limits=$manifest.limits } | ConvertTo-Json
