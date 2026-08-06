#!/usr/bin/env bash
# Packaging gate: the sdist and the wheel must both carry the browser-side files, and the
# vendored Fabric bundle they carry must be byte-identical to the one VENDORED.md documents.
# Neither is observable from Python: a dropped or swapped bundle keeps every unit test green
# and only breaks in a user's browser.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf dist && python -m build >/dev/null
for artifact in dist/*.whl dist/*.tar.gz; do
  python - "$artifact" nicefabric/lib/VENDORED.md <<'EOF'
import hashlib, re, sys, tarfile, zipfile

path, vendored_md = sys.argv[1], sys.argv[2]

# The expected digest is parsed out of VENDORED.md instead of being duplicated here, so the
# documented hash and the gate that enforces it cannot drift apart: re-vendoring means editing
# VENDORED.md, and that edit is what this check reads.
with open(vendored_md, encoding='utf-8') as f:
    match = re.search(r'\*\*sha256:\*\*\s*`([0-9a-f]{64})`', f.read())
assert match, f'{vendored_md}: no sha256 recorded'
expected = match.group(1)

if path.endswith('.whl'):
    archive = zipfile.ZipFile(path)
    names, read = archive.namelist(), archive.read
else:
    archive = tarfile.open(path)
    names = archive.getnames()
    def read(name):
        return archive.extractfile(name).read()

bundles = [n for n in names if n.endswith('lib/nicefabric.min.mjs')]
assert bundles, f'{path}: bundle missing!'
assert any(n.endswith('fabric_canvas.js') for n in names), f'{path}: component JS missing!'
for name in bundles:
    actual = hashlib.sha256(read(name)).hexdigest()
    assert actual == expected, (f'{path}: {name} sha256 {actual} does not match the '
                                f'{expected} recorded in {vendored_md}')
print(f'{path}: OK (bundle sha256 {expected[:12]}... matches VENDORED.md)')
EOF
done
