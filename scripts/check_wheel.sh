#!/usr/bin/env bash
set -euo pipefail
rm -rf dist && python -m build >/dev/null
for artifact in dist/*.whl dist/*.tar.gz; do
  python - "$artifact" <<'EOF'
import sys, zipfile, tarfile
p = sys.argv[1]
names = zipfile.ZipFile(p).namelist() if p.endswith('.whl') else tarfile.open(p).getnames()
assert any(n.endswith('lib/nicefabric.min.mjs') for n in names), f'{p}: bundle missing!'
print(f'{p}: OK')
EOF
done
