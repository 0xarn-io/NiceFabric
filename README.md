# NiceFabric

[Fabric.js](https://fabricjs.com/) 7.4.0 as a [NiceGUI](https://nicegui.io/) element: an
interactive canvas you drive from Python. Add shapes, text, images and free-hand drawing;
users drag, scale, rotate and edit them in the browser; the changes come back to Python.

Fabric.js is vendored — no CDN, no network access needed at runtime.

## Install

Not on PyPI yet — install from a clone:

```bash
git clone https://github.com/0xarn-io/NiceFabric.git
cd NiceFabric
pip install .
```

`nicegui >= 3.6, < 4` is the only dependency; Python ≥ 3.10. The wheel bundles the Fabric.js
build (`nicefabric/lib/nicefabric.min.mjs`), so nothing is fetched at runtime.

## Quickstart

```python
from nicegui import ui

from nicefabric import FabricCanvas


@ui.page('/')  # per-visit page: a module-level canvas would be shared by ALL tabs and users
def index() -> None:
    canvas = FabricCanvas(width=800, height=450, background='#f8fafc', keyboard_delete=True,
                          on_modified=lambda e: ui.notify(f'moved {e.args["id"][:8]}'))
    canvas.add_rect(left=200, top=150, width=120, height=80, fill='#3b82f6')
    canvas.add_text('drag me', left=400, top=150, fontSize=24)

    with ui.row():
        ui.button('Circle', on_click=lambda: canvas.add_circle(
            left=400, top=300, radius=40, fill='#ef4444'))
        ui.switch('draw', on_change=lambda e:
                  canvas.enable_drawing('#ef4444', 3) if e.value else canvas.disable_drawing())
        ui.button('Clear', on_click=canvas.clear_objects)   # NOT canvas.clear() — see below


ui.run()
```

Save as `app.py`, then run `python app.py`.

A fuller demo — colour picker, delete-selected, PNG export, save/load — is in
[`examples/main.py`](examples/main.py): `python examples/main.py`.

> **Create canvases inside `@ui.page`.** A canvas built at module level is *one Python object
> shared by every browser tab and every user*: everyone sees everyone else's shapes and
> selections. That is occasionally what you want (a shared whiteboard); it is almost never what
> you meant. Inside `@ui.page`, each visit gets its own canvas.

## Three things that trip everyone up

### 1. `clear()` is not `clear_objects()`

`FabricCanvas` inherits from `nicegui.Element`, which already defines `update()`, `remove()` and
`clear()`. Those keep their NiceGUI meaning — they operate on **child elements**, not on canvas
objects. The Fabric-native operations have `_object` names:

| You want to…                  | Call                            | Do **not** call — it means something else |
| ----------------------------- | ------------------------------- | ----------------------------------------- |
| remove every canvas object    | `canvas.clear_objects()`        | `canvas.clear()` — removes child elements |
| remove one canvas object      | `canvas.remove_object(obj)`     | `canvas.remove(element)` — removes a child |
| set props on a canvas object  | `canvas.update_object(obj, ...)`| `canvas.update()` — re-sends element props |

```python
canvas.clear()          # ✗ no error, no exception — it just did not touch the canvas
canvas.clear_objects()  # ✓
```

`canvas.clear()` and `canvas.update()` fail **silently**: no `AttributeError`, no warning, just
the wrong thing happening quietly. (`canvas.remove(fabric_object)` at least raises.) If your
"clear" button appears to do nothing, this is why.

### 2. Fabric 7 positions objects from their CENTRE

`left` and `top` are the object's **centre**, not its top-left corner. `left=0, top=0` puts three
quarters of a shape off-canvas. To place a 120×80 rect flush in the top-left corner of the canvas:

```python
canvas.add_rect(left=60, top=40, width=120, height=80, fill='#3b82f6')
```

This changed in Fabric 6 and surprises everyone arriving from Fabric 5.

### 3. Awaited calls must be awaited immediately

`await canvas.run_canvas_method('getZoom')` is fine; assigning the call to a variable and
awaiting it works only until something else awaits first — once it does, the delayed `await`
raises `RuntimeError`. And an awaited call can overtake a fire-and-forget call issued just before
it. See [Awaiting rules](#awaiting-rules).

## API reference

### `FabricCanvas(...)`

```python
canvas = FabricCanvas(
    width=800, height=600,
    background='#ffffff', selection=True, keyboard_delete=False,
    on_selection=None, on_modified=None, on_added=None, on_error=None,
    on_mouse_down=None, on_mouse_up=None, on_text_changed=None,
)
```

Everything after `height` is keyword-only.

`selection=False` disables Fabric's own selection handling. `keyboard_delete=True` makes
<kbd>Delete</kbd>/<kbd>Backspace</kbd> delete the selection (routed through Python, so the
registry stays correct) once the canvas has focus.

### Adding objects

Every `add_*` returns a `FabricObject` handle. `**props` are Fabric-native camelCase props.

| Method                                        | Creates                                                |
| --------------------------------------------- | ------------------------------------------------------ |
| `add_rect(**props)`                            | `Rect`                                                 |
| `add_circle(**props)`                          | `Circle` (use `radius=`)                               |
| `add_ellipse(**props)`                         | `Ellipse` (use `rx=`, `ry=`)                           |
| `add_line(x1, y1, x2, y2, **props)`            | `Line`                                                 |
| `add_polygon(points, **props)`                 | `Polygon`; `points` is `[{'x': …, 'y': …}, …]`         |
| `add_polyline(points, **props)`                | `Polyline`                                             |
| `add_path(path, **props)`                      | `Path`; `path` is SVG path data                        |
| `add_text(text, **props)`                      | `Textbox` — editable, word-wrapping, `width` defaults to 200 |
| `add_image(url, **props)`                      | `Image`; `crossOrigin` defaults to `'anonymous'`       |
| `add_object(type_, **props)`                   | any Fabric type by name, e.g. `add_object('IText', text='hi')` |

`await add_svg(svg, timeout=30)` imports a whole SVG document and also returns handles, but it
is a coroutine with different rules — see [Importing SVG](#importing-svg-async).

### Importing SVG (async)

| Method                                       | Notes                                                             |
| -------------------------------------------- | ----------------------------------------------------------------- |
| `await add_svg(svg, timeout=30) -> list[FabricObject]` | parses `svg` in the browser and appends the shapes    |
| `last_svg_size: tuple[float, float] \| None`  | dimensions of the last parsed document, `None` if it declared none |

**It needs a connected client.** Fabric's SVG parser runs on the browser's `DOMParser`, so this
is a round trip: put it in a button handler or an `on_connect` callback, never in a page-builder
body — there is no browser there yet, and the call can only run out its `timeout` (which bounds
the *whole* call, the wait for a client included). Every other `add_*` is fire-and-forget and
has no such requirement.

```python
async def import_drawing() -> None:
    try:
        objects = await canvas.add_svg(Path('logo.svg').read_text())
    except (ValueError, RuntimeError, asyncio.TimeoutError) as e:
        ui.notify(f'import failed: {e}', type='negative')
        return
    ui.notify(f'imported {len(objects)} shapes at {canvas.last_svg_size}')


ui.button('Import SVG', on_click=import_drawing)
```

**The result is flat: `<g>` structure is not preserved.** Fabric's parser bakes each element's
accumulated parent transforms into absolute `left`/`top`/`scaleX`/`angle`/… values and discards
the groups themselves — so a `<g transform="translate(100, 40)">` moves its children rather than
surviving as an object. What you get back is ordinary shapes (`Path`, `Rect`, `Circle`, …) that
are indistinguishable from ones you added by hand: they replay on reconnect, survive
`to_dict()` → `load_json()`, and are individually selectable and editable.

**Import is at native size.** The canvas is not resized and nothing is scaled to fit — both
would be lossy surprises. `last_svg_size` holds the parsed document's dimensions, so you can do
either yourself:

```python
objects = await canvas.add_svg(source)
if canvas.last_svg_size:
    width, height = canvas.last_svg_size
    canvas.resize(round(width), round(height))                  # fit the canvas to the document
    # ...or fit the document to the canvas:
    # scale = min(800 / width, 450 / height)
    # for obj in objects:
    #     p = obj.props
    #     obj.update(left=p['left'] * scale, top=p['top'] * scale,
    #                scaleX=p.get('scaleX', 1) * scale, scaleY=p.get('scaleY', 1) * scale)
```

Failure modes, all of which leave the registry untouched:

| Situation                                              | Result                                       |
| ------------------------------------------------------ | -------------------------------------------- |
| source over 1 MB, or more shapes than the canvas cap    | `ValueError` (nothing is sent or registered) |
| a document the browser's XML parser rejects             | `[]` — indistinguishable from an empty document at Fabric's boundary |
| an `<image>` the browser cannot load                    | `RuntimeError`: Fabric 7.4.0 fails the *whole* parse, not just that element |
| no client connects within `timeout`                     | `asyncio.TimeoutError`                       |

Parsed shapes are treated as untrusted, exactly like a `load_json` payload: allow-listed types,
the image `src` scheme allow-list at every nesting level, and freshly generated ids.

### Mutating objects

| Method                                   | Notes                                                       |
| ---------------------------------------- | ----------------------------------------------------------- |
| `update_object(obj_or_id, **props)`      | raises `KeyError` if the object is no longer in the registry |
| `remove_object(obj_or_id)`               | raises `KeyError`                                            |
| `clear_objects()`                        | removes every canvas object                                  |
| `bring_to_front(obj_or_id)`              | raises `KeyError`                                            |
| `send_to_back(obj_or_id)`                | raises `KeyError`                                            |

`obj_or_id` accepts a `FabricObject` or its `id` string.

### Selection

| Method                  | Returns / does                                     |
| ----------------------- | -------------------------------------------------- |
| `get_selected()`        | `list[FabricObject]` currently selected in the browser |
| `remove_selected()`     | deletes every selected object                       |
| `discard_selection()`   | clears the selection                                |

### Canvas-wide

| Method                                   | Notes                                              |
| ---------------------------------------- | -------------------------------------------------- |
| `set_background(color)`                  | CSS colour string                                   |
| `set_zoom(zoom)`                         | `1.0` is 100 %                                      |
| `absolute_pan(x, y)`                     | absolute viewport pan                               |
| `resize(width, height)`                  | the only way to change the drawing surface size     |
| `enable_drawing(color='#000000', width=2)` | free-hand pencil brush                            |
| `disable_drawing()`                      |                                                     |
| `draw_mode`                              | read-only `bool` property                           |

### Serialization

| Method                     | Notes                                                                |
| -------------------------- | -------------------------------------------------------------------- |
| `to_dict() -> dict`        | deep copy of the server-side registry; no browser round-trip, works before the page connects and in tests |
| `to_json() -> str`         | `json.dumps(to_dict())`                                              |
| `load_json(data: str \| dict)` | replaces every object; validates and re-ids; raises `ValueError` — see [Limits](#limits) |

### Export (async)

| Method                                                              | Notes                                    |
| ------------------------------------------------------------------- | ---------------------------------------- |
| `await to_svg(timeout=30) -> str`                                    | SVG source rendered by the browser        |
| `await to_data_url(format='png', quality=1.0, multiplier=1.0, timeout=30) -> str` | e.g. `data:image/png;base64,…` |

Both wait for the canvas to initialize, then ask the browser to render. A browser-side failure
(typically a canvas tainted by a cross-origin image) raises `RuntimeError` promptly instead of
hanging until `timeout`.

`timeout` bounds the **whole** call, including that wait for initialization — so an export fired
from a background task after the tab closed (or from a test with no browser at all) raises
`asyncio.TimeoutError` rather than waiting forever for a client that will never connect.

### Lifecycle and escape hatches

| Member                                              | Notes                                                        |
| ---------------------------------------------------- | ------------------------------------------------------------ |
| `is_initialized: bool`                               | `True` once the browser-side canvas exists                    |
| `await initialized()`                                | waits for the client connection and the init handshake        |
| `run_canvas_method(name, *args, timeout=1)`          | call any `fabric.Canvas` method — see [Security](#security-notes) |
| `run_object_method(obj_or_id, name, *args, timeout=1)` | call any Fabric object method                              |

Both return NiceGUI's `AwaitableResponse`: ignore it to fire-and-forget, or `await` it
immediately for the return value. Before the canvas is initialized, `run_method` hands back a
`NullResponse` instead of sending anything — the call is silently **dropped and lost**, not
queued. The registry replay described in [State model](#state-model) does *not* cover it: replay
only re-sends `self._objects` and `self._canvas_state`, which is what the typed methods
(`add_*`, `set_zoom`, …) write to, but `run_canvas_method`/`run_object_method` never touch either
one. Awaiting the `NullResponse` yields `None`.

`run_object_method` and `FabricObject.run_method` also differ from the typed mutators in another
way: they resolve the target by id in JavaScript and simply return `undefined` if it is not
found, so an unknown id is a **silent no-op**, not the `KeyError` that `update_object`,
`remove_object` and friends raise (see [Mutating objects](#mutating-objects)).

### `FabricObject`

Returned by every `add_*` and by `get_selected()`.

| Member                                    | Notes                                             |
| ----------------------------------------- | ------------------------------------------------- |
| `.id`                                     | the registry key (a hex string)                    |
| `.type`                                   | e.g. `'Rect'`                                      |
| `.props`                                  | a copy of the object's current registry entry      |
| `.update(**props)`                        | → `canvas.update_object` (not shadowed — safe here) |
| `.delete()`                               | → `canvas.remove_object`                            |
| `.bring_to_front()` / `.send_to_back()`   |                                                     |
| `.run_method(name, *args, timeout=1)`     | → `canvas.run_object_method`                        |

### Events

Handlers take one `GenericEventArguments`; the payload is in `e.args`.

| Constructor argument | Fires when                                     | `e.args`                                            |
| -------------------- | ---------------------------------------------- | --------------------------------------------------- |
| `on_selection`       | the selection changes                          | `{'kind': 'created' \| 'updated' \| 'cleared', 'ids': [...]}` |
| `on_modified`        | an object is dragged, scaled or rotated        | `{'id': ..., 'props': {geometry}}`                   |
| `on_added`           | **a free-hand stroke is finished**             | `{'id': ..., 'obj': {...}}`                          |
| `on_text_changed`    | text is edited on the canvas                   | `{'id': ..., 'text': ...}`                           |
| `on_mouse_down` / `on_mouse_up` | the pointer is pressed / released  | `{'x': ..., 'y': ..., 'id': id or None}` (scene coords) |
| `on_error`           | an object fails to revive in the browser       | `{'id': ..., 'message': ...}`                        |

**`on_added` fires only for free-drawn paths**, never for your own `add_rect`/`add_text`/… calls —
otherwise every programmatic add would echo back at you.

The registry's own text sync is throttled to 5 updates per second; your `on_text_changed` handler
is not, so it sees every keystroke event the browser sends. `on_mouse_down`/`on_mouse_up` are
unthrottled too — each one fires on every pointer press/release, so a handler doing real work
should debounce or throttle itself.

## Prop convention

Constructor arguments are Pythonic (`keyboard_delete=`, `on_modified=`). **Object props are
Fabric-native camelCase** and are passed straight through, so
[the Fabric docs](http://fabricjs.com/api/) apply verbatim:

```python
canvas.add_rect(left=100, top=100, width=120, height=80,
                fill='#3b82f6', stroke='#1e40af', strokeWidth=4, rx=8, angle=15)
canvas.add_text('hello', left=300, top=100, fontSize=28, fontFamily='monospace',
                textAlign='center', fill='#111827')
```

A prop name containing `_` is almost certainly a mistake, so it emits a `UserWarning` naming the
camelCase spelling it thinks you meant (`stroke_width` → `strokeWidth`). The prop is still sent;
Fabric simply stores it as an unknown property and draws nothing differently.

## State model

The **Python registry is authoritative.** `add_*`, `update_object`, `load_json`, `set_zoom` and
friends record the change server-side first, then message the browser.

- **Replay.** Anything you do before the websocket connects is buffered and replayed on `init` —
  building a whole canvas at page-construction time works, no `await initialized()` needed.
- **Sync-back.** Browser-side changes flow into the registry: geometry from drag/scale/rotate,
  edited text, and free-drawn paths. Every payload is re-validated server-side.
- **`run_canvas_method` / `run_object_method` mutations are ephemeral.** They talk to the browser
  directly and never enter the registry, so they are absent from `to_dict()` and are *not*
  replayed. Prefer the typed methods for anything that must survive.
- **State does not survive a page reload.** NiceGUI builds fresh elements per page visit; replay
  only covers the gap before the socket connects. Persistence is your app's job:

```python
from nicegui import app, ui

from nicefabric import FabricCanvas


@ui.page('/')
def index() -> None:
    canvas = FabricCanvas(width=800, height=450)

    def save() -> None:
        app.storage.general['canvas'] = canvas.to_dict()
        ui.notify('saved')

    def load() -> None:
        data = app.storage.general.get('canvas')
        if data is None:
            ui.notify('nothing saved yet')
            return
        try:
            canvas.load_json(data)
        except ValueError as e:
            ui.notify(f'load failed: {e}', type='negative')

    ui.button('Save', on_click=save)
    ui.button('Load', on_click=load)


ui.run()
```

Use `app.storage.user` for per-user state, `app.storage.general` for shared state, or write the
`to_json()` string to a file or database.

## Awaiting rules

`run_canvas_method`, `run_object_method` and `FabricObject.run_method` return NiceGUI's
`AwaitableResponse`. **It must be awaited immediately after creation, or not at all.** "Immediately"
is a statement about the event loop, not about which source line the `await` sits on: stashing the
response in a variable and awaiting it on the very next line, with nothing else awaited in
between, works — the fire-and-forget path hasn't had a chance to run yet. The moment *any* real
`await` happens first — even `asyncio.sleep(0)` — the fire-and-forget path wins the race, and the
delayed `await` then raises
`RuntimeError: AwaitableResponse must be awaited immediately after creation or not at all`. That
makes the anti-pattern worse than an outright bug: it works right up until something else in the
same function starts awaiting things, then breaks.

```python
async def measure() -> None:
    zoom = await canvas.run_canvas_method('getZoom')          # ✓ awaited immediately
    ui.notify(f'zoom is {zoom}')

    pending = canvas.run_canvas_method('getZoom')             # ✗ don't do this...
    zoom = await pending                                      #   ...but this line alone works
    ui.notify(f'zoom is {zoom} (works only because nothing awaited first)')

    pending = canvas.run_canvas_method('getZoom')
    await asyncio.sleep(0)                                    # any intervening await tips it over
    try:
        await pending                                         # -> RuntimeError, now that it's late
    except RuntimeError as e:
        ui.notify(f'as documented: {e}', type='negative')
```

The default `timeout` is **1 second**. Raise it for anything slow:

```python
async def dump() -> None:
    data = await canvas.run_canvas_method('toDatalessJSON', timeout=10)
    ui.notify(f'{len(data["objects"])} objects')
```

### An awaited call can overtake the fire-and-forget call in front of it

A response you *don't* await is dispatched from a background task, so its message is queued on
the next event-loop iteration. A response you *do* await is queued straight away — and therefore
arrives at the browser **first**:

```python
async def broken() -> None:
    canvas.run_canvas_method('setZoom', 2)                    # queued on the next loop iteration
    zoom = await canvas.run_canvas_method('getZoom')          # queued now — overtakes it
    ui.notify(f'zoom is {zoom}')                              # -> 'zoom is 1'
```

Await the mutation too (or `await asyncio.sleep(0)` between them):

```python
async def fixed() -> None:
    await canvas.run_canvas_method('setZoom', 2)
    zoom = await canvas.run_canvas_method('getZoom')
    ui.notify(f'zoom is {zoom}')                              # -> 'zoom is 2'
```

This only bites when you mix the two styles. Consecutive fire-and-forget calls — which is what
every typed method (`add_rect`, `set_zoom`, `update_object`, …) issues — keep their order, both in
flight and in the browser-side queue that applies them.

`to_svg()`, `to_data_url()` and `add_svg()` are ordinary coroutines with their own 30 s default
timeout, and they wait for canvas initialization internally — no `await initialized()` needed
first. They are also the only calls that *require* a browser: everything else works without one.

## Limits

Every limit exists because something breaks without it.

| What                          | Cap                                                                                       | On breach                    |
| ----------------------------- | ----------------------------------------------------------------------------------------- | ---------------------------- |
| `load_json` payload           | 1 MB (UTF-8 bytes, `dict` and `str` alike)                                                 | `ValueError`, canvas untouched |
| `load_json` object count      | 1000                                                                                       | `ValueError`, canvas untouched |
| `add_svg` source              | 1 MB (UTF-8 bytes), checked before anything is sent to the browser                          | `ValueError`, nothing is sent |
| `add_svg` shape count         | the same 1000-object registry cap, counting what is already on the canvas                   | `ValueError`, canvas untouched |
| `load_json` object types      | `Rect Circle Ellipse Line Polygon Polyline Path Textbox IText Text Image`                   | object dropped silently       |
| `load_json` image `src`       | `https://`, `http://`, `data:image/` — at every nesting level (e.g. a `clipPath` image)     | object dropped silently       |
| text sync-back                | 20 000 characters                                                                          | the edit is not recorded      |
| free-drawn path sync-back     | 256 000 JSON *characters* (`len(json.dumps(obj))`, not bytes)                              | the path is not registered    |
| export upload                 | 64 MB                                                                                      | `ValueError`                  |
| websocket message             | ~1 MB (engine.io's default)                                                                | connection closes             |

`load_json` treats its input as untrusted — it typically comes from a file or an upload — and
gives every object a freshly generated id, so a payload cannot choose or collide with registry
keys. Objects are stored as deep copies, so the registry never aliases the payload you passed in.

The type names above are Fabric's own registered names — the ones its `toJSON` writes and its
`enlivenObjects` looks up. Plain text is `Text`, **not** `FabricText` (that is the class name and
is not registered); `add_text()` produces `Textbox`.

**The asymmetry is real:** `to_dict()` and `to_json()` are *uncapped*. A canvas full of free-drawn
paths can be saved and then refused on load. Always catch `ValueError` around `load_json`, as the
recipe above does.

The ~1 MB websocket cap is also why exports do not come back over the socket: `to_svg()` and
`to_data_url()` have the browser POST the rendered result to a one-time-token HTTP endpoint
instead. Many real exports exceed 1 MB, and an oversized socket message would close the
connection outright — but it doesn't matter either way, since exports always go over HTTP
regardless of size.

## Security notes

**Never interpolate user input into a `:`-prefixed passthrough call.** Prefixing the method name
with `:` makes every *argument* be evaluated as JavaScript source (`new Function`) in the browser
of every viewer of that page:

```python
canvas.run_canvas_method(':setZoom', '1 + 1')                 # ok — you wrote the string
canvas.run_canvas_method(':setZoom', user_input)              # ✗ remote code execution
canvas.run_canvas_method('setZoom', float(user_input))        # ✓ plain JSON argument
```

Without the `:`, arguments are JSON-serialized and never evaluated — that is the default and the
right choice for anything data-driven.

**Treat exported SVG as untrusted.** It embeds user-controlled URLs (image `src`, font
references) and, being a full XML document, is a script-execution vector when rendered as a page.
Serve it as a *download* — which is what `ui.download` does — and never re-inline it into your own
HTML:

```python
async def download_svg() -> None:
    svg = await canvas.to_svg()
    ui.download(svg.encode(), 'canvas.svg')       # ✓ a download, not an inlined page

ui.button('Export SVG', on_click=download_svg)
```

Method *names* are validated (`^[A-Za-z_$][\w$.]*$` after any `:` prefix) and a hostile one
raises `ValueError` before anything reaches the browser — but that only stops name injection,
not the `:`-argument evaluation above.

Object props are passed through to Fabric untouched. If they come from users, validate them —
particularly image `src` (`load_json` already restricts it, `add_image` does not).

**Exports add a public, unauthenticated route.** `to_svg()`/`to_data_url()` register
`POST /_nicefabric/export/{token}` so the browser can hand back the rendered result over HTTP
instead of the websocket (see [Limits](#limits)). That route accepts requests from anyone, not
just your page's own session — by design, since the browser POST carries no NiceGUI auth context.
It's still narrow: `token` is a single-use 122-bit `uuid4`, popped from the pending-exports table
before the body is even read, so a replayed, guessed or late token gets `{"ok": false}` without
being processed further, and the body itself is read as a size-capped stream (see `export upload`
in [Limits](#limits)) so an oversized POST is abandoned mid-flight rather than buffered.

## Sizing

The canvas renders at a **fixed pixel size** set by `width`/`height`. CSS does not resize the
drawing surface: `.classes('w-full')` stretches the wrapper `<div>` while the canvas keeps
drawing at its original resolution, so the two disagree and hit-testing goes wrong. Use
`resize()`:

```python
canvas = FabricCanvas(width=800, height=600)
ui.button('Bigger', on_click=lambda: canvas.resize(1200, 900))
```

For a large canvas on a small viewport, scroll it rather than scale it:

```python
with ui.element().classes('overflow-auto max-w-full border'):
    canvas = FabricCanvas(width=1600, height=1200)
```

`set_zoom()` scales the *content*; the surface stays the same size.

## CDN override

To load Fabric.js from a CDN instead of the vendored bundle, override the import map before the
page is built:

```python
from nicegui.dependencies import register_importmap_override

register_importmap_override('nicefabric', 'https://cdn.jsdelivr.net/npm/fabric@7.4.0/+esm')
```

The import name is `nicefabric`, not `fabric` — see
[`nicefabric/lib/VENDORED.md`](nicefabric/lib/VENDORED.md) for why. `register_importmap_override`
is what pins the dependency to `nicegui >= 3.6`.

## Vendored Fabric.js

`nicefabric/lib/nicefabric.min.mjs` is the unmodified prebuilt browser bundle of **fabric 7.4.0**
(only the trailing `sourceMappingURL` comment removed), MIT licensed. Source URL, sha256, the
reason for the filename, and the upstream licence notice are in
[`nicefabric/lib/VENDORED.md`](nicefabric/lib/VENDORED.md). NiceFabric itself is MIT licensed —
see [`LICENSE`](LICENSE).

## Extensions and non-goals

Not built in for v1, but reachable from what is:

- **Undo/redo** — snapshot `to_dict()` on `on_modified` (and after each of your own mutations),
  push onto a stack, `load_json()` to restore.
- **Dark-mode background** — bind `set_background` to `ui.dark_mode`:

  ```python
  dark = ui.dark_mode(on_change=lambda e: canvas.set_background('#1e293b' if e.value else '#ffffff'))
  ui.switch('dark mode', on_change=lambda e: dark.set_value(e.value))
  ```

- **Groups** — no Python-side API. `run_canvas_method` reaches Fabric's grouping directly, but the
  result is ephemeral (see [State model](#state-model)) and grouped objects will not round-trip
  through `to_dict()`.
- **Per-object event handlers** — events are canvas-wide; dispatch on `e.args['id']` yourself.
- **`animate`** — reachable via `run_object_method`, ephemeral for the same reason.
- **Responsive scaling** — see [Sizing](#sizing); wrap and scroll, or call `resize()` yourself.
- **Touch gestures** — whatever Fabric provides by default, nothing added.
