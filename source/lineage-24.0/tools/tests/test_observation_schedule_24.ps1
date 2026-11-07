$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot '../build/observation_schedule_24.ps1')
$cases=0
function Assert-Outcome($expected,$actual){
    if($actual -cne $expected){throw ('Expected '+$expected+', got '+$actual)}
    $script:cases++
}
Assert-Outcome 300 (Get-Candidate24ObservationInterval 0)
Assert-Outcome 300 (Get-Candidate24ObservationInterval 3599.9)
Assert-Outcome 1800 (Get-Candidate24ObservationInterval 3600)
Assert-Outcome 1800 (Get-Candidate24ObservationInterval 43200)
$rejected=$false
try{Get-Candidate24ObservationInterval -1|Out-Null}catch{$rejected=$true}
Assert-Outcome $true $rejected
$inactive=@{LoadState='loaded';ActiveState='inactive'}
$active=@{LoadState='loaded';ActiveState='active'}
$success=@{state='success';finished_ns=1}
Assert-Outcome 'success' (Get-Candidate24ObservationOutcome @{collector=$success;unit=$inactive} $false)
Assert-Outcome 'running' (Get-Candidate24ObservationOutcome @{collector=$success;unit=$inactive} $true)
Assert-Outcome 'running' (Get-Candidate24ObservationOutcome @{collector=$success;unit=$active} $false)
Assert-Outcome 'failed' (Get-Candidate24ObservationOutcome @{collector=@{state='failed';finished_ns=1};unit=$inactive} $false)
Assert-Outcome 'failed-after-collector' (Get-Candidate24ObservationOutcome @{collector=$success;unit=@{LoadState='loaded';ActiveState='failed';Result='exit-code'}} $false)
Assert-Outcome 'terminal-without-complete-result' (Get-Candidate24ObservationOutcome @{collector=$null;unit=$inactive} $false)
Assert-Outcome 'terminal-without-complete-result' (Get-Candidate24ObservationOutcome @{collector=@{state='running'};unit=$inactive} $false)
Assert-Outcome 'inconclusive' (Get-Candidate24ObservationOutcome $null $false)
Write-Output "PASS: $cases observer schedule and terminal-state cases. No build or sleep invoked."
