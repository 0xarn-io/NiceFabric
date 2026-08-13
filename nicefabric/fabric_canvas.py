from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import re
import uuid
import warnings
from typing import Any

from fastapi import Request
from nicegui import app
from nicegui.awaitable_response import AwaitableResponse, NullResponse
from nicegui.element import Element
from nicegui.events import GenericEventArguments, Handler

logger = logging.getLogger(__name__)

_METHOD_NAME = re.compile(r'^[A-Za-z_$][\w$.]*$')

_GEOMETRY_KEYS = frozenset({'left', 'top', 'scaleX', 'scaleY', 'angle',
                             'skewX', 'skewY', 'flipX', 'flipY', 'width', 'height'})
_TEXT_TYPES = frozenset({'Textbox', 'IText', 'Text'})
_PATH_KEYS = frozenset({'type', 'id', 'path', 'left', 'top', 'width', 'height',
                         'scaleX', 'scaleY', 'angle', 'fill', 'stroke', 'strokeWidth',
                         'strokeLineCap', 'strokeLineJoin', 'strokeMiterLimit', 'strokeDashArray'})
_MAX_TEXT_LEN = 20_000
_MAX_PATH_BYTES = 256_000

_MAX_JSON_BYTES = 1_000_000
_MAX_OBJECTS = 1000
_SUPPORTED_TYPES = frozenset({'Rect', 'Circle', 'Ellipse', 'Line', 'Polygon', 'Polyline',
                              'Path', 'Textbox', 'IText', 'Text', 'Image'})
"""Types ``load_json`` will accept.

Every name here must be a key in Fabric 7.4.0's ``classRegistry`` — that is what
``enlivenObjects`` looks up in the browser, and a name that is not a key throws there instead of
being caught by this allow-list. ``'Text'`` is the registered name for plain (non-editable) text
and is what Fabric's own ``toJSON`` writes; ``'FabricText'`` is the *class* name and is **not**
registered, so it must never appear here (see ``tests/test_canvas.py`` for the gate).
"""
_IMAGE_SRC_SCHEMES = ('https://', 'http://', 'data:image/')
_MAX_EXPORT_BYTES = 64_000_000
_MAX_SVG_RESULT_BYTES = 20_000_000
"""Cap on the browser's ``import_svg`` answer, enforced before ``json.loads``/``deepcopy``.

Deliberately not ``_MAX_JSON_BYTES``: Fabric's SVG parser does not preserve source size, it
expands it. A path's ``d`` attribute becomes an array of numbers, and the worst offender is the
arc command — one ``A`` command (rx ry rot large-arc sweep x y, ~30 bytes) can lower to several
cubic Bézier curves, each six JSON numbers wide. Measured against the vendored 7.4.0 bundle with
legitimate, spec-valid documents at the ``_MAX_JSON_BYTES`` source boundary (dense polylines,
hundreds of small shapes, arc-heavy paths), the worst observed blow-up was ~18x source size — a
1 MB document producing an ~18 MB result. 20 MB leaves headroom above that measurement while
staying well under ``_MAX_EXPORT_BYTES``, so a hostile 64 MB browser POST is still rejected by
this check long before ``json.loads`` or the per-object ``deepcopy`` in ``_clean_objects`` ever
see it — closing the gap that made the object-count cap (``_MAX_OBJECTS``) alone insufficient:
that cap bounds how many objects land in the registry, not how many bytes the JSON blob those
objects came from cost to parse and copy.
"""
_EXPORT_PATH = '/_nicefabric/export/{token}'

_pending_exports: dict[str, asyncio.Future] = {}
"""Exports awaiting their browser POST, keyed by one-time token.

Process-wide (the route is registered once) but bounded: only ``_export`` adds entries and it
always removes its own token in a ``finally``, so a client that never POSTs leaks nothing.
"""


@app.post(_EXPORT_PATH)
async def _receive_export(token: str, request: Request) -> dict:
    """Receive one rendered export from the browser and resolve the call waiting for it.

    A public unauthenticated route, so every failure mode is a normal outcome: an unknown,
    replayed or already-timed-out token is dropped without reading the body, and an oversized
    body is refused before it is retained. The token is the only credential — 122 bits of
    ``uuid4``, valid once, for at most one ``timeout`` window.

    A ``?error=1`` query string marks a browser-side export failure (e.g. ``toDataURL`` throwing
    on a tainted canvas — see ``add_image``/``load_json``'s ``crossOrigin`` defaults): the body is
    then the error message, delivered to the caller as a ``RuntimeError`` instead of a result, so
    a broken export fails fast instead of running out the clock on ``timeout``.
    """
    future = _pending_exports.pop(token, None)
    if future is None or future.done():
        return {'ok': False}
    body = await _read_capped(request)
    if future.done():           # the caller timed out while the body was arriving
        return {'ok': False}
    if body is None:
        future.set_exception(ValueError(f'export exceeds {_MAX_EXPORT_BYTES} bytes'))
        return {'ok': False}
    try:
        text = body.decode()
    except UnicodeDecodeError:
        future.set_exception(ValueError('export payload is not valid UTF-8'))
        return {'ok': False}
    if request.query_params.get('error'):
        logger.warning('nicefabric: export failed in the browser: %s', text)
        future.set_exception(RuntimeError(f'browser-side export failed: {text}'))
        return {'ok': True}
    future.set_result(text)
    return {'ok': True}


