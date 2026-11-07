"""Check public release metadata, source hashes, links and artifact boundaries."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def main():
    metadata = json.loads((ROOT/'release.json').read_text())
    checksums = {}
    for line in (ROOT/'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        assert re.fullmatch('[0-9a-f]{64}', digest) and '/' not in name and '\\' not in name
        assert name not in checksums
        checksums[name] = digest
    assert checksums['release.json'] == hashlib.sha256((ROOT/'release.json').read_bytes()).hexdigest()
    for asset in metadata['assets']:
        assert checksums[asset['name']] == asset['sha256']
    exported = 0
    for manifest in (ROOT/'source').rglob('PROVENANCE.json'):
        provenance = json.loads(manifest.read_text())
        for row in provenance['files']:
            path = PurePosixPath(row['path'])
            assert not path.is_absolute() and '..' not in path.parts
            local = manifest.parent/Path(*path.parts)
            assert local.is_file() and hashlib.sha256(local.read_bytes()).hexdigest() == row['sha256'], row['path']
            exported += 1
    documents = [p for p in ROOT.rglob('*.md') if '.git' not in p.parts]
    for document in documents:
        text = document.read_text(encoding='utf-8')
        for link in re.findall(r'\[[^\]]*\]\(([^)]+)\)', text):
            if re.match(r'^(https?://|#|mailto:)', link):
                continue
            target = link.split('#')[0]
            assert (document.parent/target).exists(), (document.relative_to(ROOT), link)
    forbidden = {'.apk', '.zip', '.img', '.pk8', '.p12', '.jks', '.vhdx'}
    for path in ROOT.rglob('*'):
        if '.git' in path.parts or not path.is_file():
            continue
        assert path.suffix not in forbidden, path.relative_to(ROOT)
        data = path.read_bytes()
        assert not re.search(rb'(?m)^-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{22,}', data), path.relative_to(ROOT)
    print(f"PASS: {len(checksums)} checksums, {exported} source files and {len(documents)} public guides")


if __name__ == '__main__':
    main()
