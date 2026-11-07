[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^candidate-[a-z0-9-]+$')][string]$Run,
    [ValidateSet('nothing','check-elf-files','codec2-provider','init-diagnostic','otapackage')][string]$Target='otapackage',
    [ValidateRange(1,500)][int]$MaxUsedGiB=300,
    [ValidateRange(20,100)][int]$MinFreeGiB=40,
    [ValidateRange(1,32)][int]$Jobs=5,
    [ValidateRange(1,86400)][int]$TimeoutSeconds=43200,
    [ValidateRange(20,500)][int]$MinHostFreeGiB=40,
    [ValidateRange(4,64)][int]$MemoryHighGiB=16,
    [ValidateRange(4,64)][int]$MemoryMaxGiB=20,
    [switch]$PrepareOnly,
    [string]$Distribution='realme-build'
)
$ErrorActionPreference='Stop'
if($MemoryHighGiB -gt $MemoryMaxGiB){throw 'The soft memory limit cannot exceed the hard limit.'}
$workspace=[IO.Path]::GetFullPath((Split-Path (Split-Path $PSScriptRoot -Parent) -Parent))
if ($workspace -notmatch '^[A-Za-z]:\\' -or $workspace -match '\s' -or $Distribution -notmatch '^[a-zA-Z0-9_-]+$') {
    throw 'This launcher requires a local drive workspace without spaces and a simple distro name.'
}
$linuxRepo='/mnt/'+$workspace.Substring(0,1).ToLowerInvariant()+'/'+$workspace.Substring(3).Replace('\','/')
$records=Join-Path $workspace ('.local\goals\launches\'+$Run)
function Write-LaunchRecord($value) {
    $destination=Join-Path $records 'launch.json'
    $temporary=Join-Path $records 'launch.json.partial'
    [IO.File]::WriteAllText($temporary,($value|ConvertTo-Json -Depth 8))
    for($attempt=0;$attempt -lt 51;$attempt++){
        try{
            if([IO.File]::Exists($destination)){[IO.File]::Replace($temporary,$destination,(Join-Path $records 'launch.previous.json'))}
            else{[IO.File]::Move($temporary,$destination)}
            return
        }catch [IO.IOException]{
            if($attempt -eq 50){throw}
            Start-Sleep -Milliseconds 100
        }
    }
}
if ((Test-Path -LiteralPath $records) -or (Test-Path -LiteralPath (Join-Path $workspace ('.local\goals\runs\'+$Run)))) {
    throw 'Use a new run name; previous evidence is preserved.'
}
[IO.Directory]::CreateDirectory($records) | Out-Null
$tree='/build/lineage-24.0'
$store='/mnt/lineage24-store'
$lower=$store+'/tree'
$workRoot=$store+'/work'
$hostDrive='C'
$hostFree=(Get-PSDrive -Name $hostDrive).Free
if($hostFree -lt $MinHostFreeGiB*1GB){
    throw ('Host '+$hostDrive+': has '+[math]::Round($hostFree/1GB,2)+' GiB free; '+$MinHostFreeGiB+' GiB required before a 24.0 build.')
}
& wsl.exe -d $Distribution -e bash ($linuxRepo+'/tools/build/mount_24.sh') | Out-Null
if($LASTEXITCODE -ne 0){ throw 'Could not verify and mount the dedicated SSD 24.0 ext4 store.' }
$arguments=@('-d',$Distribution,'--exec','systemd-run','--wait','--pipe',
    ('--unit=realme-next-'+$Run),'--property=Type=exec','--property=Restart=no','--property=KillMode=control-group',
    '--setenv=WSL_INTEROP','--setenv=WSL_DISTRO_NAME',
    ('--property=MemoryHigh='+$MemoryHighGiB+'G'),('--property=MemoryMax='+$MemoryMaxGiB+'G'),
    '/bin/bash',($linuxRepo+'/tools/build/prepare_job_24.sh'),'/usr/bin/python3',
    ($linuxRepo+'/tools/build/isolated_job.py'),'--root',$tree,'--lower',$lower,
    '--work-root',$workRoot,'--records-root',($store+'/records'),
    '--run-dir',($workRoot+'/'+$Run),
    '--','/usr/bin/python3',($linuxRepo+'/tools/build/run_candidate_24.py'),
    '--target',$Target,'--run',$Run,'--jobs',[string]$Jobs,
    '--max-used-gib',[string]$MaxUsedGiB,'--min-free-gib',[string]$MinFreeGiB,
    '--timeout',[string]$TimeoutSeconds,'--tree',$tree,'--store',$store,
    '--signing-dir','/root/.local/share/realmegt2pro-next/signing/rmx3301-mvp')
if($PrepareOnly){$arguments+= '--prepare-only'}
Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $records 'start_candidate_24.ps1')
# --wait holds a non-service WSL client open. --pipe forwards output into these host logs.
$launchOptions=@{FilePath='wsl.exe';ArgumentList=$arguments;WindowStyle='Hidden';
    RedirectStandardOutput=(Join-Path $records 'stdout.log');
    RedirectStandardError=(Join-Path $records 'stderr.log');PassThru=$true}
$process=Start-Process @launchOptions
$receipt=@{run=$Run;target=$Target;unit=('realme-next-'+$Run+'.service');tree=$tree;
    store=$store;lower=$lower;host_drive=$hostDrive;
    fresh=$true;windows_min_free_gib=$MinFreeGiB;min_host_free_gib=$MinHostFreeGiB;memory_high_gib=$MemoryHighGiB;memory_max_gib=$MemoryMaxGiB;
    native_build_requested=(-not [bool]$PrepareOnly);
    timeout_seconds=$TimeoutSeconds;windows_pid=$process.Id;started_utc=[DateTime]::UtcNow.ToString('o');
    arguments=$arguments;linux_max_used_gib=$MaxUsedGiB;
    windows_free_bytes=$hostFree;
    launcher_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant();
    limits='Fresh 24.0 source tree only. The launcher does not sync, format, flash or touch the device; completion is proved by the run result, not this receipt.'}
Write-LaunchRecord $receipt
if(-not $PrepareOnly){
    $observer=Start-Process -FilePath (Get-Process -Id $PID).Path -WindowStyle Hidden -PassThru `
        -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'observe_candidate_24.ps1'),'-Run',$Run) `
        -RedirectStandardOutput (Join-Path $records 'observer.stdout.log') `
        -RedirectStandardError (Join-Path $records 'observer.stderr.log')
    $receipt.observer_windows_pid=$observer.Id
    $receipt.observer_schedule=@{early_interval_seconds=300;early_window_seconds=3600;running_interval_seconds=1800}
}
Write-LaunchRecord $receipt
$receipt | ConvertTo-Json -Depth 5
