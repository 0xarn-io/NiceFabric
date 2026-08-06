# Vendored: Fabric.js

This directory vendors a prebuilt browser bundle of [Fabric.js](https://fabricjs.com/).

- **Upstream package:** `fabric@7.4.0`
- **Source URL:** https://registry.npmjs.org/fabric/-/fabric-7.4.0.tgz
- **Vendored file:** `nicefabric.min.mjs` (from `package/dist/index.min.mjs` in the tarball)
- **sha256:** `fbb5df348454a703924cf08d18df25a6c44d652b14732951b9ec18c80bfa18bf`

The file is renamed from `index.min.mjs` to `nicefabric.min.mjs` (and not `fabric.min.mjs`)
because NiceGUI derives an import-map bare module name from the filename up to the first
dot, and those bare names are process-global with an assertion against duplicates —
`fabric.min.mjs` would collide with any other installed package that also vendors Fabric.js
under that name.

## Modifications

The only modification to the upstream file is removal of the trailing
`//# sourceMappingURL=...` comment (no sourcemap file is vendored alongside it).

## Reproduction

```bash
mkdir -p nicefabric/lib
curl -fsSL https://registry.npmjs.org/fabric/-/fabric-7.4.0.tgz -o /tmp/fabric-7.4.0.tgz
tar -xzOf /tmp/fabric-7.4.0.tgz package/dist/index.min.mjs > nicefabric/lib/nicefabric.min.mjs
sed -i '/^\/\/# sourceMappingURL=/d' nicefabric/lib/nicefabric.min.mjs
sha256sum nicefabric/lib/nicefabric.min.mjs
```

## License

Fabric.js is MIT licensed. Upstream license notice (from `package/LICENSE` in the tarball):

```
MIT License

Copyright (c) 2008-2015 Printio (Juriy Zaytsev, Maxim Chernyak)
Copyright (c) 2016-present Andrea Bogazzi, Shachar Nen and Fabric.js contributors (https://github.com/fabricjs/fabric.js/graphs/contributors)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