def _ensure_export_route() -> None:
    """Re-add the export route if something removed it after import.

    Registering once at import is enough for a normally-running app, but NiceGUI's own test
    fixtures (``nicegui_reset_globals``, behind both ``user`` and ``screen``) delete every route
    outside ``/_nicegui/`` between tests — without this, an app under test would POST its
    exports at a 404 and every export would hang until its timeout.
    """
    if not any(getattr(route, 'path', None) == _EXPORT_PATH for route in app.routes):
        app.post(_EXPORT_PATH)(_receive_export)


async def _read_capped(request: Request) -> bytes | None:
    """Read the request body, or return ``None`` if it exceeds ``_MAX_EXPORT_BYTES``.

    Streamed rather than ``await request.body()`` so an oversized upload is abandoned mid-flight
    instead of being buffered in full and measured afterwards.
    """
    declared = request.headers.get('content-length')
    if declared is not None and declared.isdigit() and int(declared) > _MAX_EXPORT_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _MAX_EXPORT_BYTES:
            return None
        chunks.append(chunk)
    return b''.join(chunks)


def _valid_image_src(src: Any) -> bool:
    """The one place an ``Image`` source is judged — used at every nesting level."""
    return isinstance(src, str) and src.startswith(_IMAGE_SRC_SCHEMES)


def _clean_nested_images(entry: dict) -> bool:
    """Apply the ``Image`` rules to every dict nested inside one ``load_json`` object.

    An object's ``clipPath`` (or any other nested descriptor) may itself be an ``Image``, and
    Fabric revives it exactly like a top-level one — so an unchecked nested ``src`` would be the
    single hole in the scheme allow-list. Nested images that pass also get ``add_image``'s
    ``crossOrigin`` default, since a nested cross-origin image taints the canvas just as
    thoroughly as a top-level one.

    :return: ``False`` if any nested ``Image`` has a disallowed ``src``, in which case the caller
        drops the whole top-level object — the same outcome as a bad top-level ``src``.

    Iterative rather than recursive so a deeply nested payload cannot exhaust the stack here
    (``load_json`` has already converted the equivalent failure into ``ValueError`` upstream).
    ``entry`` must be a private deep copy: this mutates nested dicts in place.
    """
    stack: list[Any] = [*entry.values()]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if node.get('type') == 'Image':
                if not _valid_image_src(node.get('src')):
                    return False
                node.setdefault('crossOrigin', 'anonymous')
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return True


def _clean_object(obj: Any) -> dict | None:
    """Validate one untrusted object descriptor into a private, freshly-identified entry.

    The single gate every browser- or file-originated object passes through (``load_json`` and
    ``add_svg`` alike): allow-listed type, image ``src`` scheme at every nesting level, and an
    id this side chose — so a payload can never pick or collide with a registry key.

    :return: a deep copy ready to store, or ``None`` if the object must be dropped.
    """
    if not isinstance(obj, dict):
        return None
    type_ = obj.get('type')
    # the isinstance guard is load-bearing: an unhashable value (JSON gives lists and
    # dicts) would make the ``in`` test raise TypeError instead of dropping the object
    if not isinstance(type_, str) or type_ not in _SUPPORTED_TYPES:
        return None
    if type_ == 'Image' and not _valid_image_src(obj.get('src')):
        return None
    # deep, so the registry never aliases the caller's payload and ``_clean_nested_images``
    # can safely fill in nested defaults
    entry = copy.deepcopy(obj)
    if not _clean_nested_images(entry):
        return None
    if type_ == 'Image':
        entry.setdefault('crossOrigin', 'anonymous')
    entry['id'] = uuid.uuid4().hex
    return entry


