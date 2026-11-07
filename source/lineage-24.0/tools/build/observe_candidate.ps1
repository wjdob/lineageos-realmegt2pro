<#
.SYNOPSIS
Record bounded hourly collector, Windows-waiter and Linux-unit observations.
.DESCRIPTION
Launch metadata identifies the exact run and distribution. A missing waiter or
transient unit alone does not establish build completion. Native collector state
does not certify package gates or device acceptance. No build restart or cleanup.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^candidate-[a-z0-9-]+$')][string]$Run,
    [ValidateRange(1,24)][int]$Hours=13
)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Split-Path (Split-Path $PSScriptRoot -Parent) -Parent))
$runPath=Join-Path $repo ('.local\goals\runs\'+$Run)
$launch=Get-Content -LiteralPath (Join-Path $repo ('.local\goals\launches\'+$Run+'\launch.json')) -Raw | ConvertFrom-Json
$unit='realme-next-'+$Run+'.service'
$launchArgs=@($launch.arguments)
if($launch.run -cne $Run -or $launch.unit -cne $unit -or $launchArgs.Count -lt 4 -or
    $launchArgs[0] -cne '-d' -or $launchArgs[1] -notmatch '^[a-zA-Z0-9_-]+$' -or
    $launchArgs[2] -cne '--exec' -or $launchArgs -cnotcontains ('--unit=realme-next-'+$Run)){
    throw 'Launch receipt does not identify this exact run and distribution.'
}
$distribution=$launchArgs[1]
$drive=$repo.Substring(0,1)
$out=Join-Path $repo ('.local\goals\observations\'+$Run)
if(Test-Path -LiteralPath $out){throw 'Use one observer per run; previous observations are preserved.'}
[IO.Directory]::CreateDirectory($out)|Out-Null
[IO.File]::WriteAllText((Join-Path $out 'schedule.json'),(@{started_utc=[DateTime]::UtcNow.ToString('o');run=$Run;interval_seconds=3600;maximum_observations=$Hours;limits='Local hourly evidence only; no chat notification, restart, retry or device operation.'}|ConvertTo-Json))
for($sample=1;$sample -le $Hours;$sample++){
    Start-Sleep -Seconds 3600
    $record=@{observed_utc=[DateTime]::UtcNow.ToString('o');sample=$sample;run=$Run;windows_free_bytes=(Get-PSDrive -Name $drive).Free;state='no-collector-result';
        state_scope='Native collector only; unit/waiter and package acceptance are separate.'}
    $result=$null
    $terminal=$false
    $matching=$false
    $unitStopped=$false
    $unitMissing=$false
    try{
        $resultPath=Join-Path $runPath 'result.json'
        if(Test-Path -LiteralPath $resultPath){$result=Get-Content -LiteralPath $resultPath -Raw|ConvertFrom-Json}
        $record.state=if($result){$result.state}else{'no-collector-result'}
        if($result){$record.exit_code=$result.exit_code;$record.finished_ns=$result.finished_ns}
        $terminal=$result -and $result.state -in @('success','failed') -and
            ($result.finished_ns -is [long] -or $result.finished_ns -is [int]) -and $result.finished_ns -gt 0
    }catch{$record.collector_error=$_.Exception.Message}
    $record.collector_terminal=[bool]$terminal
    try{
        $waiter=Get-CimInstance Win32_Process -Filter ('ProcessId = '+[uint32]$launch.windows_pid)
        $token='--unit=realme-next-'+$Run
        $matching=$waiter -and $waiter.Name -eq 'wsl.exe' -and
            $waiter.CommandLine -match ('(?<!\S)'+[regex]::Escape($token)+'(?=\s|$)')
    }catch{$record.waiter_error=$_.Exception.Message}
    $record.matching_windows_waiter=[bool]$matching
    try{
        $log=Join-Path $runPath 'build.log'
        if(Test-Path -LiteralPath $log){$record.build_tail=(Get-Content -LiteralPath $log -Tail 12)-join "`n"}
        # The Windows waiter can disappear independently of the Linux build unit.
        $lines=@(& wsl.exe -d $distribution --exec systemctl show $unit --property=LoadState,ActiveState,SubState,Result,ExecMainStatus)
        $record.unit_query_exit_code=$LASTEXITCODE
        $record.unit_status=$lines-join "`n"
        $properties=@{}
        foreach($line in $lines){
            $pair=$line-split '=',2
            if($pair.Count -eq 2){$properties[$pair[0]]=$pair[1]}
        }
        $unitStopped=$record.unit_query_exit_code -eq 0 -and $properties.LoadState -eq 'loaded' -and
            $properties.ActiveState -in @('inactive','failed')
        $unitMissing=$properties.LoadState -eq 'not-found'
    }catch{$record.unit_error=$_.Exception.Message}
    if($unitStopped){$record.stop_reason='unit-terminal'}
    elseif($terminal -and $unitMissing -and -not $matching){$record.stop_reason='collector-terminal-unit-gone'}
    elseif($sample -eq $Hours){$record.stop_reason='observation-limit; build outcome unresolved'}
    [IO.File]::WriteAllText((Join-Path $out ('hour-'+$sample+'.json')),($record|ConvertTo-Json -Depth 8))
    if($unitStopped -or ($terminal -and $unitMissing -and -not $matching)){break}
}
