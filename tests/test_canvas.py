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
    returned = c.add_rect(left=10, top=20, width=30, height=40, fill='red')
    assert not c.is_initialized          # user fixture never runs JS → init never fires
    (obj,) = c._objects.values()
    assert obj['type'] == 'Rect' and obj['left'] == 10 and 'id' in obj
    assert returned.id == obj['id']


async def test_handle_init_replays_pending_objects(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    returned = c.add_rect(left=1, top=2, width=3, height=4, fill='blue')
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
    assert replayed['payload'] == [c._objects[returned.id]]


async def test_helpers_return_handles_and_register(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    r = c.add_rect(left=1, top=2, width=3, height=4)
    t = c.add_text('hello', left=5, top=6)
    assert r.type == 'Rect' and t.type == 'Textbox'
    assert c._objects[r.id]['left'] == 1
    assert c._objects[t.id]['text'] == 'hello'


async def test_update_delete_and_zorder(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    a, b = c.add_rect(), c.add_circle(radius=5)
    a.update(fill='blue')
    assert c._objects[a.id]['fill'] == 'blue'
    c.bring_to_front(a)                      # accepts handle or id
    assert list(c._objects) == [b.id, a.id]  # dict order = z-order
    a.delete()
    assert a.id not in c._objects


async def test_snake_case_prop_warns(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    with pytest.warns(UserWarning, match='stroke_width'):
        c.add_rect(stroke_width=4)


async def test_image_defaults_cross_origin(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    img = c.add_image('https://example.com/a.png')
    assert c._objects[img.id]['crossOrigin'] == 'anonymous'
    assert c._objects[img.id]['src'] == 'https://example.com/a.png'


async def test_run_canvas_method_rejects_hostile_name(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    with pytest.raises(ValueError):
        c.run_canvas_method(':alert(1);//')


async def test_run_object_method_rejects_hostile_name(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    r = c.add_rect()
    with pytest.raises(ValueError):
        c.run_object_method(r, ':alert(1);//')


async def test_handle_init_replays_canvas_state(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    c.set_background('#123456')
    c.set_zoom(2.0)
    c.absolute_pan(5, 6)
    c.enable_drawing(color='#ff0000', width=3)
    assert not c.is_initialized

    replayed: list[tuple] = []

    def fake_run_method(name, *args, timeout=1):
        replayed.append((name, args))
        return NullResponse()

    c.run_method = fake_run_method  # type: ignore[method-assign]

    c._handle_init()

    calls = dict(replayed)
    assert calls['set_background'] == ('#123456',)
    assert calls['set_zoom'] == (2.0,)
    assert calls['absolute_pan'] == (5, 6)
    assert calls['set_draw_mode'] == (True, {'color': '#ff0000', 'width': 3})