def _clean_objects(objects: Any, *, budget: int) -> dict[str, dict]:
    """Validate an untrusted list of object descriptors into a registry slice.

    :param budget: how many objects the registry can still take (``_MAX_OBJECTS`` for a call
        that replaces everything, less for one that appends). Checked before validation, on the
        raw count, so a huge payload is refused rather than walked. Can be negative for an
        appending caller whose registry is already past ``_MAX_OBJECTS`` — every ``add_*`` other
        than ``add_svg`` is itself uncapped, so that is reachable even though appending never
        exceeds the cap on its own.
    :raises ValueError: if ``objects`` is not a list, does not fit in ``budget``, or nests deeply
        enough that ``copy.deepcopy`` overflows the interpreter's recursion limit (converted from
        ``RecursionError`` here so both callers of this function only ever need to catch
        ``ValueError`` — see ``load_json`` and ``add_svg``).
    """
    if not isinstance(objects, list):
        raise ValueError(f'expected a list of objects, got {type(objects).__name__}')
    if len(objects) > budget:
        if budget < 0:
            raise ValueError(f'the canvas already holds {_MAX_OBJECTS - budget} objects — over '
                             f'the {_MAX_OBJECTS} cap, so none of these {len(objects)} fit')
        raise ValueError(f'{len(objects)} objects does not fit — the canvas holds at most '
                         f'{_MAX_OBJECTS} and has room for {budget}')
    fresh: dict[str, dict] = {}
    try:
        for obj in objects:
            entry = _clean_object(obj)
            if entry is not None:
                fresh[entry['id']] = entry
    except RecursionError as e:
        raise ValueError('object is too deeply nested to copy') from e
    return fresh


def _document_size(options: Any) -> tuple[float, float] | None:
    """Read a parsed SVG document's dimensions out of Fabric's ``options``, or ``None``.

    Fabric leaves them out entirely when the root element is not an ``<svg>`` (a document the
    browser's XML parser rejected, say), and a document can also declare them as percentages —
    all of which reach here as something that is not a usable number.
    """
    if not isinstance(options, dict):
        return None
    width, height = options.get('width'), options.get('height')
    if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v)
           for v in (width, height)):
        return None
    return width, height


def _clean_geometry(props: Any) -> dict:
    """Filter untrusted ``props`` down to well-typed geometry keys only.

    Never trust a browser-originated payload: this is the single choke point every
    ``object-modified`` event must pass through before touching the canonical registry.
    """
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
        self._canvas.update_object(self.id, **props)

    def delete(self) -> None:
        self._canvas.remove_object(self.id)

    def bring_to_front(self) -> None:
        self._canvas.bring_to_front(self.id)

    def send_to_back(self) -> None:
        self._canvas.send_to_back(self.id)

    def run_method(self, name: str, *args: Any, timeout: float = 1) -> AwaitableResponse:
        return self._canvas.run_object_method(self.id, name, *args, timeout=timeout)


