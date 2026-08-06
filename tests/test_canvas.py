from typing import Callable

import pytest
from nicegui import ui
from nicegui.awaitable_response import NullResponse
from nicegui.testing import User

from nicefabric import FabricCanvas


@pytest.fixture
def canvas_page() -> Callable[[], FabricCanvas]:
    """Build a page with a single FabricCanvas and hand back the created instance.

    The canvas is captured via a closure over a list because the page builder
    function runs later, when the client actually opens the page.
    """
    canvases: list[FabricCanvas] = []

    @ui.page('/')
    def page() -> None:
        c = FabricCanvas()
        canvases.append(c)

    def get() -> FabricCanvas:
        return canvases[0]

    return get


async def test_element_renders(user: User) -> None:
    @ui.page('/')
    def page() -> None:
        FabricCanvas(width=400, height=300)
    await user.open('/')
    # the custom tag is present in the page tree
    assert user.find(FabricCanvas).elements


async def test_add_rect_registers_before_init(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    returned_id = c.add_rect(left=10, top=20, width=30, height=40, fill='red')
    assert not c.is_initialized          # user fixture never runs JS → init never fires
    (obj,) = c._objects.values()
    assert obj['type'] == 'Rect' and obj['left'] == 10 and 'id' in obj
    assert returned_id == obj['id']


async def test_handle_init_replays_pending_objects(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    returned_id = c.add_rect(left=1, top=2, width=3, height=4, fill='blue')
    assert not c.is_initialized

    replayed: dict[str, list] = {}

    def fake_run_method(name, *args, timeout=1):
        if name == 'sync_objects':
            replayed['payload'] = args[0]
        return NullResponse()

    c.run_method = fake_run_method  # type: ignore[method-assign]

    c._handle_init()

    assert c.is_initialized is True
    assert c._init_event.is_set()
    assert replayed['payload'] == list(c._objects.values())
    assert replayed['payload'] == [c._objects[returned_id]]
