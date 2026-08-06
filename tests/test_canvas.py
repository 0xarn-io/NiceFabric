import json
from typing import Callable

import pytest
from nicegui import ui
from nicegui.awaitable_response import NullResponse
from nicegui.events import GenericEventArguments
from nicegui.testing import User

from nicefabric import FabricCanvas
from nicefabric.fabric_canvas import _MAX_PATH_BYTES


def _ev(canvas: FabricCanvas, args: dict) -> GenericEventArguments:
    return GenericEventArguments(sender=canvas, client=canvas.client, args=args)


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


async def test_canvas_ops_accept_bare_id(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    a, b = c.add_rect(), c.add_circle(radius=5)
    c.update_object(a.id, fill='green')      # a raw id string, not a handle
    assert c._objects[a.id]['fill'] == 'green'
    c.bring_to_front(a.id)
    assert list(c._objects) == [b.id, a.id]
    c.remove_object(a.id)
    assert a.id not in c._objects


async def test_send_to_back_reorders_the_same_dict(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    a, b = c.add_rect(), c.add_circle(radius=5)
    registry = c._objects                    # a holder of the dict, like a sync-back handler
    c.send_to_back(b)
    assert list(c._objects) == [b.id, a.id]  # b is now at the bottom
    assert c._objects is registry            # same dict object — no stale references
    assert list(registry) == [b.id, a.id]


async def test_clear_objects_empties_the_registry(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    c.add_rect()
    c.add_circle(radius=5)
    c.clear_objects()
    assert c._objects == {}


async def test_element_clear_remove_update_are_unshadowed(user: User,
                                                          canvas_page: Callable[[], FabricCanvas]) -> None:
    """The three base `Element` methods keep their own meaning (children, not canvas objects)."""
    await user.open('/')
    c = canvas_page()
    r = c.add_rect()
    with c:
        child = ui.label('inside the canvas element')
    assert c.clear() is c                    # Element.clear() -> Self
    assert not list(c)                       # the NiceGUI child is gone ...
    assert r.id in c._objects                # ... but the canvas object is untouched
    with c:
        child = ui.label('again')
    c.remove(child)                          # Element.remove(child) still works
    assert not list(c)
    assert c.update() is None                # Element.update() -> None


async def test_resize_updates_props(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    c.resize(1024, 768)
    assert c._props['width'] == 1024
    assert c._props['height'] == 768


async def test_draw_mode_toggles(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    assert c.draw_mode is False
    c.enable_drawing(color='#00ff00', width=5)
    assert c.draw_mode is True
    assert c._canvas_state['drawing'] == {'color': '#00ff00', 'width': 5}
    c.disable_drawing()
    assert c.draw_mode is False
    assert 'drawing' not in c._canvas_state


async def test_unknown_id_raises_key_error(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    stale = c.add_rect()
    c.clear_objects()                        # the handle is now stale
    with pytest.raises(KeyError):
        c.update_object(stale, fill='blue')
    with pytest.raises(KeyError):
        c.remove_object(stale)
    with pytest.raises(KeyError):
        c.bring_to_front(stale)
    with pytest.raises(KeyError):
        c.send_to_back(stale)


async def test_snake_case_prop_warns(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    with pytest.warns(UserWarning, match='stroke_width'):
        c.add_rect(stroke_width=4)


async def test_snake_case_warning_blames_the_caller(user: User,
                                                    canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    with pytest.warns(UserWarning) as helper_warning:
        c.add_rect(stroke_width=4)                 # user -> add_rect -> _add -> _warn_snake_case
    with pytest.warns(UserWarning) as direct_warning:
        c.add_object('Rect', stroke_width=4)       # user -> add_object -> _add -> _warn_snake_case
    r = c.add_rect()
    with pytest.warns(UserWarning) as update_warning:
        c.update_object(r, stroke_width=4)         # user -> update_object -> _warn_snake_case
    for record in (helper_warning, direct_warning, update_warning):
        assert record[0].filename == __file__      # not nicefabric/fabric_canvas.py


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


async def test_run_methods_accept_legitimate_names(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    r = c.add_rect()
    # pre-init there is no browser to talk to, so a permitted name yields a NullResponse
    assert isinstance(c.run_canvas_method('setZoom', 2), NullResponse)
    assert isinstance(c.run_object_method(r, 'get', 'left'), NullResponse)
    assert isinstance(c.run_canvas_method(':setZoom', '1 + 1'), NullResponse)  # the JS-eval form


async def test_modified_merges_geometry_only(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    r = c.add_rect(left=0, top=0)
    c._on_modified(_ev(c, {'id': r.id, 'props': {
        'left': 50.5, 'angle': 90, 'type': 'Image', 'src': 'https://evil', 'fill': 'green'}}))
    entry = c._objects[r.id]
    assert entry['left'] == 50.5 and entry['angle'] == 90
    assert entry['type'] == 'Rect' and 'src' not in entry and entry.get('fill') != 'green'


async def test_modified_rejects_nan_and_unknown_id(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    r = c.add_rect(left=0)
    c._on_modified(_ev(c, {'id': r.id, 'props': {'left': float('nan')}}))
    assert c._objects[r.id]['left'] == 0
    c._on_modified(_ev(c, {'id': 'nope', 'props': {'left': 1}}))   # silently ignored


async def test_modified_rejects_bool_and_non_finite(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """bool is a subclass of int in Python — must not sneak into numeric geometry keys."""
    await user.open('/')
    c = canvas_page()
    r = c.add_rect(left=0, flipX=False)
    c._on_modified(_ev(c, {'id': r.id, 'props': {
        'left': True, 'top': float('inf'), 'flipX': 'yes'}}))
    assert c._objects[r.id]['left'] == 0
    assert 'top' not in c._objects[r.id]
    assert c._objects[r.id]['flipX'] is False


async def test_path_added_validated(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    c._on_added(_ev(c, {'id': 'p1', 'obj': {'type': 'Path', 'path': [['M', 0, 0]], 'stroke': '#000'}}))
    assert 'p1' in c._objects
    c._on_added(_ev(c, {'id': 'p1', 'obj': {'type': 'Path', 'path': []}}))        # duplicate id → ignored
    c._on_added(_ev(c, {'id': 'p2', 'obj': {'type': 'Image', 'src': 'x'}}))        # wrong type → ignored
    assert 'p2' not in c._objects and c._objects['p1']['stroke'] == '#000'


async def test_path_added_rejects_oversized_payload(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    obj = {'type': 'Path', 'path': [['L', 0, 0]]}
    while len(json.dumps(obj)) <= _MAX_PATH_BYTES:                # grow past the cap, precisely
        obj['path'].append(['L', 1, 1])
    c._on_added(_ev(c, {'id': 'big', 'obj': obj}))
    assert 'big' not in c._objects


async def test_text_changed_capped_and_typed(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    t = c.add_text('hi')
    r = c.add_rect()
    c._on_text_changed(_ev(c, {'id': t.id, 'text': 'new'}))
    assert c._objects[t.id]['text'] == 'new'
    c._on_text_changed(_ev(c, {'id': r.id, 'text': 'nope'}))       # not a text type → ignored
    c._on_text_changed(_ev(c, {'id': t.id, 'text': 'x' * 30_000})) # over cap → ignored
    assert c._objects[t.id]['text'] == 'new'


async def test_selection_tracked_and_remove_selected(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    a, b = c.add_rect(), c.add_rect()
    c._on_selection(_ev(c, {'kind': 'created', 'ids': [a.id, 'bogus', b.id]}))
    assert [o.id for o in c.get_selected()] == [a.id, b.id]
    c.remove_selected()
    assert not c._objects and not c.get_selected()


async def test_request_delete_removes_known_ids_and_ignores_unknown(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """The critical fix over the stale brief: remove_object raises KeyError on unknown ids for
    Python callers, but a browser-originated request-delete must no-op silently on a stale/hostile id."""
    await user.open('/')
    c = canvas_page()
    a, b = c.add_rect(), c.add_rect()
    c._on_request_delete(_ev(c, {'ids': [a.id, 'unknown-id', 12345]}))  # must not raise
    assert a.id not in c._objects
    assert b.id in c._objects


async def test_discard_selection_clears_local_state(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    a = c.add_rect()
    c._on_selection(_ev(c, {'kind': 'created', 'ids': [a.id]}))
    assert c.get_selected()
    c.discard_selection()
    assert not c.get_selected()


async def test_ctor_kwargs_wire_user_handlers(user: User) -> None:
    """Every on_* ctor kwarg registers as a real event listener alongside the internal handler."""
    from nicegui.helpers import event_type_to_camel_case

    handlers = {
        'selection': lambda e: None,
        'object-modified': lambda e: None,
        'object-added': lambda e: None,
        'object-error': lambda e: None,
        'mouse-down': lambda e: None,
        'mouse-up': lambda e: None,
        'text-changed': lambda e: None,
    }

    @ui.page('/')
    def page() -> None:
        FabricCanvas(
            on_selection=handlers['selection'],
            on_modified=handlers['object-modified'],
            on_added=handlers['object-added'],
            on_error=handlers['object-error'],
            on_mouse_down=handlers['mouse-down'],
            on_mouse_up=handlers['mouse-up'],
            on_text_changed=handlers['text-changed'],
        )

    await user.open('/')
    c = user.find(FabricCanvas).elements.pop()
    registered = {(listener.type, listener.handler) for listener in c._event_listeners.values()}
    for event, handler in handlers.items():
        assert (event_type_to_camel_case(event), handler) in registered


async def test_keyboard_delete_prop_defaults_false_and_is_settable(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    default_canvas = canvas_page()
    assert default_canvas._props['keyboardDelete'] is False


async def test_keyboard_delete_prop_true_when_requested(user: User) -> None:
    @ui.page('/')
    def page() -> None:
        FabricCanvas(keyboard_delete=True)

    await user.open('/')
    (enabled_canvas,) = user.find(FabricCanvas).elements
    assert enabled_canvas._props['keyboardDelete'] is True


# --- hostile-input coverage: every handler must no-op, never raise, on malformed payloads ---

async def test_on_modified_hostile_payloads(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    r = c.add_rect(left=0)
    c._on_modified(_ev(c, 'not-a-dict'))                          # args not a dict
    c._on_modified(_ev(c, {'props': {'left': 5}}))                 # missing id
    c._on_modified(_ev(c, {'id': 123, 'props': {'left': 5}}))      # id wrong type
    c._on_modified(_ev(c, {'id': r.id, 'props': 'not-a-dict'}))    # props not a dict
    c._on_modified(_ev(c, {'id': r.id, 'props': None}))            # props missing/None
    assert c._objects[r.id]['left'] == 0


async def test_on_added_hostile_payloads(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    c._on_added(_ev(c, 'not-a-dict'))                              # args not a dict
    c._on_added(_ev(c, {'obj': {'type': 'Path', 'path': []}}))     # missing id
    c._on_added(_ev(c, {'id': 42, 'obj': {'type': 'Path', 'path': []}}))  # id wrong type
    c._on_added(_ev(c, {'id': 'x1', 'obj': 'not-a-dict'}))         # obj not a dict
    c._on_added(_ev(c, {'id': 'x2'}))                              # missing obj
    assert c._objects == {}


async def test_on_text_changed_hostile_payloads(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    t = c.add_text('hi')
    c._on_text_changed(_ev(c, 'not-a-dict'))                       # args not a dict
    c._on_text_changed(_ev(c, {'text': 'nope'}))                   # missing id
    c._on_text_changed(_ev(c, {'id': 123, 'text': 'nope'}))        # id wrong type
    c._on_text_changed(_ev(c, {'id': t.id, 'text': 123}))          # text wrong type
    c._on_text_changed(_ev(c, {'id': t.id}))                       # missing text
    assert c._objects[t.id]['text'] == 'hi'


async def test_on_selection_hostile_payloads(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    a = c.add_rect()
    c._on_selection(_ev(c, {'kind': 'created', 'ids': [a.id]}))
    assert c._selected == [a.id]
    c._on_selection(_ev(c, 'not-a-dict'))                          # args not a dict → cleared
    assert c._selected == []
    c._on_selection(_ev(c, {'kind': 'created', 'ids': [a.id]}))
    c._on_selection(_ev(c, {'kind': 'created', 'ids': 'not-a-list'}))  # ids not a list → cleared
    assert c._selected == []
    c._on_selection(_ev(c, {'kind': 'created'}))                   # missing ids → cleared
    assert c._selected == []
    c._on_selection(_ev(c, {'kind': 'created', 'ids': [a.id, 123, None]}))  # non-str entries dropped
    assert c._selected == [a.id]


async def test_on_request_delete_hostile_payloads(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    a = c.add_rect()
    c._on_request_delete(_ev(c, 'not-a-dict'))                     # args not a dict
    c._on_request_delete(_ev(c, {}))                                # missing ids
    c._on_request_delete(_ev(c, {'ids': 'not-a-list'}))            # ids not a list
    c._on_request_delete(_ev(c, {'ids': [123, None, {}]}))         # wrong-typed entries
    assert a.id in c._objects                                       # nothing above touched the registry
    c._on_request_delete(_ev(c, {'ids': [a.id]}))
    assert a.id not in c._objects


async def test_handle_init_replays_canvas_state(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    r = c.add_rect(left=1)
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

    # order matters: objects are synced first, and zoom must be applied before the pan it scales
    assert replayed == [
        ('sync_objects', ([c._objects[r.id]],)),
        ('set_background', ('#123456',)),
        ('set_zoom', (2.0,)),
        ('absolute_pan', (5, 6)),
        ('set_draw_mode', (True, {'color': '#ff0000', 'width': 3})),
    ]