class FabricCanvas(Element, component='fabric_canvas.js', dependencies=['lib/nicefabric.min.mjs']):

    def __init__(self, width: int = 800, height: int = 600, *,
                 background: str = '#ffffff', selection: bool = True,
                 keyboard_delete: bool = False,
                 on_selection: Handler[GenericEventArguments] | None = None,
                 on_modified: Handler[GenericEventArguments] | None = None,
                 on_added: Handler[GenericEventArguments] | None = None,
                 on_error: Handler[GenericEventArguments] | None = None,
                 on_mouse_down: Handler[GenericEventArguments] | None = None,
                 on_mouse_up: Handler[GenericEventArguments] | None = None,
                 on_text_changed: Handler[GenericEventArguments] | None = None,
                 on_moving: Handler[GenericEventArguments] | None = None,
                 moving_interval: float = 0.05,
                 on_viewport: Handler[GenericEventArguments] | None = None,
                 wheel_zoom: bool = False, drag_pan: bool = False,
                 zoom_range: tuple[float, float] = (0.3, 4.0),
                 wheel_rate: float = 0.0012) -> None:
        super().__init__()
        self._props['width'] = width
        self._props['height'] = height
        self._props['background'] = background
        self._props['selection'] = selection
        self._objects: dict[str, dict] = {}
        self.last_svg_size: tuple[float, float] | None = None
        """Dimensions of the document parsed by the most recent ``add_svg`` call that did not
        raise.

        ``None`` before the first import, after one whose document declared no usable
        ``width``/``height`` — and also after one that imported nothing at all: a malformed
        SVG and a genuinely empty one both return ``[]`` without raising (see ``add_svg``), and
        both still overwrite this from whatever ``options`` the browser reported for them, so a
        later malformed import silently clears the dimensions an earlier successful one left
        here. Only a call that *raises* leaves it untouched.

        Last-write-wins, with no lock: two ``add_svg`` calls awaited concurrently on the same
        canvas race here, and whichever browser answer is processed second overwrites the
        first's dimensions regardless of which call started or was awaited first.

        See ``add_svg``: importing is at native size, and this is what a caller needs to
        ``resize`` or scale afterwards.
        """
        self._canvas_state: dict[str, Any] = {}
        self._selected: list[str] = []
        self.is_initialized = False
        self._init_event = asyncio.Event()
        self._props['keyboardDelete'] = keyboard_delete  # camelCase like the other props — no Vue kebab normalization to reason about
        self.on('init', self._handle_init)
        self.on('object-error', self._handle_object_error)
        self.on('object-modified', self._on_modified)
        self.on('object-moving', self._on_modified)  # same payload shape; keeps the registry live
        self.on('object-added', self._on_added)
        self.on('text-changed', self._on_text_changed, throttle=0.2)
        self.on('selection', self._on_selection)
        self.on('request-delete', self._on_request_delete)
        # Only ask the browser for the continuous stream if somebody is listening to it.
        self._props['movingInterval'] = round(moving_interval * 1000) if on_moving else 0
        # Wheel-zoom and drag-to-pan run in the browser: a viewport driven over the socket lags
        # the pointer by a round trip per wheel notch. The browser reports the transform back on
        # the same throttle, so `zoom`/`pan` below stay in step with what the user sees.
        self._props['viewport'] = {
            'wheelZoom': wheel_zoom, 'dragPan': drag_pan,
            'min': zoom_range[0], 'max': zoom_range[1], 'wheelRate': wheel_rate,
            'interval': round(moving_interval * 1000),
        }
        self.zoom: float = 1.0
        """Current canvas zoom, kept live when the browser owns the viewport."""
        self.pan: tuple[float, float] = (0.0, 0.0)
        """Current pan, in `absolute_pan()`'s argument convention: passing it straight back to
        `absolute_pan()` reproduces the viewport."""
        self.on('viewport', self._on_viewport)
        for event, handler in [('selection', on_selection), ('object-modified', on_modified),
                                ('object-added', on_added), ('object-error', on_error),
                                ('mouse-down', on_mouse_down), ('mouse-up', on_mouse_up),
                                ('text-changed', on_text_changed), ('object-moving', on_moving),
                                ('viewport', on_viewport)]:
            if handler is not None:
                self.on(event, handler)

    def _handle_init(self) -> None:
        self.is_initialized = True
        self._init_event.set()
        self.run_method('sync_objects', list(self._objects.values()))
        state = self._canvas_state
        if 'background' in state:
            self.run_method('set_background', state['background'])
        if 'zoom' in state:
            self.run_method('set_zoom', state['zoom'])
        if 'pan' in state:
            self.run_method('absolute_pan', *state['pan'])
        if 'drawing' in state:
            self.run_method('set_draw_mode', True, state['drawing'])

    def _handle_object_error(self, e: GenericEventArguments) -> None:
        payload = e.args if isinstance(e.args, dict) else {}
        object_id = payload.get('id', '<unknown>')
        message = payload.get('message', '<no message>')
        logger.warning('nicefabric: object %s failed to revive in the browser: %s', object_id, message)

    def _on_modified(self, e: GenericEventArguments) -> None:
        """Merge browser-reported geometry into one registry entry.

        Never applied to an ``ActiveSelection`` member directly — the JS side skips those and
        instead re-emits absolute coords on deselection (see ``fabric_canvas.js``).
        """
        id_ = e.args.get('id') if isinstance(e.args, dict) else None
        entry = self._objects.get(id_) if isinstance(id_, str) else None
        if entry is not None:
            entry.update(_clean_geometry(e.args.get('props')))

    def _on_added(self, e: GenericEventArguments) -> None:
        """Register a freehand-drawn path. The only source of ``object-added`` — see JS side."""
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
        self._selected = [i for i in ids if isinstance(i, str) and i in self._objects] \
            if isinstance(ids, list) else []

    def _on_request_delete(self, e: GenericEventArguments) -> None:
        """Keyboard-delete round-trips through Python so the registry never diverges.

        Unlike ``remove_object`` (which raises ``KeyError`` for Python callers on an unknown
        id), this handler must no-op silently: the browser can name a stale or forged id.
        """
        ids = e.args.get('ids') if isinstance(e.args, dict) else []
        for id_ in ids if isinstance(ids, list) else []:
            if isinstance(id_, str) and id_ in self._objects:
                self.remove_object(id_)

    def get_selected(self) -> list[FabricObject]:
        return [FabricObject(self, i) for i in self._selected if i in self._objects]

    def remove_selected(self) -> None:
        """Delete every currently-selected object.

        Iterates ids (not the live ``get_selected()`` handles) so removing one entry from
        ``self._objects`` doesn't affect the list being walked; ``remove_object`` is skipped
        for any id that already vanished from the registry (e.g. removed elsewhere first).
        """
        for id_ in list(self._selected):
            if id_ in self._objects:
                self.remove_object(id_)
        self._selected = []

    def select(self, obj_or_id: FabricObject | str) -> None:
        """Make one object the browser's active object.

        The counterpart to ``discard_selection``. Needed whenever the server replaces an object
        the user had selected — restyling it, say, or rebuilding a group whose children changed:
        removing it drops the browser's active object, and until something puts the selection
        back the two sides disagree. The browser then has nothing to deselect, so the user's next
        click on the background fires no ``selection:cleared`` at all and the server's idea of
        the selection can never be cleared.

        Fabric renders controls only for the active object, so this is also what puts resize
        handles back on a recreated object.

        :raises KeyError: if the object is not in the registry
        """
        id_ = self._known_id(obj_or_id)
        self._selected = [id_]
        self.run_method('set_active', id_)

    def discard_selection(self) -> None:
        self._selected = []
        self.run_method('discard_selection')

    async def initialized(self) -> None:
        """Wait until the browser-side canvas exists (never resolves in user-fixture tests)."""
        await self.client.connected()
        await self._init_event.wait()

    def run_method(self, name: str, *args: Any, timeout: float = 1) -> AwaitableResponse:
        if not self.is_initialized:
            return NullResponse()
        return super().run_method(name, *args, timeout=timeout)

    @staticmethod
    def _warn_snake_case(props: dict, stacklevel: int) -> None:
        """Warn about snake_case prop names.

        :param stacklevel: passed to ``warnings.warn``, counted from *this* frame — so a caller
            reached directly from user code passes 3, and one more frame down passes 4.
        """
        for key in props:
            # A leading underscore is Fabric's own convention for its internal fields
            # (`_controlsVisibility`, `_cacheCanvas`, …), not a snake_case slip — only the rest
            # of the name is evidence either way.
            if '_' in key.lstrip('_'):
                head, *rest = key.lstrip('_').split('_')
                suggestion = head + ''.join(part.title() for part in rest)
                warnings.warn(f'prop {key!r} contains "_" — Fabric props are camelCase '
                              f'(did you mean {suggestion!r}?)', UserWarning, stacklevel=stacklevel)

    @staticmethod
    def _id_of(obj_or_id: FabricObject | str) -> str:
        return obj_or_id.id if isinstance(obj_or_id, FabricObject) else obj_or_id

    def _known_id(self, obj_or_id: FabricObject | str) -> str:
        """Resolve to an id that is currently in the registry, or raise ``KeyError``."""
        id_ = self._id_of(obj_or_id)
        if id_ not in self._objects:
            raise KeyError(f'unknown object id {id_!r} — it was never added or has been removed')
        return id_

    def _add(self, type_: str, props: dict) -> FabricObject:
        # every public entry point (`add_object` and the `add_*` helpers) sits exactly one frame
        # above this one, so stacklevel 4 blames the user's own line for a snake_case prop
        self._warn_snake_case(props, stacklevel=4)
        id_ = uuid.uuid4().hex
        self._objects[id_] = {'type': type_, 'id': id_, **props}
        self.run_method('add_object', self._objects[id_])
        return FabricObject(self, id_)

    def add_object(self, type_: str, **props: Any) -> FabricObject:
        return self._add(type_, props)

    def add_rect(self, **props: Any) -> FabricObject:
        return self._add('Rect', props)

    def add_circle(self, **props: Any) -> FabricObject:
        return self._add('Circle', props)

    def add_ellipse(self, **props: Any) -> FabricObject:
        return self._add('Ellipse', props)

    def add_line(self, x1: float, y1: float, x2: float, y2: float, **props: Any) -> FabricObject:
        return self._add('Line', {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2, **props})

    def add_polygon(self, points: list[dict], **props: Any) -> FabricObject:
        return self._add('Polygon', {'points': points, **props})

    def add_polyline(self, points: list[dict], **props: Any) -> FabricObject:
        return self._add('Polyline', {'points': points, **props})

    def add_path(self, path: str, **props: Any) -> FabricObject:
        return self._add('Path', {'path': path, **props})

    def add_text(self, text: str, **props: Any) -> FabricObject:
        """Creates a Fabric *Textbox* (editable, word-wrapping).

        For other text types use ``add_object('IText', text=...)`` etc.
        """
        props.setdefault('width', 200)
        return self._add('Textbox', {'text': text, **props})

    def add_image(self, url: str, **props: Any) -> FabricObject:
        props.setdefault('crossOrigin', 'anonymous')  # keeps toDataURL un-tainted
        return self._add('Image', {'src': url, **props})

    def update_object(self, obj_or_id: FabricObject | str, **props: Any) -> None:
        """Set props on one canvas object.

        :raises KeyError: if the object is not in the registry (e.g. a handle used after
            ``remove_object``/``clear_objects``)
        """
        self._warn_snake_case(props, stacklevel=3)
        id_ = self._known_id(obj_or_id)
        self._objects[id_].update(props)
        self.run_method('update_object', id_, props)

    def remove_object(self, obj_or_id: FabricObject | str) -> None:
        """Remove one canvas object.

        :raises KeyError: if the object is not in the registry (e.g. an already-removed handle)
        """
        id_ = self._known_id(obj_or_id)
        del self._objects[id_]
        self.run_method('remove_object', id_)

    def clear_objects(self) -> None:
        """Remove all canvas objects (NiceGUI child elements are untouched — see ``clear``)."""
        self._objects.clear()
        self.run_method('clear')

    def to_dict(self) -> dict:
        """Snapshot the canvas as plain data, computed from the server-side registry.

        Never a browser round-trip: Python is authoritative, so this works before init, in a
        background task and in tests where no browser exists. The copy is deep — mutating the
        result cannot reach into the registry.
        """
        return {'version': '7.4.0', 'objects': copy.deepcopy(list(self._objects.values()))}

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def load_json(self, data: str | dict) -> None:
        """Replace every canvas object with the contents of ``data``.

        Treats ``data`` as untrusted (it typically comes from a file or an upload): it is
        size-capped, dropped to an allow-listed set of types, image sources are restricted to
        http(s)/data-image URLs, and every object is given a freshly generated id so a caller
        cannot choose (or collide with) a registry key. An ``Image`` entry that does not already
        specify ``crossOrigin`` gets ``'anonymous'`` (matching ``add_image``) — otherwise a
        cross-origin image taints the canvas and a later export hangs until its timeout.

        Both ``Image`` rules apply at every nesting level, not just the top: an object whose
        ``clipPath`` (or any other nested descriptor) is an ``Image`` with a disallowed ``src``
        is dropped whole, and a nested ``Image`` that passes gets the same ``crossOrigin``
        default. The stored objects are deep copies, so the registry never aliases ``data``.

        The size cap is enforced on UTF-8 bytes and applies to a ``dict`` payload exactly like a
        ``str`` one (measured via ``json.dumps``) — a single oversized field cannot skip it by
        arriving already parsed.

        :raises ValueError: if the payload is malformed, over ``_MAX_JSON_BYTES`` bytes or holds
            more than ``_MAX_OBJECTS`` objects — in which case the canvas is left untouched. A
            pathologically deeply nested payload also raises ``ValueError`` (converted from the
            stdlib's ``RecursionError``), so callers only ever need to handle one exception type.
        """
        if isinstance(data, str):
            if len(data.encode('utf-8')) > _MAX_JSON_BYTES:
                raise ValueError(f'payload exceeds {_MAX_JSON_BYTES} bytes')
            try:
                data = json.loads(data)              # JSONDecodeError is a ValueError
            except RecursionError as e:
                raise ValueError('payload is too deeply nested') from e
        else:
            try:
                size = len(json.dumps(data).encode('utf-8'))
            except (RecursionError, TypeError) as e:
                raise ValueError(f'payload could not be measured: {e}') from e
            if size > _MAX_JSON_BYTES:
                raise ValueError(f'payload exceeds {_MAX_JSON_BYTES} bytes')
        objects = data.get('objects', []) if isinstance(data, dict) else data
        # the whole registry is being replaced, so the full cap is available
        fresh = _clean_objects(objects, budget=_MAX_OBJECTS)
        self._objects = fresh
        self._selected = []
        self.run_method('sync_objects', list(fresh.values()))

    async def add_svg(self, svg: str, *, timeout: float = 30) -> list[FabricObject]:
        """Import an SVG document as ordinary canvas objects and return handles to them.

        Fabric's SVG parser needs the browser's ``DOMParser``, so this is a round trip: the
        source goes out, the parsed shapes come back and are registered here. **It therefore
        needs a connected client** — call it from a button handler or an ``on_connect``
        callback, never from a page-builder body, where no browser exists yet and the call can
        only run out its ``timeout``. Every other ``add_*`` is fire-and-forget and has no such
        requirement.

        What lands in the registry is a *flat* list of ordinary objects — ``Path``, ``Rect``,
        ``Circle``, … — appended to whatever is already on the canvas. Fabric bakes each
        element's accumulated parent transforms into absolute ``left``/``top``/``scaleX``/…
        values and discards ``<g>`` structure, so grouping is not preserved. The gain is that
        imported shapes are indistinguishable from ones added by hand: they replay on
        reconnect, survive ``to_dict`` → ``load_json``, and can be selected and edited
        individually.

        Import is at **native size** — the canvas is not resized and nothing is scaled to fit.
        ``last_svg_size`` holds the parsed document's dimensions afterwards, so the caller can
        do either::

            objects = await canvas.add_svg(source)
            if canvas.last_svg_size:
                canvas.resize(*(round(v) for v in canvas.last_svg_size))

        The browser's answer is untrusted the same way a ``load_json`` payload is, and goes
        through the same gate (``_clean_objects``/``_clean_object``): allow-listed types only,
        image sources restricted by scheme at every nesting level, and freshly generated ids.
        Where it differs is size: the *answer* is capped at ``_MAX_SVG_RESULT_BYTES``, separately
        from the ``_MAX_JSON_BYTES`` source cap and much larger than it, because Fabric's parser
        expands source bytes rather than preserving them (see ``_MAX_SVG_RESULT_BYTES`` for the
        measurement behind the number) — and that cap is enforced before the answer is even
        parsed, let alone deep-copied into the registry, so an oversized answer costs one
        ``len()`` call, not a 20 MB ``json.loads``.

        :param svg: SVG source. Capped at ``_MAX_JSON_BYTES`` UTF-8 bytes, like ``load_json``'s.
        :param timeout: bounds the *whole* call, the wait for a client included.
        :return: handles to the shapes that were registered — empty if the document held none.
            A document the browser's XML parser rejects is not distinguishable from an empty
            one at Fabric's boundary (both parse to zero objects), so both return ``[]`` and
            leave the object registry untouched rather than raising — though ``last_svg_size``
            is still overwritten in that case (see its own docstring).
        :raises ValueError: if the source is oversized, the browser's answer is over
            ``_MAX_SVG_RESULT_BYTES``, is malformed, or the shapes would take the registry past
            ``_MAX_OBJECTS`` — in which case nothing is registered.
        :raises RuntimeError: if the parse failed in the browser.
        :raises asyncio.TimeoutError: if the whole round trip does not finish within ``timeout``.
        """
        if len(svg.encode('utf-8')) > _MAX_JSON_BYTES:
            raise ValueError(f'SVG source exceeds {_MAX_JSON_BYTES} bytes')
        payload = await self._export('import_svg', svg, timeout=timeout)
        # checked before json.loads/deepcopy ever see it — see _MAX_SVG_RESULT_BYTES
        if len(payload.encode('utf-8')) > _MAX_SVG_RESULT_BYTES:
            raise ValueError(f'the browser returned an import result over '
                             f'{_MAX_SVG_RESULT_BYTES} bytes')
        try:
            # RecursionError included for the same reason load_json converts it: the endpoint
            # that produced this body is public, so a pathological payload must not escape the
            # documented ``ValueError`` contract
            parsed = json.loads(payload)
        except (ValueError, RecursionError) as e:
            raise ValueError(f'the browser returned a malformed import result: {e}') from e
        if not isinstance(parsed, dict):
            raise ValueError(f'expected an import result, got {type(parsed).__name__}')
        # counted against what is already registered: the cap is on the canvas, not on one call
        fresh = _clean_objects(parsed.get('objects'), budget=_MAX_OBJECTS - len(self._objects))
        self.last_svg_size = _document_size(parsed.get('options'))
        self._objects.update(fresh)
        if fresh:
            self.run_method('add_objects', list(fresh.values()))
        return [FabricObject(self, id_) for id_ in fresh]

    async def _export(self, method: str, *args: Any, timeout: float) -> str:
        """Run one browser-side job and wait for it to POST its result back.

        Used by the exports and by ``add_svg``'s parse — jobs whose result is a document rather
        than a status. That result travels over HTTP rather than the websocket because a
        browser→server socket message above ~1 MB closes the connection (engine.io's default
        cap, which NiceGUI does not raise), and any real PNG export is larger than that.

        ``timeout`` bounds the *whole* call, waiting for the canvas to initialize included — the
        wait for a client is exactly the case that can never end on its own (an export fired from
        a background task after the tab closed, or from a test with no browser at all), so leaving
        it outside the budget would make the documented timeout unenforceable precisely when it
        matters. Raises ``asyncio.TimeoutError`` either way, as before.
        """
        async def run() -> str:
            await self.initialized()
            _ensure_export_route()
            token = uuid.uuid4().hex
            future: asyncio.Future = asyncio.get_running_loop().create_future()
            _pending_exports[token] = future
            try:
                self.run_method(method, token, *args)
                return await future
            finally:
                # reached on cancellation too, so the outer timeout cannot leak a token
                _pending_exports.pop(token, None)

        return await asyncio.wait_for(run(), timeout)

    async def to_svg(self, timeout: float = 30) -> str:
        """Render the canvas to SVG source in the browser. Waits for the canvas to initialize."""
        return await self._export('export_svg', timeout=timeout)

    async def to_data_url(self, format: str = 'png', quality: float = 1.0,  # noqa: A002
                          multiplier: float = 1.0, timeout: float = 30) -> str:
        """Render the canvas to a data URL in the browser. Waits for the canvas to initialize.

        An image added from a cross-origin URL that does not allow CORS taints the canvas and
        makes the browser refuse the export (see ``add_image``, which requests CORS by default).
        """
        return await self._export('export_data_url',
                                  {'format': format, 'quality': quality, 'multiplier': multiplier},
                                  timeout=timeout)

    def set_background(self, color: str) -> None:
        self._canvas_state['background'] = color
        self._props['background'] = color
        self.run_method('set_background', color)

    def set_zoom(self, zoom: float) -> None:
        self._canvas_state['zoom'] = zoom
        self.zoom = zoom
        self.run_method('set_zoom', zoom)

    def absolute_pan(self, x: float, y: float) -> None:
        self._canvas_state['pan'] = [x, y]
        self.pan = (x, y)
        self.run_method('absolute_pan', x, y)

    def _on_viewport(self, e: GenericEventArguments) -> None:
        """The browser panned or wheel-zoomed: adopt the transform it now has.

        `_canvas_state` is written too, so a reconnect replays the viewport the user left rather
        than the last one the server set.
        """
        self.zoom = e.args['zoom']
        self.pan = (e.args['panX'], e.args['panY'])
        self._canvas_state['zoom'] = self.zoom
        self._canvas_state['pan'] = [self.pan[0], self.pan[1]]

    def resize(self, width: int, height: int) -> None:
        self._props['width'] = width
        self._props['height'] = height
        self.run_method('resize', width, height)

    def bring_to_front(self, obj_or_id: FabricObject | str) -> None:
        """Move one object to the top of the z-order.

        :raises KeyError: if the object is not in the registry
        """
        id_ = self._known_id(obj_or_id)
        self._objects[id_] = self._objects.pop(id_)      # move to end = top
        self.run_method('bring_to_front', id_)

    def send_to_back(self, obj_or_id: FabricObject | str) -> None:
        """Move one object to the bottom of the z-order.

        :raises KeyError: if the object is not in the registry
        """
        id_ = self._known_id(obj_or_id)
        entry = self._objects.pop(id_)
        rest = list(self._objects.items())
        self._objects.clear()                            # rebuild in place: same dict object
        self._objects[id_] = entry                       # move to front = bottom
        self._objects.update(rest)
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
        """Call a method on the browser-side ``fabric.Canvas`` and optionally await its result.

        :param name: name of the Fabric canvas method, e.g. ``'setZoom'``
        :param args: arguments passed to the method (JSON-serialized)
        :param timeout: maximum time to wait for a response when awaited (default: 1 second)

        .. warning::
            If ``name`` is prefixed with ``':'``, every *argument* is evaluated as JavaScript
            source in the browser of every viewer of this page (``new Function``). Never pass
            untrusted or user-supplied data to a ``':'``-prefixed call.
        """
        self._check_method_name(name)
        return self.run_method('run_canvas_method', name, *args, timeout=timeout)

    def run_object_method(self, obj_or_id: FabricObject | str, name: str, *args: Any,
                           timeout: float = 1) -> AwaitableResponse:
        """Call a method on one browser-side Fabric object and optionally await its result.

        :param obj_or_id: the object handle or its id
        :param name: name of the Fabric object method, e.g. ``'get'``
        :param args: arguments passed to the method (JSON-serialized)
        :param timeout: maximum time to wait for a response when awaited (default: 1 second)

        .. warning::
            If ``name`` is prefixed with ``':'``, every *argument* is evaluated as JavaScript
            source in the browser of every viewer of this page (``new Function``). Never pass
            untrusted or user-supplied data to a ``':'``-prefixed call.
        """
        self._check_method_name(name)
        return self.run_method('run_object_method', self._id_of(obj_or_id), name, *args, timeout=timeout)

    @staticmethod
    def _check_method_name(name: str) -> None:
        if not _METHOD_NAME.match(name.removeprefix(':')):
            raise ValueError(f'invalid method name: {name!r}')
