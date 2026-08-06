from __future__ import annotations

import asyncio
import logging
import re
import uuid
import warnings
from typing import Any

from nicegui.awaitable_response import AwaitableResponse, NullResponse
from nicegui.element import Element
from nicegui.events import GenericEventArguments

logger = logging.getLogger(__name__)

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
        self.on('object-error', self._handle_object_error)

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

    async def initialized(self) -> None:
        """Wait until the browser-side canvas exists (never resolves in user-fixture tests)."""
        await self.client.connected()
        await self._init_event.wait()

    def run_method(self, name: str, *args: Any, timeout: float = 1) -> AwaitableResponse:
        if not self.is_initialized:
            return NullResponse()
        return super().run_method(name, *args, timeout=timeout)

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

    def add_rect(self, **props: Any) -> FabricObject:
        return self.add_object('Rect', **props)

    def add_circle(self, **props: Any) -> FabricObject:
        return self.add_object('Circle', **props)

    def add_ellipse(self, **props: Any) -> FabricObject:
        return self.add_object('Ellipse', **props)

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

    def update(self, obj_or_id: FabricObject | str | None = None, **props: Any) -> None:
        # `Element.update()` is called with no arguments by NiceGUI internals
        # (e.g. `.on()`, `.classes()`, `.style()`, `.props()`) to re-render this
        # element on the client. That base signature collides with the canvas-op
        # `update(obj_or_id, **props)` this class needs, so a bare no-arg call
        # falls back to the inherited behavior instead of erroring.
        if obj_or_id is None and not props:
            super().update()
            return
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
