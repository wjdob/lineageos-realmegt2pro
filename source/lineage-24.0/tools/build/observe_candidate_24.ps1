[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^candidate-[a-z0-9-]+$')][string]$Run,
    [ValidateRange(1,24)][int]$Hours=13
)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'observation_schedule_24.ps1')
$repo=[IO.Path]::GetFullPath((Split-Path (Split-Path $PSScriptRoot -Parent) -Parent))
$launchDir=Join-Path $repo ('.local\goals\launches\'+$Run)
$launch=Get-Content -LiteralPath (Join-Path $launchDir 'launch.json') -Raw | ConvertFrom-Json
$argsList=@($launch.arguments)
$token='--unit=realme-next-'+$Run
if($launch.run -cne $Run -or $launch.store -cne '/mnt/lineage24-store' -or $launch.host_drive -cne 'C' -or
   $argsList[0] -cne '-d' -or $argsList[1] -notmatch '^[a-zA-Z0-9_-]+$' -or
   $argsList -cnotcontains $token){throw 'Mismatched 24.0 launch identity.'}
$out=Join-Path $repo ('.local\goals\observations\'+$Run)
if(Test-Path -LiteralPath $out){throw 'An observer already owns this run.'}
[IO.Directory]::CreateDirectory($out)|Out-Null
$linuxRepo='/mnt/'+$repo.Substring(0,1).ToLowerInvariant()+'/'+$repo.Substring(3).Replace('\','/')
[IO.File]::WriteAllText((Join-Path $out 'schedule.json'),(@{
    run=$Run;early_interval_seconds=300;early_window_seconds=3600;
    running_interval_seconds=1800;maximum_hours=$Hours;
    limits='Read-only evidence; no build restart, retry, completion promotion or device command.'
}|ConvertTo-Json))
$started=[DateTime]::UtcNow
$deadline=$started.AddHours($Hours)
$sample=0
while([DateTime]::UtcNow -lt $deadline){
    $interval=Get-Candidate24ObservationInterval -ElapsedSeconds ([DateTime]::UtcNow-$started).TotalSeconds
    $remaining=[math]::Ceiling(($deadline-[DateTime]::UtcNow).TotalSeconds)
    if($remaining -le 0){break}
    Start-Sleep -Seconds ([math]::Min($interval,$remaining))
    $sample++
    $record=@{run=$Run;sample=$sample;observed_utc=[DateTime]::UtcNow.ToString('o');
        host_drive=$launch.host_drive;host_free_bytes=(Get-PSDrive -Name $launch.host_drive).Free}
    $matching=$false
    try{
        $waiter=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[uint32]$launch.windows_pid)
        $matching=$waiter -and $waiter.Name -eq 'wsl.exe' -and
            $waiter.CommandLine -match ('(?<!\S)'+[regex]::Escape($token)+'(?=\s|$)')
        $record.matching_windows_waiter=[bool]$matching
    }catch{$record.waiter_error=$_.Exception.Message}
    $outcome='inconclusive'
    try{
        $lines=@(& wsl.exe -d $argsList[1] --exec /usr/bin/python3 ($linuxRepo+'/tools/build/observe_candidate_24.py') --run $Run)
        $record.probe_exit_code=$LASTEXITCODE
        if($LASTEXITCODE -ne 0){throw 'Could not read the exact SSD collector/unit.'}
        $probe=($lines -join "`n")|ConvertFrom-Json
        $record.probe=$probe
        $outcome=Get-Candidate24ObservationOutcome -Probe $probe -MatchingWaiter ([bool]$matching)
    }catch{$record.probe_error=$_.Exception.Message}
    $terminal=$outcome -in @('success','failed','failed-after-collector','terminal-without-complete-result')
    $record.outcome=$outcome
    $record.interval_seconds=$interval
    $record.launch_terminal=[bool]$terminal
    [IO.File]::WriteAllText((Join-Path $out ('sample-'+$sample.ToString('000')+'.json')),($record|ConvertTo-Json -Depth 12))
    if($terminal){break}
}
