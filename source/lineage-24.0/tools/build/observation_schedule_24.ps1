function Get-Candidate24ObservationInterval {
    param([double]$ElapsedSeconds)
    if($ElapsedSeconds -lt 0){throw 'Elapsed time cannot be negative.'}
    if($ElapsedSeconds -lt 3600){return 300}
    return 1800
}

function Get-Candidate24ObservationOutcome {
    param($Probe,[bool]$MatchingWaiter)
    if(-not $Probe){return 'inconclusive'}
    $unitTerminal=$Probe.unit.LoadState -eq 'not-found' -or $Probe.unit.ActiveState -in @('inactive','failed')
    if($MatchingWaiter -or -not $unitTerminal){return 'running'}
    if($Probe.collector -and $Probe.collector.state -in @('success','failed') -and $Probe.collector.finished_ns -gt 0){
        if($Probe.collector.state -eq 'success' -and ($Probe.unit.ActiveState -eq 'failed' -or $Probe.unit.Result -notin @($null,'','success'))){return 'failed-after-collector'}
        return [string]$Probe.collector.state
    }
    # Preparation can fail before execute() creates a collector. A killed job
    # can also leave an unfinished collector. Neither is a successful build.
    return 'terminal-without-complete-result'
}
