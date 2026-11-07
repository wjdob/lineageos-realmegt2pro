param([switch]$VerifyPreservedSource)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$failures = New-Object 'System.Collections.Generic.List[string]'
$scripts = @(Get-ChildItem -LiteralPath (Join-Path $root 'tools') -Filter '*.ps1' -Recurse)
foreach ($file in $scripts) {
    $tokens = $null
    $parseErrors = $null
    [void][Management.Automation.Language.Parser]::ParseFile($file.FullName, [ref]$tokens, [ref]$parseErrors)
    foreach ($problem in $parseErrors) { $failures.Add("$($file.Name): $problem") }
}
$documents = @(
    Get-Item -LiteralPath (Join-Path $root 'README.md'), (Join-Path $root 'AGENTS.md')
    Get-ChildItem -LiteralPath (Join-Path $root 'docs') -Filter '*.md' -File
    Get-Item -LiteralPath (Join-Path $root 'patches\README.md')
)
foreach ($document in $documents) {
    $content = Get-Content -LiteralPath $document.FullName -Raw
    foreach ($match in [regex]::Matches($content, '\[[^\]]+\]\(([^)]+)\)')) {
        $link = $match.Groups[1].Value
        if ($link -match '^(https?://|#)') { continue }
        $target = ($link -split '#')[0]
        if (-not (Test-Path -LiteralPath (Join-Path $document.DirectoryName $target))) {
            $failures.Add("Broken local link in $($document.Name): $link")
        }
    }
}
foreach ($relative in @('manifests\lineage-23.0-locked.xml', 'tools\lineage_local_manifest.xml')) {
    [xml]$xml = Get-Content -LiteralPath (Join-Path $root $relative) -Raw
    $projects = @($xml.manifest.project)
    if (-not $projects.Count) { $failures.Add("No projects: $relative") }
    $keys = @{}
    foreach ($project in $projects) {
        if ($project.revision -notmatch '^[0-9a-f]{40}$') {
            $failures.Add("Unpinned project in ${relative}: $($project.name)")
        }
        $key = "$($project.name)|$($project.path)"
        if ($keys.ContainsKey($key)) { $failures.Add("Duplicate project key in ${relative}: $key") }
        $keys[$key] = $true
    }
    Write-Output "$relative : $($projects.Count) project entries inspected"
}
if ($VerifyPreservedSource) {
    $inventory = Get-Content -LiteralPath (Join-Path $root '.local\migration\evidence\source-inventory.json') -Raw | ConvertFrom-Json
    foreach ($entry in $inventory.files) {
        $path = Join-Path $root ('.local\migration\source\' + $entry.path)
        if (-not (Test-Path -LiteralPath $path)) {
            $failures.Add("Missing preserved file: $($entry.path)")
        } elseif ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower() -ne $entry.sha256) {
            $failures.Add("Preserved file changed: $($entry.path)")
        }
    }
    Write-Output "Preserved source: $($inventory.files.Count) files checked"
}
$map = @(Import-Csv -LiteralPath (Join-Path $root 'docs\evidence\migration-map.csv'))
foreach ($entry in $map) {
    $activePath = Join-Path $root $entry.original_path
    if ($entry.disposition -eq 'history-and-local-snapshot') {
        if (Test-Path -LiteralPath $activePath -PathType Leaf) {
            $failures.Add("Migration map omits active file: $($entry.original_path)")
        }
    } elseif (-not (Test-Path -LiteralPath $activePath -PathType Leaf)) {
        $failures.Add("Mapped active file missing: $($entry.original_path)")
    } elseif ((Get-FileHash -LiteralPath $activePath -Algorithm SHA256).Hash.ToLower() -ne $entry.active_sha256) {
        $failures.Add("Active hash changed since migration map: $($entry.original_path)")
    }
}
Write-Output "Migration map: $($map.Count) dispositions checked"
if ($failures.Count) {
    $failures | ForEach-Object { Write-Output "FAIL: $_" }
    throw "$($failures.Count) workspace checks failed."
}
Write-Output "PASS: $($scripts.Count) PowerShell files, $($documents.Count) current documents, and manifest structure. No Python tests or device checks implied."
