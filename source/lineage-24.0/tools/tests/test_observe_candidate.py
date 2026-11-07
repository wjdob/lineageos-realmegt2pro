"""Exercise the real PowerShell observer with local files and mocked host queries."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SHELL = shutil.which('pwsh') or shutil.which('powershell.exe') or shutil.which('powershell')


@unittest.skipUnless(SHELL, 'PowerShell unavailable; observer behavior check blocked')
class CandidateObserverTests(unittest.TestCase):
    def observe(self, *, unit='active', result=None, waiter=False, wrong_token=False,
                waiter_error=False, receipt_run=None, result_text=None):
        scratch = ROOT/'tmp/observer-tests'
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as name:
            root = Path(name)
            script = root/'tools/build/observe_candidate.ps1'
            script.parent.mkdir(parents=True)
            shutil.copyfile(ROOT/'tools/build/observe_candidate.ps1', script)
            run = 'candidate-observer-fixture'
            launch = root/'.local/goals/launches'/run
            launch.mkdir(parents=True)
            (launch/'launch.json').write_text(json.dumps({
                'run': receipt_run or run, 'unit': 'realme-next-'+run+'.service',
                'windows_pid': 1234,
                'arguments': ['-d', 'fixture-distro', '--exec', 'systemd-run',
                              '--unit=realme-next-'+run],
            }))
            if result is not None or result_text is not None:
                records = root/'.local/goals/runs'/run
                records.mkdir(parents=True)
                (records/'result.json').write_text(result_text if result_text is not None else json.dumps(result))
            configuration = dict(unit=unit, waiter=waiter, wrong_token=wrong_token,
                                 waiter_error=waiter_error)
            (root/'case.json').write_text(json.dumps(configuration))
            harness = root/'harness.ps1'
            harness.write_text(r'''
$ErrorActionPreference='Stop'
$global:observerTestCase=Get-Content (Join-Path $PSScriptRoot 'case.json') -Raw|ConvertFrom-Json
$global:observerTestQueries=0
function Start-Sleep {param($Seconds) if($Seconds -ne 3600){throw 'Wrong interval'}}
function Get-PSDrive {param($Name) [pscustomobject]@{Free=123456}}
function Get-CimInstance {
    param($ClassName,$Filter)
    if($global:observerTestCase.waiter_error){throw 'CIM unavailable'}
    if($global:observerTestCase.waiter){
        $suffix=if($global:observerTestCase.wrong_token){'-other'}else{''}
        [pscustomobject]@{Name='wsl.exe';CommandLine=('wsl.exe --unit=realme-next-candidate-observer-fixture'+$suffix+' --wait')}
    }
}
function wsl.exe {
    if($args[0] -ne '-d' -or $args[1] -ne 'fixture-distro' -or
       $args[5] -ne 'realme-next-candidate-observer-fixture.service'){throw 'Wrong unit/distribution'}
    $global:observerTestQueries++
    if($global:observerTestCase.unit -eq 'missing'){
        $global:LASTEXITCODE=4
        'LoadState=not-found';'ActiveState=inactive'
    }elseif($global:observerTestCase.unit -eq 'error'){
        $global:LASTEXITCODE=1
        'transport unavailable'
    }else{
        $global:LASTEXITCODE=0
        'LoadState=loaded';('ActiveState='+$global:observerTestCase.unit);'Result=success';'ExecMainStatus=0'
    }
}
& (Join-Path $PSScriptRoot 'tools/build/observe_candidate.ps1') -Run candidate-observer-fixture -Hours 2
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'queries.json'),[string]$global:observerTestQueries)
''')
            harness_path = str(harness)
            if sys.platform == 'linux' and Path(SHELL).name.lower().endswith('.exe'):
                harness_path = subprocess.check_output(['wslpath', '-w', harness_path], text=True).strip()
            options = ['-WindowStyle', 'Hidden'] if Path(SHELL).name.lower().endswith('.exe') else []
            completed = subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                                        'Bypass', *options, '-File', harness_path], capture_output=True,
                                       text=True, timeout=30)
            output = root/'.local/goals/observations'/run
            rows = [json.loads(p.read_text(encoding='utf-8-sig'))
                    for p in sorted(output.glob('hour-*.json'))] if output.exists() else []
            queries = int((root/'queries.json').read_text()) if (root/'queries.json').exists() else 0
            return completed, rows, queries

    def test_missing_waiter_does_not_stop_an_active_unit(self):
        completed, rows, queries = self.observe()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual((len(rows), queries), (2, 2))
        self.assertFalse(rows[0]['matching_windows_waiter'])
        self.assertFalse(rows[0]['collector_terminal'])

    def test_missing_unit_without_collector_is_unresolved(self):
        completed, rows, queries = self.observe(unit='missing')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual((len(rows), queries), (2, 2))
        self.assertIn('unresolved', rows[-1]['stop_reason'])

    def test_terminal_collector_and_missing_unit_stop(self):
        completed, rows, queries = self.observe(unit='missing', result=dict(state='success', finished_ns=123))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual((len(rows), queries), (1, 1))
        self.assertTrue(rows[0]['collector_terminal'])
        self.assertEqual(rows[0]['stop_reason'], 'collector-terminal-unit-gone')

    def test_invalid_finish_time_or_live_unit_prevents_early_stop(self):
        for finish in ['123', None, 0, -1, 123]:
            with self.subTest(finish=finish):
                completed, rows, queries = self.observe(result=dict(state='success', finished_ns=finish))
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual((len(rows), queries), (2, 2))
                self.assertEqual(rows[0]['collector_terminal'], finish == 123)

    def test_cim_failure_or_prefix_collision_still_queries_unit(self):
        for options in [dict(waiter_error=True), dict(waiter=True, wrong_token=True)]:
            with self.subTest(options=options):
                completed, rows, queries = self.observe(**options)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual((len(rows), queries), (2, 2))
                self.assertFalse(rows[0]['matching_windows_waiter'])

    def test_confirmed_unit_failure_stops_without_claiming_collector_success(self):
        completed, rows, queries = self.observe(unit='failed')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual((len(rows), queries), (1, 1))
        self.assertEqual(rows[0]['state'], 'no-collector-result')
        self.assertFalse(rows[0]['collector_terminal'])

    def test_wrong_receipt_refuses_before_output_or_queries(self):
        completed, rows, queries = self.observe(receipt_run='candidate-other')
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual((rows, queries), ([], 0))

    def test_exact_waiter_token_is_recognized_but_does_not_replace_unit_query(self):
        completed, rows, queries = self.observe(waiter=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual((len(rows), queries), (2, 2))
        self.assertTrue(rows[0]['matching_windows_waiter'])

    def test_transport_failure_does_not_infer_a_terminal_unit(self):
        completed, rows, queries = self.observe(unit='error')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual((len(rows), queries), (2, 2))
        self.assertEqual(rows[0]['unit_query_exit_code'], 1)
        self.assertNotIn('stop_reason', rows[0])

    def test_partial_collector_json_does_not_hide_live_unit(self):
        completed, rows, queries = self.observe(result_text='{"state":')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual((len(rows), queries), (2, 2))
        self.assertIn('collector_error', rows[0])
        self.assertEqual(rows[0]['state'], 'no-collector-result')
        self.assertFalse(rows[0]['collector_terminal'])


if __name__ == '__main__':
    unittest.main()
