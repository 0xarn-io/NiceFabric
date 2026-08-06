# NiceFabric — Fabric.js Canvas Element Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pip-installable `nicefabric` package exposing Fabric.js 7.4.0 as a first-class NiceGUI element (`FabricCanvas`), with a Pythonic helper API layered over a generic bridge — no fork of NiceGUI or Fabric.js.

**Architecture:** Python holds the canonical object registry (`dict[id, props]`, insertion order = z-order); the JS side is a Vue component that revives registry dicts through one `fabric.util.enlivenObjects()` pipeline and emits compact, allow-listed events back. Readiness follows NiceGUI's own Leaflet pattern (init handshake, `NullResponse` gating, replay of pre-connect state). Browser-originated events are validated server-side before touching the registry; large exports (PNG/SVG) travel over an HTTP POST side-channel because socket messages >1 MB close the websocket.

**Tech Stack:** Python ≥3.10, NiceGUI ≥3.6,<4 (element/`dependencies=` API + `register_importmap_override`), Fabric.js 7.4.0 vendored browser ESM bundle, hatchling, pytest + `nicegui.testing.user_plugin`, Playwright (E2E).

## Global Constraints

- No fork or patch of NiceGUI or Fabric.js — public extension points only.
- Vendored bundle: `fabric@7.4.0` `dist/index.min.mjs` from the npm registry tarball, renamed `nicefabric/lib/nicefabric.min.mjs` (importmap bare name must be `nicefabric`, never `fabric` — NiceGUI library names are process-global with an assert on duplicates), sourceMappingURL line stripped, sha256 recorded in `nicefabric/lib/VENDORED.md`.
- `pyproject.toml`: hatchling; `requires-python = ">=3.10"`; `dependencies = ["nicegui>=3.6,<4"]`; `[tool.hatch.build] artifacts = ["nicefabric/lib/*.mjs"]` (hatchling honors `.gitignore` — without this a stray ignore pattern silently ships a wheel with no bundle).
- Object prop kwargs map 1:1 to Fabric camelCase names (`strokeWidth=`); constructor args are Pythonic. Warn on `_` in prop kwargs (no Fabric prop is snake_case).
- Browser events are untrusted: geometry merges limited to `_GEOMETRY_KEYS` with finite numbers, text capped at 20 000 chars, drawn paths ≤ 256 KB and type `Path` only, `load_json` ≤ 1 MB / ≤1000 objects / type allow-list / fresh ids / Image `src` scheme allow-list.
- Never emit raw fabric event objects (circular/huge); payloads are built explicitly in JS.
- All sync-back handlers no-op silently on unknown ids (races with `load_json`/`clear`).
- Do not claim state survives page reloads: NiceGUI 3.x builds fresh elements per page visit. Replay covers pre-socket-connect state only; persistence is the app's job via `app.storage` (README recipe).
- Project rules from `.claude/CLAUDE_RULES.md` apply: simplicity first, surgical changes, every step verifiable.
- Commit per task on branch `claude/fabric-nicegui-integration-temx74`; never push elsewhere.

---

### Task 1: Package scaffold + vendored bundle + packaging gate

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `LICENSE`, `nicefabric/__init__.py`, `nicefabric/py.typed`, `nicefabric/lib/nicefabric.min.mjs`, `nicefabric/lib/VENDORED.md`, `scripts/check_wheel.sh`

**Interfaces:**
- Produces: importable package `nicefabric` (version `0.1.0`), vendored bundle at `nicefabric/lib/nicefabric.min.mjs`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "nicefabric"
version = "0.1.0"
description = "Fabric.js canvas element for NiceGUI"
readme = "README.md"
license = "MIT"
requires-python = ">=3.10"
dependencies = ["nicegui>=3.6,<4"]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "playwright", "build"]

[tool.hatch.build]
artifacts = ["nicefabric/lib/*.mjs"]

