param(
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [Parameter(Mandatory = $true)][string]$OutputName,
    [long]$HashLimitBytes = 268435456
)
$ErrorActionPreference = 'Stop'
if ($OutputName -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]*$') { throw 'Use a simple output name.' }
if ($HashLimitBytes -lt 0) { throw 'Hash limit cannot be negative.' }
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$root = (Resolve-Path -LiteralPath $SourceRoot).Path.TrimEnd('\')
if (-not (Get-Item -LiteralPath $root).PSIsContainer) { throw 'Source must be a directory.' }
if ((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint) {
    throw 'Source root cannot be a reparse point.'
}
$outputDirectory = Join-Path $workspace '.local\migration\evidence'
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$queue = New-Object 'System.Collections.Generic.Queue[string]'
$queue.Enqueue($root)
$rows = New-Object 'System.Collections.Generic.List[object]'
while ($queue.Count) {
    foreach ($item in (Get-ChildItem -LiteralPath $queue.Dequeue() -Force -ErrorAction Stop)) {
        $relative = $item.FullName.Substring($root.Length + 1).Replace('\','/')
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            $rows.Add([pscustomobject]@{path=$relative; status='reparse-point-not-followed'})
        } elseif ($item.PSIsContainer) {
            $queue.Enqueue($item.FullName)
        } else {
            $digest = $null
            $status = 'metadata-only'
            $length = $item.Length
            $modified = $item.LastWriteTimeUtc
            if ($length -le $HashLimitBytes) {
                $digest = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLower()
                $after = Get-Item -LiteralPath $item.FullName
                if ($after.Length -ne $length -or $after.LastWriteTimeUtc -ne $modified) {
                    throw "File changed during inventory: $relative"
                }
                $status = 'sha256-observed-now'
            }
            $rows.Add([pscustomobject]@{path=$relative;bytes=$length;modifiedUtc=$modified.ToString('o');sha256=$digest;status=$status})
        }
    }
}
$result = [pscustomobject]@{
    root=$root;observedUtc=[DateTime]::UtcNow.ToString('o');hashLimitBytes=$HashLimitBytes
    meaning='Inventory only; not original capture integrity or device validation.'
    entries=@($rows.ToArray() | Sort-Object path)
}
$destination = Join-Path $outputDirectory ($OutputName + '.json')
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $destination -Encoding UTF8
Write-Output "Inventoried $($rows.Count) entries: $destination"
