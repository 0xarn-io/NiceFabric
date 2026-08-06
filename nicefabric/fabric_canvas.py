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