[tool.hatch.build.targets.wheel]
packages = ["nicefabric"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Write `.gitignore`** (must NOT match `*.mjs`)

```
__pycache__/
*.egg-info/
dist/
build/
.venv/
.pytest_cache/
```

- [ ] **Step 3: Write `LICENSE`** — standard MIT text, copyright holder `0xarn-io`, year 2026.

- [ ] **Step 4: Vendor the bundle from the npm tarball and strip the sourcemap pointer**

```bash
mkdir -p nicefabric/lib
curl -fsSL https://registry.npmjs.org/fabric/-/fabric-7.4.0.tgz -o /tmp/fabric-7.4.0.tgz
tar -xzOf /tmp/fabric-7.4.0.tgz package/dist/index.min.mjs > nicefabric/lib/nicefabric.min.mjs
sed -i '/^\/\/# sourceMappingURL=/d' nicefabric/lib/nicefabric.min.mjs
sha256sum nicefabric/lib/nicefabric.min.mjs
```
Expected: file ~292 KB; note the printed hash.

- [ ] **Step 5: Write `nicefabric/lib/VENDORED.md`** — containing: Fabric.js MIT copyright notice (copy from `package/LICENSE` inside the tarball), upstream `fabric@7.4.0`, source URL `https://registry.npmjs.org/fabric/-/fabric-7.4.0.tgz`, the sha256 from Step 4, the exact reproduction commands from Step 4, and one line noting the stripped `sourceMappingURL` comment (only modification).

- [ ] **Step 6: Write `nicefabric/__init__.py`** (placeholder exports arrive in Task 2)

```python
__version__ = '0.1.0'
```

Create empty `nicefabric/py.typed`.

- [ ] **Step 7: Write the packaging gate `scripts/check_wheel.sh`**

```bash
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
```

- [ ] **Step 8: Verify install + gate**

Run: `pip install -e '.[dev]' && python -c "import nicefabric; print(nicefabric.__version__)" && bash scripts/check_wheel.sh`
Expected: `0.1.0`, then `OK` for wheel and sdist.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .gitignore LICENSE nicefabric scripts
git commit -m "feat: package scaffold with vendored fabric 7.4.0 bundle"
```

---

### Task 2: Element skeleton — init handshake + add_rect vertical slice

**Files:**
- Create: `nicefabric/fabric_canvas.py`, `nicefabric/fabric_canvas.js`, `tests/conftest.py`, `tests/test_canvas.py`
- Modify: `nicefabric/__init__.py`

**Interfaces:**
- Produces: `FabricCanvas(width: int = 800, height: int = 600, *, background: str = '#ffffff', selection: bool = True)` with `add_rect(**props) -> str` (returns object id at this stage), `initialized() -> Awaitable[None]`, attribute `is_initialized: bool`, private registry `_objects: dict[str, dict]`.
- JS component methods consumed later: `sync_objects(objs)`, `add_object(obj)`.

- [ ] **Step 1: Write the failing tests** (`tests/conftest.py` + first tests)

```python
# tests/conftest.py
pytest_plugins = ['nicegui.testing.user_plugin']
```

```python
# tests/test_canvas.py
from nicegui import ui
from nicegui.testing import User

from nicefabric import FabricCanvas


async def test_element_renders(user: User) -> None:
    @ui.page('/')
    def page() -> None:
        FabricCanvas(width=400, height=300)
    await user.open('/')
    # the custom tag is present in the page tree
    assert user.find(FabricCanvas).elements


async def test_add_rect_registers_before_init(user: User) -> None:
    canvases: list[FabricCanvas] = []

    @ui.page('/')
    def page() -> None:
        c = FabricCanvas()
        c.add_rect(left=10, top=20, width=30, height=40, fill='red')
        canvases.append(c)
    await user.open('/')
    c = canvases[0]
    assert not c.is_initialized          # user fixture never runs JS → init never fires
    (obj,) = c._objects.values()
    assert obj['type'] == 'Rect' and obj['left'] == 10 and 'id' in obj
```

**Never `await c.initialized()` or any round-trip method in user-fixture tests** — the fixture doesn't execute JS, so they deadlock/return `None` by design.

- [ ] **Step 2: Run tests — expect import failure**

Run: `pytest tests/test_canvas.py -v`
Expected: FAIL — `ImportError: cannot import name 'FabricCanvas'`.

- [ ] **Step 3: Write `nicefabric/fabric_canvas.py` (skeleton)**

```python
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from nicegui.awaitable_response import AwaitableResponse, NullResponse
from nicegui.element import Element


class FabricCanvas(Element, component='fabric_canvas.js', dependencies=['lib/nicefabric.min.mjs']):

    def __init__(self, width: int = 800, height: int = 600, *,
                 background: str = '#ffffff', selection: bool = True) -> None:
        super().__init__()
        self._props['width'] = width
        self._props['height'] = height
        self._props['background'] = background
        self._props['selection'] = selection
        self._objects: dict[str, dict] = {}
        self._canvas_state: dict[str, Any] = {}
        self.is_initialized = False
        self._init_event = asyncio.Event()
        self.on('init', self._handle_init)

    def _handle_init(self) -> None:
        self.is_initialized = True
        self._init_event.set()
        self.run_method('sync_objects', list(self._objects.values()))

    async def initialized(self) -> None:
        """Wait until the browser-side canvas exists (never resolves in user-fixture tests)."""
        await self.client.connected()
        await self._init_event.wait()

    def run_method(self, name: str, *args: Any, timeout: float = 1) -> AwaitableResponse:
        if not self.is_initialized:
            return NullResponse()
        return super().run_method(name, *args, timeout=timeout)

    def add_object(self, type_: str, **props: Any) -> str:
        id_ = uuid.uuid4().hex
        obj = {'type': type_, 'id': id_, **props}
        self._objects[id_] = obj
        self.run_method('add_object', obj)
        return id_

    def add_rect(self, **props: Any) -> str:
        return self.add_object('Rect', **props)
```

- [ ] **Step 4: Write `nicefabric/fabric_canvas.js` (skeleton)**

```js
import * as fabric from "nicefabric";

fabric.FabricObject.customProperties = ["id"];

export default {
  template: "<div></div>",
  props: { width: Number, height: Number, background: String, selection: Boolean },
  mounted() {
    // a <canvas> root would be re-parented by Fabric into .canvas-container,
    // breaking NiceGUI .classes()/.style() — so the root is a <div>
    const el = document.createElement("canvas");
    this.$el.appendChild(el);
    this.canvas = new fabric.Canvas(el, {
      width: this.width,
      height: this.height,
      backgroundColor: this.background,
      selection: this.selection,
    });
    const iv = setInterval(() => {
      if (window.socket.id === undefined) return;  // Leaflet handshake pattern
      this.$emit("init");
      clearInterval(iv);
    }, 100);
  },
  beforeUnmount() {
    this.canvas?.dispose();  // async, but DOM cleanup is synchronous — safe fire-and-forget
  },
  methods: {
    find(id) {
      return this.canvas.getObjects().find((o) => o.id === id);
    },
    async enliven_and_add(objs) {
      const results = await Promise.allSettled(
        objs.map((o) => fabric.util.enlivenObjects([o]).then(([x]) => x)),
      );
      results.forEach((r, i) => {
        if (r.status === "fulfilled" && r.value) this.canvas.add(r.value);
        else this.$emit("object-error", { id: objs[i].id, message: String(r.reason ?? "enliven failed") });
      });
      this.canvas.requestRenderAll();
    },
    async sync_objects(objs) {
      this.canvas.remove(...this.canvas.getObjects());
      await this.enliven_and_add(objs);
    },
    async add_object(obj) {
      if (this.find(obj.id)) return;  // idempotent — replay-safe
      await this.enliven_and_add([obj]);
    },
  },
};
```

- [ ] **Step 5: Export from `nicefabric/__init__.py`**

```python
from .fabric_canvas import FabricCanvas

__version__ = '0.1.0'
__all__ = ['FabricCanvas']
```

- [ ] **Step 6: Run tests — expect pass**

Run: `pytest tests/test_canvas.py -v`
Expected: 2 passed.

- [ ] **Step 7: Browser smoke test** (the one thing the user fixture can't prove)

```python
# /tmp/smoke.py
from nicegui import ui
from nicefabric import FabricCanvas

@ui.page('/')
def page() -> None:
    c = FabricCanvas(width=400, height=300, background='#eeeeee')
    c.add_rect(left=10, top=20, width=100, height=80, fill='red')

ui.run(show=False, port=8123)
```

Run: `python /tmp/smoke.py &` then Playwright (chromium is pre-installed): open `http://localhost:8123`, assert `div.canvas-container` exists and a screenshot shows the red rect. Kill the server.
Expected: container present, rect visible, browser console free of errors.

- [ ] **Step 8: Extend the packaging gate** — in `scripts/check_wheel.sh`, add below the `.mjs` assert:

```python
assert any(n.endswith('fabric_canvas.js') for n in names), f'{p}: component JS missing!'
```

Run: `bash scripts/check_wheel.sh` — expected: `OK` for both artifacts.

- [ ] **Step 9: Commit**

```bash
git add nicefabric tests scripts
git commit -m "feat: FabricCanvas element with init handshake and add_rect slice"
```

---

### Task 3: Registry API — FabricObject handle, helpers, canvas ops

**Files:**
- Modify: `nicefabric/fabric_canvas.py`, `nicefabric/__init__.py`, `nicefabric/fabric_canvas.js`, `tests/test_canvas.py`

**Interfaces:**
- Produces (Python): `FabricObject` with `.id: str`, `.type: str`, `.props: dict` (read-only copy), `.update(**props) -> None`, `.delete() -> None`, `.bring_to_front() -> None`, `.send_to_back() -> None`, `.run_method(name, *args, timeout=1) -> AwaitableResponse`.
  `add_object`/`add_rect`/`add_circle`/`add_ellipse`/`add_line`/`add_polygon`/`add_polyline`/`add_path`/`add_text`/`add_image` now return `FabricObject`. Canvas ops: `update(obj_or_id, **props)`, `remove(obj_or_id)`, `clear()`, `set_background(color)`, `set_zoom(z)`, `absolute_pan(x, y)`, `resize(width, height)`, `bring_to_front(obj_or_id)`, `send_to_back(obj_or_id)`, `enable_drawing(color='#000000', width=2)`, `disable_drawing()`, read-only property `draw_mode: bool`, `run_canvas_method(name, *args, timeout=1)`, `run_object_method(obj_or_id, name, *args, timeout=1)`.
- Produces (JS methods): `update_object(id, props)`, `remove_object(id)`, `clear()`, `set_background(color)`, `set_zoom(z)`, `absolute_pan(x, y)`, `resize(w, h)`, `bring_to_front(id)`, `send_to_back(id)`, `set_draw_mode(on, opts)`, `run_canvas_method(name, ...args)`, `run_object_method(id, name, ...args)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_canvas.py`; each test builds a page exactly like `test_add_rect_registers_before_init` and grabs the canvas from the closure — repeat that boilerplate, don't factor it prematurely)

```python
async def test_helpers_return_handles_and_register(user: User) -> None:
    ...  # page boilerplate as above
    r = c.add_rect(left=1, top=2, width=3, height=4)
    t = c.add_text('hello', left=5, top=6)
    assert r.type == 'Rect' and t.type == 'Textbox'
    assert c._objects[r.id]['left'] == 1
    assert c._objects[t.id]['text'] == 'hello'


async def test_update_delete_and_zorder(user: User) -> None:
    ...
    a, b = c.add_rect(), c.add_circle(radius=5)
    a.update(fill='blue')
    assert c._objects[a.id]['fill'] == 'blue'
    c.bring_to_front(a)                      # accepts handle or id
    assert list(c._objects) == [b.id, a.id]  # dict order = z-order
    a.delete()
    assert a.id not in c._objects


async def test_snake_case_prop_warns(user: User) -> None:
    ...
    with pytest.warns(UserWarning, match='stroke_width'):
        c.add_rect(stroke_width=4)


async def test_image_defaults_cross_origin(user: User) -> None:
    ...
    img = c.add_image('https://example.com/a.png')
    assert c._objects[img.id]['crossOrigin'] == 'anonymous'
    assert c._objects[img.id]['src'] == 'https://example.com/a.png'


async def test_run_canvas_method_rejects_hostile_name(user: User) -> None:
    ...
    with pytest.raises(ValueError):
        c.run_canvas_method(':alert(1);//')
```

- [ ] **Step 2: Run — expect failures** (`AttributeError`/`TypeError`), then implement.

- [ ] **Step 3: Implement in `fabric_canvas.py`**

```python
import json
import math
import re
import warnings

_METHOD_NAME = re.compile(r'^[A-Za-z_$][\w$.]*$')


class FabricObject:
    """Lightweight handle to one object in a FabricCanvas registry."""

    def __init__(self, canvas: 'FabricCanvas', id_: str) -> None:
        self._canvas = canvas
        self.id = id_

    @property
    def type(self) -> str:
        return self._canvas._objects[self.id]['type']

    @property
    def props(self) -> dict:
        return dict(self._canvas._objects[self.id])

    def update(self, **props: Any) -> None:
        self._canvas.update(self.id, **props)

    def delete(self) -> None:
        self._canvas.remove(self.id)

    def bring_to_front(self) -> None:
        self._canvas.bring_to_front(self.id)

    def send_to_back(self) -> None:
        self._canvas.send_to_back(self.id)

    def run_method(self, name: str, *args: Any, timeout: float = 1) -> AwaitableResponse:
        return self._canvas.run_object_method(self.id, name, *args, timeout=timeout)
```

In `FabricCanvas` (replacing the Task-2 `add_object`/`add_rect`):

```python
    @staticmethod
    def _warn_snake_case(props: dict) -> None:
        for key in props:
            if '_' in key:
                head, *rest = key.split('_')
                suggestion = head + ''.join(part.title() for part in rest)
                warnings.warn(f'prop {key!r} contains "_" — Fabric props are camelCase '
                              f'(did you mean {suggestion!r}?)', UserWarning, stacklevel=3)

    @staticmethod
    def _id_of(obj_or_id: 'FabricObject | str') -> str:
        return obj_or_id.id if isinstance(obj_or_id, FabricObject) else obj_or_id

    def add_object(self, type_: str, **props: Any) -> FabricObject:
        self._warn_snake_case(props)
        id_ = uuid.uuid4().hex
        self._objects[id_] = {'type': type_, 'id': id_, **props}
        self.run_method('add_object', self._objects[id_])
        return FabricObject(self, id_)

    def add_rect(self, **props: Any) -> FabricObject: return self.add_object('Rect', **props)
    def add_circle(self, **props: Any) -> FabricObject: return self.add_object('Circle', **props)
    def add_ellipse(self, **props: Any) -> FabricObject: return self.add_object('Ellipse', **props)
    def add_line(self, x1: float, y1: float, x2: float, y2: float, **props: Any) -> FabricObject:
        return self.add_object('Line', x1=x1, y1=y1, x2=x2, y2=y2, **props)
    def add_polygon(self, points: list[dict], **props: Any) -> FabricObject:
        return self.add_object('Polygon', points=points, **props)
    def add_polyline(self, points: list[dict], **props: Any) -> FabricObject:
        return self.add_object('Polyline', points=points, **props)
    def add_path(self, path: str, **props: Any) -> FabricObject:
        return self.add_object('Path', path=path, **props)

    def add_text(self, text: str, **props: Any) -> FabricObject:
        """Creates a Fabric *Textbox* (editable, word-wrapping).

        For other text types use ``add_object('IText', text=...)`` etc.
        """
        props.setdefault('width', 200)
        return self.add_object('Textbox', text=text, **props)

    def add_image(self, url: str, **props: Any) -> FabricObject:
        props.setdefault('crossOrigin', 'anonymous')  # keeps toDataURL un-tainted
        return self.add_object('Image', src=url, **props)

    def update(self, obj_or_id: FabricObject | str, **props: Any) -> None:
        self._warn_snake_case(props)
        id_ = self._id_of(obj_or_id)
        self._objects[id_].update(props)
        self.run_method('update_object', id_, props)

    def remove(self, obj_or_id: FabricObject | str) -> None:
        id_ = self._id_of(obj_or_id)
        self._objects.pop(id_, None)
        self.run_method('remove_object', id_)

    def clear(self) -> None:
        self._objects.clear()
        self.run_method('clear')

    def set_background(self, color: str) -> None:
        self._canvas_state['background'] = color
        self._props['background'] = color
        self.run_method('set_background', color)

    def set_zoom(self, zoom: float) -> None:
        self._canvas_state['zoom'] = zoom
        self.run_method('set_zoom', zoom)

    def absolute_pan(self, x: float, y: float) -> None:
        self._canvas_state['pan'] = [x, y]
        self.run_method('absolute_pan', x, y)

    def resize(self, width: int, height: int) -> None:
        self._props['width'] = width
        self._props['height'] = height
        self.run_method('resize', width, height)

    def bring_to_front(self, obj_or_id: FabricObject | str) -> None:
        id_ = self._id_of(obj_or_id)
        self._objects[id_] = self._objects.pop(id_)      # move to end = top
        self.run_method('bring_to_front', id_)

    def send_to_back(self, obj_or_id: FabricObject | str) -> None:
        id_ = self._id_of(obj_or_id)
        entry = self._objects.pop(id_)
        self._objects = {id_: entry, **self._objects}
        self.run_method('send_to_back', id_)

    def enable_drawing(self, color: str = '#000000', width: int = 2) -> None:
        self._canvas_state['drawing'] = {'color': color, 'width': width}
        self.run_method('set_draw_mode', True, self._canvas_state['drawing'])

    def disable_drawing(self) -> None:
        self._canvas_state.pop('drawing', None)
        self.run_method('set_draw_mode', False, {})

    @property
    def draw_mode(self) -> bool:
        return 'drawing' in self._canvas_state

    def run_canvas_method(self, name: str, *args: Any, timeout: float = 1) -> AwaitableResponse:
        self._check_method_name(name)
        return self.run_method('run_canvas_method', name, *args, timeout=timeout)

    def run_object_method(self, obj_or_id: FabricObject | str, name: str, *args: Any,
                          timeout: float = 1) -> AwaitableResponse:
        self._check_method_name(name)
        return self.run_method('run_object_method', self._id_of(obj_or_id), name, *args, timeout=timeout)

    @staticmethod
    def _check_method_name(name: str) -> None:
        if not _METHOD_NAME.match(name.removeprefix(':')):
            raise ValueError(f'invalid method name: {name!r}')
```

`_handle_init` grows the canvas-state replay (audit: ops issued pre-connect were silently lost):

```python
    def _handle_init(self) -> None:
        self.is_initialized = True
        self._init_event.set()
        self.run_method('sync_objects', list(self._objects.values()))
        state = self._canvas_state
        if 'background' in state: self.run_method('set_background', state['background'])
        if 'zoom' in state: self.run_method('set_zoom', state['zoom'])
        if 'pan' in state: self.run_method('absolute_pan', *state['pan'])
        if 'drawing' in state: self.run_method('set_draw_mode', True, state['drawing'])
```

- [ ] **Step 4: Add the JS methods** (append to `methods` in `fabric_canvas.js`)

```js
    update_object(id, props) {
      const o = this.find(id);
      if (!o) return;
      o.set(props);
      o.setCoords();
      this.canvas.requestRenderAll();
    },
    remove_object(id) {
      const o = this.find(id);
      if (o) this.canvas.remove(o);
      this.canvas.requestRenderAll();
    },
    clear() {
      this.canvas.remove(...this.canvas.getObjects());
      this.canvas.requestRenderAll();
    },
    set_background(color) {
      this.canvas.backgroundColor = color;
      this.canvas.requestRenderAll();
    },
    set_zoom(z) { this.canvas.setZoom(z); },
    absolute_pan(x, y) { this.canvas.absolutePan(new fabric.Point(x, y)); },
    resize(w, h) { this.canvas.setDimensions({ width: w, height: h }); },
    bring_to_front(id) {
      const o = this.find(id);
      if (o) this.canvas.bringObjectToFront(o);
      this.canvas.requestRenderAll();
    },
    send_to_back(id) {
      const o = this.find(id);
      if (o) this.canvas.sendObjectToBack(o);
      this.canvas.requestRenderAll();
    },
    set_draw_mode(on, opts) {
      this.canvas.isDrawingMode = on;
      if (on) {
        const b = new fabric.PencilBrush(this.canvas);
        b.color = opts.color;
        b.width = opts.width;
        this.canvas.freeDrawingBrush = b;
      }
    },
    run_canvas_method(name, ...args) { return this._run(this.canvas, name, args); },
    run_object_method(id, name, ...args) {
      const o = this.find(id);
      if (o) return this._run(o, name, args);
    },
    _run(target, name, args) {
      if (name.startsWith(":")) {
        name = name.slice(1);
        args = args.map((a) => new Function(`return (${a})`)());
      }
      return runMethod(target, name, args);
    },
```

- [ ] **Step 5: Run tests — expect all pass**: `pytest tests/ -v`
- [ ] **Step 6: Commit** — `git add -u && git add nicefabric tests && git commit -m "feat: FabricObject handles, shape helpers, canvas ops"`

---

### Task 4: Sync-back handlers with server-side validation

**Files:**
- Modify: `nicefabric/fabric_canvas.py`, `nicefabric/fabric_canvas.js`, `tests/test_canvas.py`

**Interfaces:**
- Produces (Python): ctor kwargs `keyboard_delete: bool = False`, `on_selection`, `on_modified`, `on_added`, `on_error`, `on_mouse_down`, `on_mouse_up`, `on_text_changed` (each `Handler[GenericEventArguments] | None`); `get_selected() -> list[FabricObject]`, `remove_selected() -> None`, `discard_selection() -> None`; module constants `_GEOMETRY_KEYS`, `_TEXT_TYPES`, `_MAX_TEXT_LEN = 20_000`, `_MAX_PATH_BYTES = 256_000`, `_PATH_KEYS`.
- Produces (JS emits): `object-modified {id, props}`, `object-added {id, obj}` (free-drawn paths only), `object-error {id, message}`, `selection {kind, ids}`, `text-changed {id, text}` (throttle 0.2), `mouse-down`/`mouse-up` `{x, y, id|null}`, `request-delete {ids}`.

**Design notes (why, from the audits):**
- Browser events are forgeable — a client can invoke any handler with arbitrary JSON. All filtering must happen server-side; client-side compactness is a bandwidth courtesy, not a control.
- Multi-select geometry: while objects sit in an ActiveSelection their coords are group-relative. Instead of matrix-decomposing (fiddly, origin-sensitive), sync members *after deselection*, when Fabric has restored absolute coords — `selection:updated`/`selection:cleared` hand us `e.deselected`; read props on the next tick. The E2E test in Task 8 asserts exactly this.
- `path:created` is the ONLY source of `object-added` (fabric's generic `object:added` also fires for programmatic adds → echo loop).
- Keyboard delete round-trips through Python (`request-delete` → authoritative `remove`) so the registry never diverges.

- [ ] **Step 1: Write the failing tests** (test file needs `import json` and `import pytest` at the top from here on)

```python
from nicegui.events import GenericEventArguments


def _ev(canvas, args: dict) -> GenericEventArguments:
    return GenericEventArguments(sender=canvas, client=canvas.client, args=args)


async def test_modified_merges_geometry_only(user: User) -> None:
    ...
    r = c.add_rect(left=0, top=0)
    c._on_modified(_ev(c, {'id': r.id, 'props': {
        'left': 50.5, 'angle': 90, 'type': 'Image', 'src': 'https://evil', 'fill': 'green'}}))
    entry = c._objects[r.id]
    assert entry['left'] == 50.5 and entry['angle'] == 90
    assert entry['type'] == 'Rect' and 'src' not in entry and entry.get('fill') != 'green'


async def test_modified_rejects_nan_and_unknown_id(user: User) -> None:
    ...
    r = c.add_rect(left=0)
    c._on_modified(_ev(c, {'id': r.id, 'props': {'left': float('nan')}}))
    assert c._objects[r.id]['left'] == 0
    c._on_modified(_ev(c, {'id': 'nope', 'props': {'left': 1}}))   # silently ignored


async def test_path_added_validated(user: User) -> None:
    ...
    c._on_added(_ev(c, {'id': 'p1', 'obj': {'type': 'Path', 'path': [['M', 0, 0]], 'stroke': '#000'}}))
    assert 'p1' in c._objects
    c._on_added(_ev(c, {'id': 'p1', 'obj': {'type': 'Path', 'path': []}}))        # duplicate id → ignored
    c._on_added(_ev(c, {'id': 'p2', 'obj': {'type': 'Image', 'src': 'x'}}))        # wrong type → ignored
    assert 'p2' not in c._objects and c._objects['p1']['stroke'] == '#000'


async def test_text_changed_capped_and_typed(user: User) -> None:
    ...
    t = c.add_text('hi')
    r = c.add_rect()
    c._on_text_changed(_ev(c, {'id': t.id, 'text': 'new'}))
    assert c._objects[t.id]['text'] == 'new'
    c._on_text_changed(_ev(c, {'id': r.id, 'text': 'nope'}))       # not a text type → ignored
    c._on_text_changed(_ev(c, {'id': t.id, 'text': 'x' * 30_000})) # over cap → ignored
    assert c._objects[t.id]['text'] == 'new'


async def test_selection_tracked_and_remove_selected(user: User) -> None:
    ...
    a, b = c.add_rect(), c.add_rect()
    c._on_selection(_ev(c, {'kind': 'created', 'ids': [a.id, 'bogus', b.id]}))
    assert [o.id for o in c.get_selected()] == [a.id, b.id]
    c.remove_selected()
    assert not c._objects and not c.get_selected()
```

- [ ] **Step 2: Run — expect failures**, then implement.

- [ ] **Step 3: Implement validation + handlers in `fabric_canvas.py`**

```python
_GEOMETRY_KEYS = frozenset({'left', 'top', 'scaleX', 'scaleY', 'angle',
                            'skewX', 'skewY', 'flipX', 'flipY', 'width', 'height'})
_TEXT_TYPES = frozenset({'Textbox', 'IText', 'FabricText', 'Text'})
_PATH_KEYS = frozenset({'type', 'id', 'path', 'left', 'top', 'width', 'height',
                        'scaleX', 'scaleY', 'angle', 'fill', 'stroke', 'strokeWidth',
                        'strokeLineCap', 'strokeLineJoin', 'strokeMiterLimit', 'strokeDashArray'})
_MAX_TEXT_LEN = 20_000
_MAX_PATH_BYTES = 256_000


def _clean_geometry(props: Any) -> dict:
    if not isinstance(props, dict):
        return {}
    clean: dict[str, Any] = {}
    for key, value in props.items():
        if key not in _GEOMETRY_KEYS:
            continue
        if key in ('flipX', 'flipY'):
            if isinstance(value, bool):
                clean[key] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            clean[key] = value
    return clean
```

In `__init__` (new kwargs wired; internal handlers registered unconditionally, user handlers additionally):

```python
        self._selected: list[str] = []
        self._props['keyboardDelete'] = keyboard_delete  # camelCase like the other props — no Vue kebab normalization to reason about
        self.on('object-modified', self._on_modified)
        self.on('object-added', self._on_added)
        self.on('text-changed', self._on_text_changed, throttle=0.2)
        self.on('selection', self._on_selection)
        self.on('request-delete', self._on_request_delete)
        for event, handler in [('selection', on_selection), ('object-modified', on_modified),
                               ('object-added', on_added), ('object-error', on_error),
                               ('mouse-down', on_mouse_down), ('mouse-up', on_mouse_up),
                               ('text-changed', on_text_changed)]:
            if handler is not None:
                self.on(event, handler)
```

Handlers (every one no-ops on unknown/invalid input — never raises on hostile payloads):

```python
    def _on_modified(self, e: GenericEventArguments) -> None:
        id_ = e.args.get('id') if isinstance(e.args, dict) else None
        entry = self._objects.get(id_) if isinstance(id_, str) else None
        if entry is not None:
            entry.update(_clean_geometry(e.args.get('props')))

    def _on_added(self, e: GenericEventArguments) -> None:
        if not isinstance(e.args, dict):
            return
        id_, obj = e.args.get('id'), e.args.get('obj')
        if (not isinstance(id_, str) or id_ in self._objects or not isinstance(obj, dict)
                or obj.get('type') != 'Path' or len(json.dumps(obj)) > _MAX_PATH_BYTES):
            return
        self._objects[id_] = {k: v for k, v in obj.items() if k in _PATH_KEYS} | {'id': id_}

    def _on_text_changed(self, e: GenericEventArguments) -> None:
        if not isinstance(e.args, dict):
            return
        id_, text = e.args.get('id'), e.args.get('text')
        entry = self._objects.get(id_) if isinstance(id_, str) else None
        if (entry is not None and entry.get('type') in _TEXT_TYPES
                and isinstance(text, str) and len(text) <= _MAX_TEXT_LEN):
            entry['text'] = text

    def _on_selection(self, e: GenericEventArguments) -> None:
        ids = e.args.get('ids') if isinstance(e.args, dict) else None
        self._selected = [i for i in ids if i in self._objects] if isinstance(ids, list) else []

    def _on_request_delete(self, e: GenericEventArguments) -> None:
        ids = e.args.get('ids') if isinstance(e.args, dict) else []
        for id_ in ids if isinstance(ids, list) else []:
            if isinstance(id_, str) and id_ in self._objects:
                self.remove(id_)

    def get_selected(self) -> list[FabricObject]:
        return [FabricObject(self, i) for i in self._selected if i in self._objects]

    def remove_selected(self) -> None:
        for obj in self.get_selected():
            self.remove(obj)
        self._selected = []

    def discard_selection(self) -> None:
        self._selected = []
        self.run_method('discard_selection')
```

- [ ] **Step 4: Wire events in `fabric_canvas.js`** — add to `mounted()` after canvas creation, plus `props: {..., keyboardDelete: Boolean}`:

```js
    const GEOMETRY_KEYS = ["left", "top", "scaleX", "scaleY", "angle",
                           "skewX", "skewY", "flipX", "flipY", "width", "height"];
    const geometryOf = (o) => Object.fromEntries(GEOMETRY_KEYS.map((k) => [k, o[k]]));
    const c = this.canvas;

    c.on("object:modified", (e) => {
      const t = e.target;
      if (!t || t instanceof fabric.ActiveSelection) return;  // multi-select: synced on deselect below
      if (t.id) this.$emit("object-modified", { id: t.id, props: geometryOf(t) });
    });
    const syncDeselected = (e) => {
      const gone = e.deselected ?? [];
      setTimeout(() => {  // next tick: fabric has restored absolute coords
        for (const o of gone) {
          if (o.id && !o.group) this.$emit("object-modified", { id: o.id, props: geometryOf(o) });
        }
      }, 0);
    };
    const emitSelection = (kind) =>
      this.$emit("selection", { kind, ids: c.getActiveObjects().map((o) => o.id).filter(Boolean) });
    c.on("selection:created", () => emitSelection("created"));
    c.on("selection:updated", (e) => { syncDeselected(e); emitSelection("updated"); });
    c.on("selection:cleared", (e) => { syncDeselected(e); emitSelection("cleared"); });

    c.on("path:created", (e) => {
      e.path.id = crypto.randomUUID().replaceAll("-", "");
      this.$emit("object-added", { id: e.path.id, obj: e.path.toObject(["id"]) });
    });
    c.on("text:changed", (e) => {
      if (e.target?.id) this.$emit("text-changed", { id: e.target.id, text: e.target.text });
    });
    for (const ev of ["mouse:down", "mouse:up"]) {
      c.on(ev, (e) => {
        const p = c.getScenePoint(e.e);
        this.$emit(ev.replace(":", "-"), { x: p.x, y: p.y, id: e.target?.id ?? null });
      });
    }
    if (this.keyboardDelete) {
      c.upperCanvasEl.tabIndex = 0;
      c.upperCanvasEl.addEventListener("keydown", (e) => {
        if (e.key === "Delete" || e.key === "Backspace") {
          this.$emit("request-delete", { ids: c.getActiveObjects().map((o) => o.id).filter(Boolean) });
        }
      });
    }
```

Add JS method: `discard_selection() { this.canvas.discardActiveObject(); this.canvas.requestRenderAll(); }`.

- [ ] **Step 5: Run tests — expect all pass**: `pytest tests/ -v`
- [ ] **Step 6: Commit** — `git commit -am "feat: validated sync-back handlers, selection tracking, keyboard delete"`

---

### Task 5: Serialization — to_dict/to_json/load_json (server-side), exports via HTTP

**Files:**
- Modify: `nicefabric/fabric_canvas.py`, `nicefabric/fabric_canvas.js`, `tests/test_canvas.py`

**Interfaces:**
- Produces: `to_dict() -> dict` (`{'version': '7.4.0', 'objects': [...]}`, deep copy, sync — works pre-init and in tests), `to_json() -> str`, `load_json(data: str | dict) -> None`, `await to_svg(timeout: float = 30) -> str`, `await to_data_url(format='png', quality=1.0, multiplier=1.0, timeout=30) -> str`. Module constants `_MAX_JSON_BYTES = 1_000_000`, `_MAX_OBJECTS = 1000`, `_SUPPORTED_TYPES`.
- HTTP: `POST /_nicefabric/export/{token}` registered once at import on `nicegui.app`; body = export payload; resolves a one-time `asyncio.Future`.

**Design notes:** `to_json` never round-trips to the browser (Python is authoritative; a live client must not be required to snapshot). `to_svg`/`to_data_url` genuinely need rendering → they `await initialized()` first (otherwise pre-init they'd silently return `None`), and the result comes back over HTTP POST because socket messages >1 MB close the websocket (engine.io default cap, unchanged by NiceGUI).

- [ ] **Step 1: Write the failing tests**

```python
async def test_to_dict_roundtrip_without_browser(user: User) -> None:
    ...
    c.add_rect(left=1); c.add_text('hi')
    snapshot = c.to_dict()
    assert len(snapshot['objects']) == 2
    snapshot['objects'][0]['left'] = 99
    assert list(c._objects.values())[0]['left'] == 1   # deep copy — no aliasing


async def test_load_json_validates_and_assigns_fresh_ids(user: User) -> None:
    ...
    c.load_json({'objects': [
        {'type': 'Rect', 'id': 'attacker-chosen', 'left': 5},
        {'type': 'Bogus'},                                        # unknown type → dropped
        {'type': 'Image', 'src': 'javascript:alert(1)'},          # bad scheme → dropped
        {'type': 'Image', 'src': 'https://ok.example/x.png'},
        'not-a-dict',                                             # → dropped
    ]})
    objs = list(c._objects.values())
    assert [o['type'] for o in objs] == ['Rect', 'Image']
    assert all(o['id'] != 'attacker-chosen' and len(o['id']) == 32 for o in objs)


async def test_load_json_caps(user: User) -> None:
    ...
    with pytest.raises(ValueError):
        c.load_json(json.dumps({'objects': []}) + ' ' * 2_000_000)
    with pytest.raises(ValueError):
        c.load_json({'objects': [{'type': 'Rect'}] * 1001})
```

- [ ] **Step 2: Run — expect failures**, then implement.

- [ ] **Step 3: Implement in `fabric_canvas.py`**

```python
import copy
from fastapi import Request
from nicegui import app

_MAX_JSON_BYTES = 1_000_000
_MAX_OBJECTS = 1000
_SUPPORTED_TYPES = frozenset({'Rect', 'Circle', 'Ellipse', 'Line', 'Polygon', 'Polyline',
                              'Path', 'Textbox', 'IText', 'FabricText', 'Image'})
_MAX_EXPORT_BYTES = 64_000_000
_pending_exports: dict[str, asyncio.Future] = {}


@app.post('/_nicefabric/export/{token}')
async def _receive_export(token: str, request: Request) -> dict:
    future = _pending_exports.pop(token, None)
    if future is None or future.done():
        return {'ok': False}
    body = await request.body()
    if len(body) > _MAX_EXPORT_BYTES:
        future.set_exception(ValueError('export exceeds size limit'))
    else:
        future.set_result(body.decode())
    return {'ok': True}
```

Methods:

```python
    def to_dict(self) -> dict:
        return {'version': '7.4.0', 'objects': copy.deepcopy(list(self._objects.values()))}

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def load_json(self, data: str | dict) -> None:
        if isinstance(data, str):
            if len(data) > _MAX_JSON_BYTES:
                raise ValueError(f'payload exceeds {_MAX_JSON_BYTES} bytes')
            data = json.loads(data)
        objects = data.get('objects', []) if isinstance(data, dict) else data
        if len(objects) > _MAX_OBJECTS:
            raise ValueError(f'more than {_MAX_OBJECTS} objects')
        fresh: dict[str, dict] = {}
        for obj in objects:
            if not isinstance(obj, dict) or obj.get('type') not in _SUPPORTED_TYPES:
                continue
            if obj.get('type') == 'Image':
                src = obj.get('src')
                if not isinstance(src, str) or not src.startswith(('https://', 'http://', 'data:image/')):
                    continue
            entry = dict(obj)
            entry['id'] = uuid.uuid4().hex
            fresh[entry['id']] = entry
        self._objects = fresh
        self._selected = []
        self.run_method('sync_objects', list(fresh.values()))

    async def _export(self, method: str, *args: Any, timeout: float) -> str:
        await self.initialized()
        token = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        _pending_exports[token] = future
        try:
            self.run_method(method, token, *args)
            return await asyncio.wait_for(future, timeout)
        finally:
            _pending_exports.pop(token, None)

    async def to_svg(self, timeout: float = 30) -> str:
        return await self._export('export_svg', timeout=timeout)

    async def to_data_url(self, format: str = 'png', quality: float = 1.0,
                          multiplier: float = 1.0, timeout: float = 30) -> str:
        return await self._export('export_data_url',
                                  {'format': format, 'quality': quality, 'multiplier': multiplier},
                                  timeout=timeout)
```

- [ ] **Step 4: JS export methods** (append to `methods`)

```js
    async export_data_url(token, opts) {
      await fetch(window.path_prefix + "/_nicefabric/export/" + token,
                  { method: "POST", body: this.canvas.toDataURL(opts) });
    },
    async export_svg(token) {
      await fetch(window.path_prefix + "/_nicefabric/export/" + token,
                  { method: "POST", body: this.canvas.toSVG() });
    },
```

- [ ] **Step 5: Run tests — expect all pass**: `pytest tests/ -v`
- [ ] **Step 6: Verify the route registers** — `python -c "from nicefabric import FabricCanvas; from nicegui import app; assert any('/_nicefabric/export' in str(r.path) for r in app.routes)"`
  Expected: no output (assertion passes). If route registration at import time misbehaves under `ui.run` reload mode, move registration into `app.on_startup` — decide by testing, not by guessing.
- [ ] **Step 7: Commit** — `git commit -am "feat: server-side serialization, validated load_json, HTTP export channel"`

---

### Task 6: Example app

**Files:**
- Create: `examples/main.py`

**Interfaces:**
- Consumes the full Task 3–5 API exactly as defined above.

- [ ] **Step 1: Write `examples/main.py`**

```python
"""NiceFabric demo — run with: python examples/main.py"""
import base64
import random

from nicegui import app, ui

from nicefabric import FabricCanvas


@ui.page('/')  # per-visit page: module-level canvases would be shared by ALL tabs/users
def index() -> None:
    ui.label('NiceFabric demo').classes('text-2xl')

    with ui.row().classes('items-center gap-2'):
        color = ui.color_input(value='#3b82f6').props('dense')

        def rand_pos() -> dict:
            return {'left': random.randint(0, 500), 'top': random.randint(0, 300)}

        ui.button('Rect', on_click=lambda: canvas.add_rect(
            width=80, height=60, fill=color.value, **rand_pos()))
        ui.button('Circle', on_click=lambda: canvas.add_circle(
            radius=40, fill=color.value, **rand_pos()))
        ui.button('Text', on_click=lambda: canvas.add_text(
            'edit me', fontSize=24, fill=color.value, **rand_pos()))

        draw = ui.switch('draw', on_change=lambda e:
                         canvas.enable_drawing(color.value, 3) if e.value else canvas.disable_drawing())
        ui.button('Delete sel.', on_click=lambda: canvas.remove_selected())
        ui.button('Clear', on_click=lambda: canvas.clear())

        async def export_png() -> None:
            data_url = await canvas.to_data_url()
            ui.download(base64.b64decode(data_url.split(',', 1)[1]), 'canvas.png')
        ui.button('Export PNG', on_click=export_png)

        def save() -> None:
            app.storage.general['nicefabric-demo'] = canvas.to_dict()
            ui.notify('saved')
        def load() -> None:
            if (data := app.storage.general.get('nicefabric-demo')) is not None:
                canvas.load_json(data)
        ui.button('Save', on_click=save)
        ui.button('Load', on_click=load)

    canvas = FabricCanvas(width=800, height=450, background='#f8fafc', keyboard_delete=True,
                          on_selection=lambda e: log.push(f'selection: {e.args}'),
                          on_modified=lambda e: log.push(f'modified: {e.args["id"][:8]}'),
                          on_added=lambda e: log.push(f'drawn: {e.args["id"][:8]}'),
                          on_error=lambda e: log.push(f'ERROR: {e.args}'))
    log = ui.log(max_lines=20).classes('w-full h-40')


if __name__ in {'__main__', '__mp_main__'}:
    ui.run(show=False)
```

- [ ] **Step 2: Manual verify** — `python examples/main.py` and exercise every button with Playwright or a quick screenshot loop; all actions must appear in the log, console clean.
- [ ] **Step 3: Commit** — `git add examples && git commit -m "feat: demo app"`

---

### Task 7: Playwright E2E

**Files:**
- Create: `tests/e2e_playwright.py` (standalone script AND importable as pytest module gated by `-m e2e`)

**Interfaces:**
- Consumes: `examples/main.py` running on port 8080.

- [ ] **Step 1: Write `tests/e2e_playwright.py`** — full script; core assertions:

```python
"""E2E: python tests/e2e_playwright.py  (chromium pre-installed via PLAYWRIGHT_BROWSERS_PATH)"""
import subprocess, sys, time, urllib.request
from playwright.sync_api import sync_playwright

PORT = 8080

def wait_for_server() -> None:
    for _ in range(100):
        try:
            urllib.request.urlopen(f'http://localhost:{PORT}/', timeout=1)
            return
        except Exception:
            time.sleep(0.2)
    raise TimeoutError('server did not start')

def main() -> None:
    server = subprocess.Popen([sys.executable, 'examples/main.py'])
    try:
        wait_for_server()
        with sync_playwright() as p:
            page = p.chromium.launch().new_page()
            errors: list = []
            page.on('pageerror', errors.append)
            page.goto(f'http://localhost:{PORT}/')
            page.wait_for_selector('div.canvas-container')
            box = page.locator('canvas.upper-canvas').bounding_box()
            assert (box['width'], box['height']) == (800, 450), box

            page.get_by_role('button', name='Rect').click()          # Python→JS→render
            page.wait_for_timeout(500)

            # free drawing: toggle draw mode, drag a stroke, expect path:created to
            # round-trip into the Python log (proves the full JS→Python loop)
            page.get_by_text('draw').click()
            page.mouse.move(box['x'] + 300, box['y'] + 300)
            page.mouse.down()
            page.mouse.move(box['x'] + 380, box['y'] + 360, steps=10)
            page.mouse.up()
            page.get_by_text('draw').click()                          # draw mode off again
            page.wait_for_selector('text=drawn:')                     # log line from on_added

            page.get_by_role('button', name='Export PNG').click()     # HTTP export path
            page.wait_for_timeout(1000)

            page.screenshot(path='e2e-screenshot.png')
            assert not errors, errors
    finally:
        server.terminate()

if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Add the multi-select coordinate-sync check to the same file** — it needs known positions and registry access, so it uses its own tiny page, not the demo:

```python
def multi_select_page() -> None:
    """Serve two rects at known positions and expose the registry as JSON."""
    from nicegui import ui
    from nicefabric import FabricCanvas

    @ui.page('/')
    def index() -> None:
        canvas = FabricCanvas(width=600, height=400)
        canvas.add_rect(left=100, top=100, width=50, height=50, fill='red')
        canvas.add_rect(left=300, top=100, width=50, height=50, fill='blue')
        registry = ui.label().classes('registry-dump')
        ui.timer(0.2, lambda: registry.set_text(canvas.to_json()))

    ui.run(show=False, port=8081)


def check_multi_select(p) -> None:
    import json as _json
    page = p.chromium.launch().new_page()
    page.goto('http://localhost:8081/')
    page.wait_for_selector('div.canvas-container')
    box = page.locator('canvas.upper-canvas').bounding_box()

    def rects() -> list[dict]:
        return _json.loads(page.locator('.registry-dump').inner_text())['objects']

    page.mouse.click(box['x'] + 125, box['y'] + 125)                 # select red
    page.keyboard.down('Shift')
    page.mouse.click(box['x'] + 325, box['y'] + 125)                 # add blue → ActiveSelection
    page.keyboard.up('Shift')
    page.mouse.move(box['x'] + 225, box['y'] + 125)                  # grab between them
    page.mouse.down()
    page.mouse.move(box['x'] + 225, box['y'] + 225, steps=10)        # drag both down 100px
    page.mouse.up()
    page.mouse.click(box['x'] + 550, box['y'] + 380)                 # empty corner → deselect
    page.wait_for_timeout(1000)                                      # deselect sync + timer tick

    lefts = sorted(round(r['left']) for r in rects())
    tops = [round(r['top']) for r in rects()]
    assert lefts == [100, 300], f'ABSOLUTE coords expected, got lefts={lefts}'   # unchanged x
    assert all(abs(t - 200) <= 5 for t in tops), f'both moved +100px, got tops={tops}'
```

Run the multi-select server in a second `subprocess.Popen` (same pattern as `main`) and call `check_multi_select` from `main()` after the demo checks.

- [ ] **Step 3: Run** — `pip install playwright && python tests/e2e_playwright.py`
Expected: script exits 0, `e2e-screenshot.png` shows the canvas. If chromium isn't found: `launch(executable_path='/opt/pw-browsers/chromium')`.
- [ ] **Step 4: Commit** — `git add tests/e2e_playwright.py && git commit -m "test: playwright e2e"`

---

### Task 8: README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`** with these sections (each named item is content to write out, not a placeholder to defer):
  1. **Quickstart** — the `@ui.page` example from `examples/main.py` trimmed to ~15 lines, plus a warning box: *module-level canvases are shared by every browser tab and user; always create canvases inside `@ui.page` unless you want collaborative state.*
  2. **API reference table** — every public method/property from Tasks 3–5 with signature and one-line description (source of truth: the docstrings).
  3. **Prop convention** — object props are Fabric-native camelCase (`strokeWidth=`), constructor args are Pythonic; snake_case props trigger a warning; Fabric docs apply directly.
  4. **State model** — Python registry is authoritative; replay covers pre-connect state; browser mutations sync back (geometry, text, drawn paths); raw `run_canvas_method` mutations are ephemeral; persistence recipe via `app.storage` (Save/Load buttons from the demo).
  5. **Awaiting rules** — awaited methods must be awaited immediately (NiceGUI `AwaitableResponse` contract); `to_svg`/`to_data_url` wait for init internally; base `run_method` timeout is 1 s — raise it for heavy calls.
  6. **Limits** — socket messages cap at ~1 MB (why exports use HTTP); `load_json` caps (1 MB / 1000 objects / type & src allow-lists); text 20 k chars; drawn paths 256 KB.
  7. **Security notes** — never feed user input into `:`-prefixed passthrough args (client-side eval); exported SVG contains user-controlled URLs — serve as download (`ui.download` does), never re-inline user SVG into your pages.
  8. **Sizing** — canvas renders at fixed pixel size; CSS classes don't resize the drawing surface; use `resize()`; wrap in `ui.element` with `overflow-auto` for small viewports.
  9. **CDN override** — `from nicegui.dependencies import register_importmap_override; register_importmap_override('nicefabric', '<url>')` (requires nicegui ≥3.6, hence the pin).
  10. **Vendored Fabric.js** — version, license pointer to `nicefabric/lib/VENDORED.md`.
  11. **Extensions / non-goals for v1** — undo/redo (snapshot `to_dict()` on `on_modified`), groups, per-object event handlers, `animate`, responsive scaling, touch gestures beyond Fabric defaults, dark-mode background (one-liner: `canvas.set_background('#1e293b')` bound to `ui.dark_mode`).
- [ ] **Step 2: Verify** — every code snippet in the README must run as pasted (execute each in a scratch file).
- [ ] **Step 3: Commit** — `git add README.md && git commit -m "docs: README"`

---

### Task 9: CI + roadmap + final gate

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `.claude/ROADMAP.md`

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: ci
on: [push, pull_request]
jobs:
  tests:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.10', '3.12']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '${{ matrix.python-version }}'}
      - run: pip install -e '.[dev]'
      - run: pytest tests/test_canvas.py -v
      - run: bash scripts/check_wheel.sh
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.12'}
      - run: pip install -e '.[dev]'
      - run: playwright install --with-deps chromium
      - run: python tests/e2e_playwright.py
      - uses: actions/upload-artifact@v4
        if: failure()
        with: {name: e2e-screenshot, path: e2e-screenshot.png}
```

- [ ] **Step 2: Add feature entry to `.claude/ROADMAP.md`** — `FabricCanvas element (v0.1.0): shapes, free drawing, selection sync, JSON/SVG/PNG export — shipped; v2 candidates: groups, undo/redo helper, per-object events.`
- [ ] **Step 3: Full verification pass** — `pytest tests/ -v && bash scripts/check_wheel.sh && python tests/e2e_playwright.py`; then re-read the original user request and this plan's Global Constraints line by line against the diff (verification-before-completion skill).
- [ ] **Step 4: Commit + push**

```bash
git add .github .claude/ROADMAP.md
git commit -m "ci: workflow, roadmap entry"
git push -u origin claude/fabric-nicegui-integration-temx74
```

---

## Verify-at-implementation-time register (from the red-team audit — check these against reality when you reach them, do not trust this document)

| Claim | Where verified |
|---|---|
| `enlivenObjects` round-trips `toObject()` type casing | Task 2 Step 7 smoke |
| `deselected` members regain absolute coords next tick | Task 7 multi-select E2E |
| `path:created` payload shape / `toObject(['id'])` | Task 7 drawing E2E |
| Route registration at import vs `app.on_startup` | Task 5 Step 6 |
| `crypto.randomUUID` available (secure context/localhost only) | Task 7; fallback: `Math.random`-based id |
| `getScenePoint(e.e)` signature | Task 7 console-clean assertion |
