"""Run backup control flow in PowerShell with synthetic device replies and image bytes.

Only Read-Text and Copy-AdbBlock are replaced by AST extent. The production argument,
identity/mount checks, file hashes, completion logic and receipts execute unchanged.
No ADB process, phone, actual partition or binary transport is used by these tests.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SHELL = shutil.which('pwsh') or shutil.which('powershell.exe') or shutil.which('powershell')

HARNESS = r'''
$ErrorActionPreference='Stop'
$root=$PSScriptRoot
$global:backupTestCase=Get-Content (Join-Path $root 'case.json') -Raw|ConvertFrom-Json
$global:backupTestCopies=0
$scriptPath=Join-Path $root 'tools/device/backup_oem_os.ps1'
$text=[IO.File]::ReadAllText($scriptPath)
$tokens=$null;$parseErrors=$null
$ast=[Management.Automation.Language.Parser]::ParseInput($text,[ref]$tokens,[ref]$parseErrors)
if($parseErrors.Count){throw 'Production script parse failed'}
$replacement=@{
    'Read-Text'=@'
function Read-Text([string]$Command) {
    $case=$global:backupTestCase.scenario
    $copied=$global:backupTestCopies
    $value=switch -Regex ($Command) {
        '^getprop ro.product.model$' {'RMX3301';break}
        '^getprop ro.product.device$' {'RED8ACL1';break}
        '^getprop sys.boot_completed$' {'1';break}
        '^getprop ro.lineage.version$' {'23.2-fixture';break}
        '^getprop ro.build.version.incremental$' {
            if($case -eq 'wrong-build'){'other'}else{'fixture.18'};break
        }
        '^getprop ro.boot.slot_suffix$' {
            if($case -eq 'wrong-slot'){'_a'}else{'_b'};break
        }
        '^getprop ro.boot.vbmeta.device_state$' {'unlocked';break}
        '^getenforce$' {if($case -eq 'permissive'){'Permissive'}else{'Enforcing'};break}
        '^id$' {'uid=0(root) gid=0(root)';break}
        '^snapshotctl dump$' {
            if($case -eq 'merge-started' -and $copied -ge 1){'Update state: merging'}
            else{"Update state: none`nSnapshot state: none"};break
        }
        '^cat /proc/sys/kernel/random/boot_id$' {
            if($case -eq 'rebooted' -and $copied -ge 1){'22222222-2222-2222-2222-222222222222'}
            elseif($case -eq 'missing-boot-id'){''}
            else{'11111111-1111-1111-1111-111111111111'};break
        }
        '^cat /proc/mounts$' {
            $mode=if($case -eq 'mount-became-writable' -and $copied -ge 1){'rw'}else{'ro'}
            "/dev/block/dm-0 / ext4 $mode,relatime 0 0`n/dev/block/dm-1 /product ext4 ro,relatime 0 0";break
        }
        '^readlink -f /dev/block/(mapper/system_b|dm-0)$' {'/dev/block/dm-0';break}
        '^readlink -f /dev/block/(mapper/product_b|dm-1)$' {'/dev/block/dm-1';break}
        '^cat /sys/class/block/dm-0/dm/name$' {
            if($case -eq 'mapping-changed' -and $copied -ge 1){'other_b'}else{'system_b'};break
        }
        '^cat /sys/class/block/dm-1/dm/name$' {'product_b';break}
        '^blockdev --getsize64 /dev/block/mapper/(system|product)_b$' {
            if($case -eq 'size-changed' -and $copied -ge 1){'8'}else{'4'};break
        }
        '^sha256sum /dev/block/mapper/(system|product)_b$' {
            if($case -eq 'invalid-digest'){'bad'}
            elseif($case -eq 'earlier-source-changed' -and $copied -ge 2 -and $Command.EndsWith('system_b')){
                ('0'*64)+'  '+($Command -replace '^sha256sum ','')
            }else{
                $hasher=[Security.Cryptography.SHA256]::Create()
                try{$digest=([BitConverter]::ToString($hasher.ComputeHash([byte[]](0,255,10,13)))).Replace('-','').ToLowerInvariant()}
                finally{$hasher.Dispose()}
                $digest+'  '+($Command -replace '^sha256sum ','')
            };break
        }
        default {throw ('Unexpected synthetic device read: '+$Command)}
    }
    $record.commands+=@{command=$Command;exit_code=0;stdout=$value}
    return $value
}
'@
    'Copy-AdbBlock'=@'
function Copy-AdbBlock([string]$Block,[string]$Destination) {
    if($Block -notmatch '^/dev/block/mapper/(system|product)_b$'){throw 'Test source outside scope'}
    $global:backupTestCopies++
    if($global:backupTestCase.scenario -eq 'corrupt-transfer'){
        [IO.File]::WriteAllBytes($Destination,[byte[]](0,0,0,0))
    }else{[IO.File]::WriteAllBytes($Destination,[byte[]](0,255,10,13))}
    if($global:backupTestCase.scenario -eq 'partial-transfer'){throw 'Synthetic interrupted transfer'}
}
'@
}
$targets=@($ast.FindAll({param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -in @('Read-Text','Copy-AdbBlock')
},$true))
if($targets.Count -ne 2){throw 'Unexpected production function layout'}
foreach($target in ($targets|Sort-Object {$_.Extent.StartOffset} -Descending)){
    $text=$text.Substring(0,$target.Extent.StartOffset)+$replacement[$target.Name]+$text.Substring($target.Extent.EndOffset)
}
[IO.File]::WriteAllText($scriptPath,$text)
$parameters=@{OutputDirectory=(Join-Path $root '.local/capture');AdbPath=$scriptPath;
    Serial='TESTSERIAL';ExpectedSlot='b';ExpectedIncremental='fixture.18'}
if($global:backupTestCase.scenario -eq 'invalid-incremental'){$parameters.ExpectedIncremental='invalid;command'}
& $scriptPath @parameters
'''


@unittest.skipUnless(SHELL, 'PowerShell unavailable; backup state checks blocked')
class OemBackupTests(unittest.TestCase):
    def run_case(self, scenario):
        scratch = ROOT / 'tmp/backup-tests'
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as name:
            root = Path(name)
            script = root / 'tools/device/backup_oem_os.ps1'
            script.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / 'tools/device/backup_oem_os.ps1', script)
            (root / 'case.json').write_text(json.dumps(dict(scenario=scenario)))
            harness = root / 'harness.ps1'
            harness.write_text(HARNESS)
            path = str(harness)
            windows_shell = Path(SHELL).name.lower().endswith('.exe')
            if sys.platform == 'linux' and windows_shell:
                path = subprocess.check_output(['wslpath', '-w', path], text=True).strip()
            options = ['-WindowStyle', 'Hidden'] if windows_shell else []
            result = subprocess.run([SHELL, '-NoProfile', '-NonInteractive', '-ExecutionPolicy',
                                     'Bypass', *options, '-File', path], capture_output=True,
                                    text=True, timeout=30)
            receipt = root / '.local/capture/capture.json'
            record = json.loads(receipt.read_text(encoding='utf-8-sig')) if receipt.exists() else None
            images = sorted(p.name for p in (root / '.local/capture').glob('*.img'))
            return result, record, images

    def test_exact_stable_source_completes_with_verified_local_files(self):
        result, record, images = self.run_case('stable')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(record['complete'])
        self.assertEqual(record['expected_incremental'], 'fixture.18')
        self.assertEqual(record['boot_id'], '11111111-1111-1111-1111-111111111111')
        self.assertEqual(images, ['product_b.img', 'system_b.img'])
        self.assertEqual(len(record['captures']), 2)
        self.assertTrue(all(row['bytes'] == 4 for row in record['captures']))

    def test_wrong_initial_identity_refuses_before_image_capture(self):
        for scenario in ['wrong-build', 'wrong-slot', 'permissive', 'missing-boot-id']:
            with self.subTest(scenario=scenario):
                result, record, images = self.run_case(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(record['complete'])
                self.assertEqual(images, [])

    def test_reboot_or_snapshot_change_during_copy_is_not_complete(self):
        for scenario in ['rebooted', 'merge-started']:
            with self.subTest(scenario=scenario):
                result, record, images = self.run_case(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(record['complete'])
                self.assertEqual(images, ['system_b.img'])
                self.assertEqual(record['captures'], [])

    def test_changed_mount_mapping_or_size_refuses(self):
        for scenario in ['mount-became-writable', 'mapping-changed', 'size-changed']:
            with self.subTest(scenario=scenario):
                result, record, _ = self.run_case(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(record['complete'])
                self.assertEqual(record['captures'], [])

    def test_earlier_image_change_is_caught_at_set_completion(self):
        result, record, images = self.run_case('earlier-source-changed')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(record['complete'])
        self.assertIn('Earlier source changed', record['error'])
        self.assertEqual(len(record['captures']), 2)
        self.assertEqual(len(images), 2)

    def test_corrupt_or_partial_transfer_keeps_incomplete_evidence(self):
        for scenario in ['corrupt-transfer', 'partial-transfer']:
            with self.subTest(scenario=scenario):
                result, record, images = self.run_case(scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(record['complete'])
                self.assertEqual(record['captures'], [])
                self.assertEqual(images, ['system_b.img'])

    def test_invalid_digest_refuses_before_transfer(self):
        result, record, images = self.run_case('invalid-digest')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(record['complete'])
        self.assertEqual(images, [])

    def test_invalid_incremental_refuses_before_output(self):
        result, record, images = self.run_case('invalid-incremental')
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(record)
        self.assertEqual(images, [])


if __name__ == '__main__':
    unittest.main()
