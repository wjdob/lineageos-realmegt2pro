[CmdletBinding(DefaultParameterSetName='Cached')]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^candidate-[a-z0-9-]+$')][string]$Run,
    [Parameter(Mandatory=$true,ParameterSetName='Cached')][ValidatePattern('^candidate-[a-z0-9-]+$')][string]$BaseRun,
    [Parameter(Mandatory=$true,ParameterSetName='Fresh')][switch]$Fresh,
    [ValidateSet('nothing','recoveryimage','dtboimage','otapackage','check-elf-files')][string]$Target='otapackage',
    [ValidateRange(1,500)][int]$MaxUsedGiB=400,
    [ValidateRange(5,20)][int]$MinFreeGiB=20,
    [ValidateRange(1,32)][int]$Jobs=5,
    [ValidateRange(1,86400)][int]$TimeoutSeconds=43200,
    [string]$Distribution='realme-build',
    [Parameter(ParameterSetName='Cached')][switch]$AllowFailedCache
)
$ErrorActionPreference='Stop'
$workspace=[IO.Path]::GetFullPath((Split-Path (Split-Path $PSScriptRoot -Parent) -Parent))
if ($workspace -notmatch '^[A-Za-z]:\\' -or $workspace -match '\s' -or $Distribution -notmatch '^[a-zA-Z0-9_-]+$') {
    throw 'This launcher requires a local drive workspace without spaces and a simple distro name.'
}
$linuxRepo='/mnt/'+$workspace.Substring(0,1).ToLowerInvariant()+'/'+$workspace.Substring(3).Replace('\','/')
$records=Join-Path $workspace ('.local\goals\launches\'+$Run)
if ((Test-Path -LiteralPath $records) -or (Test-Path -LiteralPath (Join-Path $workspace ('.local\goals\runs\'+$Run)))) {
    throw 'Use a new run name; previous evidence is preserved.'
}
[IO.Directory]::CreateDirectory($records) | Out-Null
$arguments=@('-d',$Distribution,'--exec','systemd-run','--wait','--pipe',
    ('--unit=realme-next-'+$Run),'--property=Type=exec','--property=Restart=no','--property=KillMode=control-group',
    '--property=MemoryHigh=16G','--property=MemoryMax=20G',
    '/usr/bin/unshare','--mount','--propagation','private','/usr/bin/python3',
    ($linuxRepo+'/tools/build/isolated_job.py'),'--run-dir',('/build/realmegt2pro-next-work/'+$Run))
if (-not $Fresh) { $arguments+=@('--base-run',('/build/realmegt2pro-next-work/'+$BaseRun)) }
if ($AllowFailedCache) { $arguments+='--allow-failed-cache' }
$arguments+=@('--','/usr/bin/python3',($linuxRepo+'/tools/build/run_candidate.py'),
    '--target',$Target,'--run',$Run,'--jobs',[string]$Jobs,'--max-used-gib',[string]$MaxUsedGiB,
    '--min-free-gib',[string]$MinFreeGiB,
    '--timeout',[string]$TimeoutSeconds,
    '--signing-dir','/root/.local/share/realmegt2pro-next/signing/rmx3301-mvp')
Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $records 'start_candidate.ps1')
# --wait holds a non-service WSL client open. --pipe forwards output into these host logs.
# Do not use RemainAfterExit with --wait: the waiter must finish when the task does.
$launchOptions=@{FilePath='wsl.exe';ArgumentList=$arguments;WindowStyle='Hidden';
    RedirectStandardOutput=(Join-Path $records 'stdout.log');
    RedirectStandardError=(Join-Path $records 'stderr.log');PassThru=$true}
$process=Start-Process @launchOptions
$receipt=@{run=$Run;base_run=$BaseRun;target=$Target;unit=('realme-next-'+$Run+'.service');
    fresh=[bool]$Fresh;windows_min_free_gib=$MinFreeGiB;
    memory_high_gib=16;memory_max_gib=20;
    timeout_seconds=$TimeoutSeconds;
    windows_pid=$process.Id;started_utc=[DateTime]::UtcNow.ToString('o');arguments=$arguments;
    linux_max_used_gib=$MaxUsedGiB;windows_free_bytes=(Get-PSDrive -Name ($workspace.Substring(0,1))).Free;
    launcher_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant();
    limits='Windows waiter keeps WSL alive independently of Codex. WSL shutdown or host shutdown still stops the build. Completion is proved by the run result, not by this receipt.'}
[IO.File]::WriteAllText((Join-Path $records 'launch.json'),($receipt | ConvertTo-Json -Depth 5))
$receipt | ConvertTo-Json -Depth 5
