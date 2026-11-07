"""Exercise shell environment routing with a stub m; no Android build is invoked."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO=Path(__file__).resolve().parents[2]


class DriverPathsTests(unittest.TestCase):
    def test_inherited_output_paths_cannot_redirect_the_selected_store(self):
        with tempfile.TemporaryDirectory() as directory:
            tree=Path(directory)
            (tree/'.realme-next-isolated.json').write_text('{}')
            var=tree/'vendor/lineage/vars/aosp_target_release';var.parent.mkdir(parents=True)
            var.write_text('aosp_target_release=cp2a\n')
            setup=tree/'build/envsetup.sh';setup.parent.mkdir()
            setup.write_text('m() { printf "%s\\n" "$OUT_DIR" "$DIST_DIR" "$TMPDIR" "$GOCACHE" "${OUT_DIR_COMMON_BASE-unset}" > captured; }\n')
            env={**os.environ,'OUT_DIR':'/wrong/out','OUT_DIR_COMMON_BASE':'/wrong/common','DIST_DIR':'/wrong/dist'}
            subprocess.run(['bash',str(REPO/'tools/build/build_candidate_24.0.sh'),
                'nothing','1','unused','RMX3301.1793610000.0123456789ab','1793610000','unused'],
                cwd=tree,env=env,check=True,capture_output=True)
            self.assertEqual((tree/'captured').read_text().splitlines(),[
                'out',str(tree/'out/dist'),str(tree/'out/.tmp'),str(tree/'out/.cache/go-build'),'unset'])


if __name__=='__main__':unittest.main()
