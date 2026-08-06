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
_TEXT_TYPES = frozenset({'Textbox', 'IText', 'FabricText', 'Text'})
_PATH_KEYS = frozenset({'type', 'id', 'path', 'left', 'top', 'width', 'height',
                         'scaleX', 'scaleY', 'angle', 'fill', 'stroke', 'strokeWidth',
                         'strokeLineCap', 'strokeLineJoin', 'strokeMiterLimit', 'strokeDashArray'})
_MAX_TEXT_LEN = 20_000
_MAX_PATH_BYTES = 256_000

_MAX_JSON_BYTES = 1_000_000
_MAX_OBJECTS = 1000
_SUPPORTED_TYPES = frozenset({'Rect', 'Circle', 'Ellipse', 'Line', 'Polygon', 'Polyline',
                              'Path', 'Textbox', 'IText', 'FabricText', 'Image'})
_MAX_EXPORT_BYTES = 64_000_000
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
                 on_text_changed: Handler[GenericEventArguments] | None = None) -> None:
        super().__init__()
        self._props['width'] = width
        self._props['height'] = height
        self._props['background'] = background
        self._props['selection'] = selection
        self._objects: dict[str, dict] = {}
        self._canvas_state: dict[str, Any] = {}
        self._selected: list[str] = []
        self.is_initialized = False
        self._init_event = asyncio.Event()
        self._props['keyboardDelete'] = keyboard_delete  # camelCase like the other props — no Vue kebab normalization to reason about
        self.on('init', self._handle_init)
        self.on('object-error', self._handle_object_error)
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
            if '_' in key:
                head, *rest = key.split('_')
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
        cannot choose (or collide with) a registry key.

        :raises ValueError: if the payload is malformed, over ``_MAX_JSON_BYTES`` or holds more
            than ``_MAX_OBJECTS`` objects — in which case the canvas is left untouched
        """
        if isinstance(data, str):
            if len(data) > _MAX_JSON_BYTES:
                raise ValueError(f'payload exceeds {_MAX_JSON_BYTES} bytes')
            data = json.loads(data)                  # JSONDecodeError is a ValueError
        objects = data.get('objects', []) if isinstance(data, dict) else data
        if not isinstance(objects, list):
            raise ValueError(f'expected a list of objects, got {type(objects).__name__}')
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
        """Ask the browser to render an export and wait for it to POST the result back.

        The result travels over HTTP rather than the websocket because a browser→server socket
        message above ~1 MB closes the connection (engine.io's default cap, which NiceGUI does
        not raise), and any real PNG export is larger than that.
        """
        await self.initialized()
        _ensure_export_route()
        token = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        _pending_exports[token] = future
        try:
            self.run_method(method, token, *args)
            return await asyncio.wait_for(future, timeout)
        finally:
            _pending_exports.pop(token, None)

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
        self.run_method('set_zoom', zoom)

    def absolute_pan(self, x: float, y: float) -> None:
        self._canvas_state['pan'] = [x, y]
        self.run_method('absolute_pan', x, y)

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
