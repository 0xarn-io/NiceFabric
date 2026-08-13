import asyncio
import warnings
import json
import subprocess
import sys
from typing import Any, Callable

import pytest
from nicegui import app, ui
from nicegui.awaitable_response import NullResponse
from nicegui.events import GenericEventArguments
from nicegui.testing import User
from starlette.requests import Request

from nicefabric import FabricCanvas
from nicefabric.fabric_canvas import (_EXPORT_PATH, _MAX_EXPORT_BYTES, _MAX_JSON_BYTES,
                                       _MAX_OBJECTS, _MAX_PATH_BYTES, _MAX_SVG_RESULT_BYTES,
                                       _SUPPORTED_TYPES, _TEXT_TYPES, _pending_exports,
                                       _receive_export)


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


# --- serialization: computed server-side, never a browser round-trip ---

async def test_to_dict_roundtrip_without_browser(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    c.add_rect(left=1)
    c.add_text('hi')
    snapshot = c.to_dict()
    assert not c.is_initialized                     # no browser was ever involved
    assert snapshot['version'] == '7.4.0'
    assert len(snapshot['objects']) == 2
    snapshot['objects'][0]['left'] = 99
    assert list(c._objects.values())[0]['left'] == 1  # deep copy — no aliasing


async def test_to_json_matches_to_dict(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    c.add_rect(left=1)
    assert json.loads(c.to_json()) == c.to_dict()


async def test_load_json_validates_and_assigns_fresh_ids(user: User,
                                                         canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
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
    assert all(key == o['id'] for key, o in c._objects.items())   # registry keyed by the fresh id


async def test_load_json_accepts_a_to_json_snapshot(user: User,
                                                    canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    c.add_rect(left=7)
    c.add_text('hi')
    restored = c.to_json()
    c.clear_objects()
    c.load_json(restored)
    assert [o['type'] for o in c._objects.values()] == ['Rect', 'Textbox']
    assert list(c._objects.values())[0]['left'] == 7


async def test_load_json_caps(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    with pytest.raises(ValueError):
        c.load_json(json.dumps({'objects': []}) + ' ' * 2_000_000)
    with pytest.raises(ValueError):
        c.load_json({'objects': [{'type': 'Rect'}] * (_MAX_OBJECTS + 1)})
    assert c._objects == {}                                       # nothing was applied


async def test_load_json_size_cap_covers_the_dict_path(user: User,
                                                        canvas_page: Callable[[], FabricCanvas]) -> None:
    """A dict payload must not skip the size cap just because it was never a JSON string."""
    await user.open('/')
    c = canvas_page()
    with pytest.raises(ValueError):
        c.load_json({'objects': [{'type': 'Rect', 'text': 'x' * 2_000_000}]})
    assert c._objects == {}


async def test_load_json_size_cap_is_byte_accurate_not_char_accurate(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """A multi-byte-heavy string can be under the character cap yet over the byte cap.

    The padding lives inside a valid JSON value (not appended as trailing garbage) so a
    char-count-only cap would let ``json.loads`` succeed and load the object — the mutation this
    test exists to catch, as opposed to merely tripping ``JSONDecodeError`` on malformed input.
    """
    await user.open('/')
    c = canvas_page()
    payload = json.dumps({'objects': [{'type': 'Rect', 'note': '\U0001f389' * 300_000}]},
                          ensure_ascii=False)                # 4 UTF-8 bytes per emoji
    assert len(payload) < _MAX_JSON_BYTES                    # character count alone looks fine
    assert len(payload.encode('utf-8')) > _MAX_JSON_BYTES
    with pytest.raises(ValueError):
        c.load_json(payload)
    assert c._objects == {}


async def test_load_json_rejects_malformed_payloads(user: User,
                                                    canvas_page: Callable[[], FabricCanvas]) -> None:
    """Hostile input must raise ValueError, never TypeError or a partially applied registry."""
    await user.open('/')
    c = canvas_page()
    r = c.add_rect()
    for payload in ['{not json', '5', '"a string"', {'objects': 5}, {'objects': 'a string'}]:
        with pytest.raises(ValueError):
            c.load_json(payload)
    assert r.id in c._objects                                     # registry untouched


async def test_load_json_converts_recursion_error_to_value_error(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """A pathologically nested payload must not leak json.loads's RecursionError past the
    documented ``:raises ValueError:`` contract."""
    await user.open('/')
    c = canvas_page()
    deeply_nested = '[' * 10_000 + ']' * 10_000
    with pytest.raises(ValueError):
        c.load_json(deeply_nested)
    assert c._objects == {}


async def test_load_json_converts_deepcopy_recursion_error_to_value_error(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """Distinct failure point from the ``json.loads`` test above: this payload is shallow enough
    for ``json.dumps`` (used to measure a ``dict`` payload's size) to succeed, but nested deep
    enough that ``copy.deepcopy`` inside ``_clean_objects``/``_clean_object`` overflows the
    recursion limit. That must still surface as ``ValueError``, not leak past the documented
    contract — this was reachable before ``_clean_objects`` wrapped its loop (see ``add_svg``'s
    sibling test, which shares the same underlying fix)."""
    await user.open('/')
    c = canvas_page()
    r = c.add_rect()
    nested: Any = 'leaf'
    for _ in range(600):
        nested = [nested]
    with pytest.raises(ValueError):
        c.load_json({'objects': [{'type': 'Rect', 'junk': nested}]})
    assert r.id in c._objects                                      # registry untouched


async def test_load_json_drops_objects_with_an_unhashable_type(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """JSON can carry a list or dict where a type name is expected — dropped, never a TypeError."""
    await user.open('/')
    c = canvas_page()
    c.load_json(json.dumps({'objects': [{'type': ['Rect']}, {'type': {'a': 1}},
                                        {'type': None}, {'type': 'Rect'}]}))
    assert [o['type'] for o in c._objects.values()] == ['Rect']


async def test_load_json_defaults_cross_origin_for_images(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """Matches add_image's default — an un-CORS'd image taints the canvas and hangs an export."""
    await user.open('/')
    c = canvas_page()
    c.load_json({'objects': [
        {'type': 'Image', 'src': 'https://ok.example/a.png'},
        {'type': 'Image', 'src': 'https://ok.example/b.png', 'crossOrigin': 'use-credentials'},
    ]})
    a, b = c._objects.values()
    assert a['crossOrigin'] == 'anonymous'
    assert b['crossOrigin'] == 'use-credentials'          # the payload's own value is not overwritten


def test_every_text_type_is_also_loadable() -> None:
    """What the text sync-back records must be what ``load_json`` can revive.

    ``_TEXT_TYPES`` gates ``_on_text_changed`` (a browser edit is merged into the registry);
    ``_SUPPORTED_TYPES`` gates ``load_json``. A type in the first but not the second means edits
    are faithfully recorded into an entry that the very next ``to_dict()``/``load_json()`` round
    trip drops on the floor — silent data loss with no error anywhere. That is exactly what
    happened to ``'Text'``, while ``'FabricText'`` — an export alias, *not* a key in Fabric
    7.4.0's ``classRegistry`` — was accepted here and then threw in ``enlivenObjects``.
    """
    assert _TEXT_TYPES <= _SUPPORTED_TYPES, sorted(_TEXT_TYPES - _SUPPORTED_TYPES)


async def test_every_type_the_api_can_create_survives_a_round_trip(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """Everything this package can put on a canvas must come back out of ``load_json``.

    Derived from the public API (every ``add_*`` helper, plus every ``_TEXT_TYPES`` member via
    ``add_object``) rather than from a copy of ``_SUPPORTED_TYPES``, so it fails when the
    allow-list and what the package actually produces disagree.
    """
    await user.open('/')
    c = canvas_page()
    points = [{'x': 0, 'y': 0}, {'x': 10, 'y': 0}, {'x': 10, 'y': 10}]
    c.add_rect()
    c.add_circle()
    c.add_ellipse()
    c.add_line(0, 0, 10, 10)
    c.add_polygon(points)
    c.add_polyline(points)
    c.add_path('M 0 0 L 10 10')
    c.add_text('hi')
    c.add_image('https://ok.example/a.png')
    for type_ in sorted(_TEXT_TYPES):
        c.add_object(type_, text='hi')
    before = [o['type'] for o in c._objects.values()]
    assert 'Text' in before                                       # the API really does emit it
    snapshot = c.to_dict()
    c.clear_objects()
    c.load_json(snapshot)
    assert [o['type'] for o in c._objects.values()] == before


async def test_plain_text_survives_a_round_trip_with_its_text(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """``add_object('Text', ...)`` is what ``add_text``'s docstring points at, and it is also
    what Fabric's own ``toJSON`` writes for plain text — so a third-party payload takes this
    path too. The content, not just the type, has to survive."""
    await user.open('/')
    c = canvas_page()
    c.add_object('Text', text='hello', left=3)
    c.load_json(c.to_dict())
    (obj,) = c._objects.values()
    assert obj['type'] == 'Text' and obj['text'] == 'hello' and obj['left'] == 3


async def test_load_json_drops_the_unregistered_fabrictext_name(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """``FabricText`` is the exported class name, not a ``classRegistry`` key: accepting it here
    would let a payload pass server validation and then fail in ``enlivenObjects``."""
    await user.open('/')
    c = canvas_page()
    c.load_json({'objects': [{'type': 'FabricText', 'text': 'x'}, {'type': 'Text', 'text': 'y'}]})
    assert [o['type'] for o in c._objects.values()] == ['Text']


async def test_load_json_validates_nested_image_sources(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """The scheme allow-list applies at every depth — Fabric revives a nested Image like any
    other, so a top-level-only check leaves one hole in an otherwise uniform validation story."""
    await user.open('/')
    c = canvas_page()
    c.load_json({'objects': [
        {'type': 'Rect', 'clipPath': {'type': 'Image', 'src': 'javascript:alert(1)'}},   # dropped
        {'type': 'Rect', 'clipPath': {'type': 'Image'}},                    # no src at all → dropped
        {'type': 'Rect', 'clipPath': {'type': 'Group',                      # inside a list, deeper
                                       'objects': [{'type': 'Image', 'src': 'ftp://x/y.png'}]}},
        {'type': 'Image', 'src': 'https://ok.example/a.png',
         'clipPath': {'type': 'Image', 'src': 'data:image/png;base64,AAA'}},          # both fine
    ]})
    (kept,) = c._objects.values()
    assert kept['type'] == 'Image'
    assert kept['clipPath']['crossOrigin'] == 'anonymous'   # nested images get add_image's default


async def test_load_json_does_not_alias_the_payload(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """Entries are deep copies, so filling in nested defaults cannot write into the caller's
    dict and later registry mutations cannot leak back out."""
    await user.open('/')
    c = canvas_page()
    nested = {'type': 'Image', 'src': 'https://ok.example/c.png'}
    payload = {'objects': [{'type': 'Rect', 'clipPath': nested}]}
    c.load_json(payload)
    (entry,) = c._objects.values()
    assert 'crossOrigin' not in nested                    # the default landed on the copy only
    entry['clipPath']['src'] = 'https://mutated.example/x.png'
    assert nested['src'] == 'https://ok.example/c.png'


async def test_load_json_clears_selection(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    a = c.add_rect()
    c._on_selection(_ev(c, {'kind': 'created', 'ids': [a.id]}))
    c.load_json({'objects': [{'type': 'Rect'}]})
    assert c._selected == [] and a.id not in c._objects


# --- HTTP export side-channel ---
# The endpoint is a public, unauthenticated route: every test below feeds it what an
# attacker could send (unknown token, replay, oversized body, binary garbage).

def _request(body: bytes, *, declared_length: int | None = None, chunk_size: int | None = None,
             on_receive: Callable[[], Any] | None = None,
             query_string: bytes = b'') -> tuple[Request, list[int]]:
    """Build a real Starlette ``Request`` and a log of the chunk sizes actually consumed.

    :param declared_length: value for the ``content-length`` header (defaults to the real length)
    :param chunk_size: split the body into chunks of this size, as a chunked upload would arrive
    :param on_receive: called as each chunk is handed over, to interfere mid-upload
    :param query_string: raw query string, e.g. ``b'error=1'`` to simulate a failed export
    """
    consumed: list[int] = []
    length = len(body) if declared_length is None else declared_length
    size = len(body) if chunk_size is None else chunk_size
    chunks = [body[i:i + size] for i in range(0, len(body), size)] or [b'']

    async def receive() -> dict:
        if on_receive is not None:
            on_receive()
        chunk = chunks.pop(0) if chunks else b''
        consumed.append(len(chunk))
        return {'type': 'http.request', 'body': chunk, 'more_body': bool(chunks)}

    scope = {'type': 'http', 'method': 'POST', 'path': '/_nicefabric/export/t',
             'query_string': query_string, 'headers': [(b'content-length', str(length).encode())]}
    return Request(scope, receive), consumed


def _pend(token: str) -> asyncio.Future:
    future = asyncio.get_running_loop().create_future()
    _pending_exports[token] = future
    return future


@pytest.fixture(autouse=True)
def _no_leaked_exports():
    """Every test must leave the process-wide pending-export table empty."""
    yield
    assert not _pending_exports, f'leaked pending exports: {list(_pending_exports)}'
    _pending_exports.clear()


def _export_route_present() -> bool:
    return any(getattr(route, 'path', None) == _EXPORT_PATH for route in app.routes)


def test_export_route_is_registered_at_import() -> None:
    """Importing the package registers the route on ``nicegui.app``.

    Checked in a subprocess: the NiceGUI test fixtures strip every non-``/_nicegui/`` route
    before each test, so in-process this can only be observed on a fresh interpreter.
    """
    subprocess.run([sys.executable, '-c',
                    'import nicefabric\n'
                    'from nicegui import app\n'
                    'assert any(str(getattr(r, "path", "")) == "/_nicefabric/export/{token}"\n'
                    '           for r in app.routes)\n'], check=True, timeout=120)


async def test_export_reinstates_a_route_that_was_stripped(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """An app under test loses the import-time route to ``nicegui_reset_globals``."""
    await user.open('/')
    c = canvas_page()
    assert not _export_route_present()                 # the fixture removed it
    c.initialized = _already_initialized               # type: ignore[method-assign]
    _post_from_fake_browser(c, b'<svg/>')
    await c.to_svg(timeout=5)
    assert _export_route_present()
    await c.to_svg(timeout=5)                          # re-adding is idempotent, not cumulative
    assert len([r for r in app.routes if getattr(r, 'path', None) == _EXPORT_PATH]) == 1


async def test_export_endpoint_resolves_the_pending_future() -> None:
    future = _pend('tok')
    request, _ = _request(b'<svg/>')
    assert await _receive_export('tok', request) == {'ok': True}
    assert await future == '<svg/>'
    assert 'tok' not in _pending_exports          # consumed, one-time


async def test_export_endpoint_ignores_unknown_token() -> None:
    request, consumed = _request(b'x' * 100)
    assert await _receive_export('never-issued', request) == {'ok': False}
    assert consumed == []                         # body of an unknown token is never read


async def test_export_endpoint_ignores_replayed_token() -> None:
    future = _pend('tok')
    first, _ = _request(b'first')
    assert await _receive_export('tok', first) == {'ok': True}
    second, consumed = _request(b'second')
    assert await _receive_export('tok', second) == {'ok': False}
    assert await future == 'first'                # the replay did not overwrite the result
    assert consumed == []


async def test_export_endpoint_ignores_timed_out_token() -> None:
    """A POST arriving after the caller gave up must not raise InvalidStateError."""
    future = _pend('tok')
    future.cancel()
    request, _ = _request(b'<svg/>')
    assert await _receive_export('tok', request) == {'ok': False}


async def test_export_endpoint_tolerates_a_timeout_mid_upload() -> None:
    """The caller can give up between the token lookup and the last byte of the body."""
    future = _pend('tok')
    request, _ = _request(b'<svg/>', on_receive=future.cancel)
    assert await _receive_export('tok', request) == {'ok': False}   # not an InvalidStateError


async def test_export_endpoint_rejects_oversized_declared_body(monkeypatch: Any) -> None:
    monkeypatch.setattr('nicefabric.fabric_canvas._MAX_EXPORT_BYTES', 10)
    future = _pend('tok')
    request, consumed = _request(b'x' * 50)
    assert await _receive_export('tok', request) == {'ok': False}
    assert consumed == []                         # rejected on content-length, body never retained
    with pytest.raises(ValueError):
        await future


async def test_export_endpoint_stops_reading_an_oversized_stream(monkeypatch: Any) -> None:
    """A lying content-length must not get the body past the cap either."""
    monkeypatch.setattr('nicefabric.fabric_canvas._MAX_EXPORT_BYTES', 10)
    future = _pend('tok')
    request, consumed = _request(b'x' * 100, declared_length=1, chunk_size=5)
    assert await _receive_export('tok', request) == {'ok': False}
    assert sum(consumed) <= 15                    # stopped one chunk past the cap, not at 100 bytes
    with pytest.raises(ValueError):
        await future


async def test_export_endpoint_rejects_non_utf8_body() -> None:
    future = _pend('tok')
    request, _ = _request(b'\xff\xfe\x00binary')
    assert await _receive_export('tok', request) == {'ok': False}
    with pytest.raises(ValueError):
        await future


async def test_export_endpoint_reports_a_browser_side_failure() -> None:
    """A ``?error=1`` marker delivers the body as a RuntimeError instead of a result."""
    future = _pend('tok')
    request, _ = _request(b'canvas is tainted', query_string=b'error=1')
    assert await _receive_export('tok', request) == {'ok': True}
    with pytest.raises(RuntimeError, match='canvas is tainted'):
        await future


async def test_export_endpoint_keeps_concurrent_exports_apart() -> None:
    a, b = _pend('tok-a'), _pend('tok-b')
    request_b, _ = _request(b'B')
    request_a, _ = _request(b'A')
    await _receive_export('tok-b', request_b)
    await _receive_export('tok-a', request_a)
    assert (await a, await b) == ('A', 'B')


async def test_to_svg_awaits_the_http_result(user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    calls = _post_from_fake_browser(c, b'<svg>drawn</svg>')
    assert await c.to_svg(timeout=5) == '<svg>drawn</svg>'
    assert calls[0][0] == 'export_svg'
    assert not _pending_exports                        # token cleaned up


async def test_export_timeout_bounds_the_wait_for_initialization(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """``timeout`` must cover the whole call, not just the wait for the browser's POST.

    ``initialized()`` awaits ``client.connected()``, whose own default timeout is ``None`` — so
    an export fired when no client will ever connect (a background task after the tab closed, or
    a user-fixture test like this one) used to wait forever despite a documented timeout. The
    elapsed-time assertion is what distinguishes the fix from the bug: both raise
    ``asyncio.TimeoutError`` here, only one of them raises it at ``timeout``.
    """
    await user.open('/')
    c = canvas_page()
    assert not c.is_initialized                        # user fixture never runs JS
    started = asyncio.get_running_loop().time()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(c.to_svg(timeout=0.2), timeout=10)
    elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < 2, f'to_svg(timeout=0.2) took {elapsed:.1f}s — the outer guard fired, not it'


async def test_to_svg_surfaces_a_browser_side_export_failure(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """A failed browser-side export (e.g. a tainted canvas) fails fast instead of timing out."""
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    _post_from_fake_browser(c, b'canvas is tainted', failed=True)
    with pytest.raises(RuntimeError, match='canvas is tainted'):
        await c.to_svg(timeout=5)
    assert not _pending_exports                        # token still cleaned up on failure


async def test_to_data_url_passes_export_options(user: User,
                                                 canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    calls = _post_from_fake_browser(c, b'data:image/png;base64,AAA')
    assert await c.to_data_url(format='jpeg', quality=0.5, multiplier=2.0,
                               timeout=5) == 'data:image/png;base64,AAA'
    name, args = calls[0]
    assert name == 'export_data_url'
    assert args[1] == {'format': 'jpeg', 'quality': 0.5, 'multiplier': 2.0}


async def test_export_waits_for_init_before_calling_run_method(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """Pins the ``await self.initialized()`` guard in ``_export``: an export started before init
    must not reach ``run_method`` until ``_handle_init`` fires — every other export test stubs
    ``initialized()`` to be already-resolved, so deleting that line would leave them green."""
    await user.open('/')
    c = canvas_page()

    async def _already_connected() -> None:
        return None                            # isolates the test to the init-event half of the gate

    c.client.connected = _already_connected    # type: ignore[method-assign]
    export_calls: list[tuple] = []

    def fake_run_method(name: str, *args: Any, timeout: float = 1) -> NullResponse:
        export_calls.append((name, args))
        if name == 'export_svg':
            request, _ = _request(b'<svg/>')
            asyncio.create_task(_receive_export(args[0], request))
        return NullResponse()

    c.run_method = fake_run_method             # type: ignore[method-assign]
    task = asyncio.create_task(c.to_svg(timeout=5))
    await asyncio.sleep(0.05)
    assert export_calls == []                  # blocked on init — run_method never reached
    assert not task.done()

    c._handle_init()                           # unblocks initialized(); sync_objects also fires
    assert await task == '<svg/>'
    assert any(name == 'export_svg' for name, _ in export_calls)


async def test_export_cleans_up_its_token_on_timeout(user: User,
                                                     canvas_page: Callable[[], FabricCanvas]) -> None:
    """A browser that never POSTs must not leak an entry in the process-wide table."""
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    c.run_method = lambda *a, **kw: NullResponse()     # type: ignore[method-assign]
    with pytest.raises(asyncio.TimeoutError):
        await c.to_svg(timeout=0.05)
    assert not _pending_exports


async def _already_initialized() -> None:
    """Stand-in for ``FabricCanvas.initialized()``, which never resolves without a browser."""


def _post_from_fake_browser(canvas: FabricCanvas, body: bytes, *,
                             failed: bool = False) -> list[tuple[str, tuple]]:
    """Make ``run_method`` behave like a browser: POST ``body`` back to the export endpoint.

    :param failed: simulate the JS export throwing (e.g. a tainted canvas) — posts with the
        ``?error=1`` marker so the body is delivered as a ``RuntimeError`` instead of a result.
    """
    calls: list[tuple[str, tuple]] = []
    posts: list[asyncio.Task] = []          # keeps the tasks alive until they finish

    def fake_run_method(name: str, *args: Any, timeout: float = 1) -> NullResponse:
        calls.append((name, args))
        request, _ = _request(body, query_string=b'error=1' if failed else b'')
        posts.append(asyncio.create_task(_receive_export(args[0], request)))
        return NullResponse()

    canvas.run_method = fake_run_method                # type: ignore[method-assign]
    return calls


# --- SVG import ---
# `add_svg` sends the source to the browser, Fabric's parser runs there, and the parsed shapes
# come back through the same one-time-token HTTP channel the exports use. Everything below is
# the Python half: the browser is faked, and its answer is treated as hostile input, because a
# parsed SVG is exactly as untrusted as a `load_json` payload.


def _svg_payload(objects: list[dict], **options: Any) -> bytes:
    """One import result as the browser would POST it back: parsed shapes plus Fabric's options."""
    return json.dumps({'objects': objects, 'options': options}).encode()


def _import_from_fake_browser(canvas: FabricCanvas, body: bytes, *,
                              failed: bool = False) -> list[tuple[str, tuple]]:
    """Make ``run_method`` answer an ``import_svg`` call by POSTing ``body`` back.

    Unlike ``_post_from_fake_browser`` this answers *only* ``import_svg`` — ``add_svg`` also
    issues an ``add_objects`` call afterwards, whose first argument is a list of objects rather
    than an export token, and feeding that to the export endpoint would be nonsense.
    """
    calls: list[tuple[str, tuple]] = []
    posts: list[asyncio.Task] = []          # keeps the tasks alive until they finish

    def fake_run_method(name: str, *args: Any, timeout: float = 1) -> NullResponse:
        calls.append((name, args))
        if name == 'import_svg':
            request, _ = _request(body, query_string=b'error=1' if failed else b'')
            posts.append(asyncio.create_task(_receive_export(args[0], request)))
        return NullResponse()

    canvas.run_method = fake_run_method                # type: ignore[method-assign]
    return calls


async def test_add_svg_registers_parsed_shapes_and_returns_handles(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    calls = _import_from_fake_browser(c, _svg_payload(
        [{'type': 'Rect', 'left': 10, 'top': 20}, {'type': 'Circle', 'left': 30, 'radius': 5}],
        width=100, height=50))

    handles = await c.add_svg('<svg/>', timeout=5)

    assert [h.type for h in handles] == ['Rect', 'Circle']
    assert [o['type'] for o in c._objects.values()] == ['Rect', 'Circle']
    assert [h.props['left'] for h in handles] == [10, 30]        # absolute, as the parser baked them
    assert [name for name, _ in calls] == ['import_svg', 'add_objects']
    assert calls[0][1][1] == '<svg/>'                            # the source is sent as-is
    assert calls[1][1][0] == list(c._objects.values())           # the browser gets the id-stamped copies
    assert not _pending_exports


async def test_add_svg_appends_with_fresh_ids(user: User,
                                              canvas_page: Callable[[], FabricCanvas]) -> None:
    """Imported shapes join the canvas — they do not replace it — and cannot choose their id."""
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    existing = c.add_rect(left=1)
    _import_from_fake_browser(c, _svg_payload([{'type': 'Path', 'id': 'attacker-chosen',
                                                'path': 'M 0 0 L 1 1'}]))
    (handle,) = await c.add_svg('<svg/>', timeout=5)
    assert existing.id in c._objects                             # nothing was cleared
    assert handle.id != 'attacker-chosen' and len(handle.id) == 32
    assert list(c._objects) == [existing.id, handle.id]          # appended, in order
    assert all(key == o['id'] for key, o in c._objects.items())


async def test_add_svg_exposes_the_document_size(user: User,
                                                 canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    assert c.last_svg_size is None                               # nothing imported yet
    _import_from_fake_browser(c, _svg_payload([{'type': 'Rect'}], width=640, height=480.5))
    await c.add_svg('<svg/>', timeout=5)
    assert c.last_svg_size == (640, 480.5)


async def test_add_svg_reports_no_size_when_the_document_has_none(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """Fabric returns ``{}`` for options when the root element is not an ``<svg>``, and
    non-numeric or non-finite dimensions are just as unusable — all of them mean 'unknown'."""
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    for options in [{}, {'width': '100%', 'height': 50}, {'width': None, 'height': None},
                    {'width': float('nan'), 'height': 10}, {'width': True, 'height': True}]:
        _import_from_fake_browser(c, _svg_payload([], **options))
        await c.add_svg('<svg/>', timeout=5)
        assert c.last_svg_size is None, options


async def test_add_svg_applies_the_load_json_validation(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """Parsed shapes go through exactly the checks a ``load_json`` payload goes through."""
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    _import_from_fake_browser(c, _svg_payload([
        {'type': 'Rect'},
        {'type': 'Group', 'objects': []},                          # unsupported type → dropped
        {'type': 'Image', 'src': 'javascript:alert(1)'},           # bad scheme → dropped
        {'type': 'Rect', 'clipPath': {'type': 'Image', 'src': 'javascript:alert(1)'}},  # nested
        'not-a-dict',                                              # → dropped
        {'type': 'Image', 'src': 'https://ok.example/x.png'},
    ]))
    handles = await c.add_svg('<svg/>', timeout=5)
    assert [h.type for h in handles] == ['Rect', 'Image']
    assert handles[1].props['crossOrigin'] == 'anonymous'          # add_image's default


async def test_add_svg_enforces_the_object_cap(user: User,
                                               canvas_page: Callable[[], FabricCanvas]) -> None:
    """A document that explodes into 10 000 shapes must be refused, not registered."""
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    _import_from_fake_browser(c, _svg_payload([{'type': 'Rect'}] * 10_000, width=10, height=10))
    with pytest.raises(ValueError):
        await c.add_svg('<svg/>', timeout=5)
    assert c._objects == {}                                        # nothing was applied
    assert c.last_svg_size is None                                 # a refused import leaves no trace


async def test_add_svg_cap_counts_the_objects_already_on_the_canvas(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """The cap is on the registry, so an import cannot walk it up one document at a time."""
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    c.load_json({'objects': [{'type': 'Rect'}] * (_MAX_OBJECTS - 1)})
    _import_from_fake_browser(c, _svg_payload([{'type': 'Rect'}, {'type': 'Rect'}]))
    with pytest.raises(ValueError):
        await c.add_svg('<svg/>', timeout=5)
    assert len(c._objects) == _MAX_OBJECTS - 1                     # nothing was applied
    _import_from_fake_browser(c, _svg_payload([{'type': 'Rect'}]))
    assert len(await c.add_svg('<svg/>', timeout=5)) == 1          # exactly at the cap is fine
    assert len(c._objects) == _MAX_OBJECTS


async def test_add_svg_negative_budget_message_is_sensible(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """``add_rect``/friends are uncapped, so the registry can already be past ``_MAX_OBJECTS``
    by the time ``add_svg`` computes its budget as ``_MAX_OBJECTS - len(self._objects)`` — a
    negative number. Even an *empty* import must not read as nonsense like 'has room for -3'."""
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    for _ in range(_MAX_OBJECTS + 3):
        c.add_rect()
    _import_from_fake_browser(c, _svg_payload([]))                 # empty — still over budget
    with pytest.raises(ValueError) as exc_info:
        await c.add_svg('<svg/>', timeout=5)
    message = str(exc_info.value)
    assert '-' not in message, message
    assert str(_MAX_OBJECTS + 3) in message


async def test_add_svg_rejects_an_oversized_source(user: User,
                                                   canvas_page: Callable[[], FabricCanvas]) -> None:
    """Refused in Python, before anything is sent to the browser."""
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    calls = _import_from_fake_browser(c, _svg_payload([]))
    with pytest.raises(ValueError):
        await c.add_svg('<svg>' + '\U0001f389' * 300_000 + '</svg>', timeout=5)   # 4 bytes each
    assert calls == []                                             # never left the server
    assert not _pending_exports


async def test_add_svg_returns_empty_for_a_document_with_no_shapes(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """Malformed source and a genuinely empty document are the same thing at Fabric's boundary:
    ``loadSVGFromString`` returns no objects for both, so ``add_svg`` returns ``[]``."""
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    r = c.add_rect()
    calls = _import_from_fake_browser(c, _svg_payload([]))
    assert await c.add_svg('this is not an svg at all', timeout=5) == []
    assert list(c._objects) == [r.id]                              # registry untouched
    assert [name for name, _ in calls] == ['import_svg']           # no pointless add_objects


async def test_add_svg_rejects_a_hostile_browser_answer(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """The body is JSON from the browser: everything about it can be a lie."""
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    for body in [b'not json at all', b'5', b'"a string"', b'{"objects": 5}',
                 b'{"objects": "a string"}', b'{}',
                 b'[' * 10_000 + b']' * 10_000]:                # RecursionError, not ValueError
        _import_from_fake_browser(c, body)
        with pytest.raises(ValueError):
            await c.add_svg('<svg/>', timeout=5)
        assert c._objects == {}
    assert not _pending_exports


async def test_add_svg_rejects_an_oversized_browser_answer(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """The parsed *answer* has its own cap, separate from and bigger than the source cap, and it
    is enforced on raw bytes before ``json.loads``/``deepcopy`` ever see them — see
    ``_MAX_SVG_RESULT_BYTES``. Without this check the only bound left is ``_MAX_EXPORT_BYTES``
    (64 MB): this payload sits comfortably under that outer cap, so it proves the gap it closes.
    """
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    oversized = json.dumps({'objects': [{'type': 'Rect'}],
                            'options': {'padding': 'x' * (_MAX_SVG_RESULT_BYTES + 1)}}).encode()
    assert _MAX_SVG_RESULT_BYTES < len(oversized) < _MAX_EXPORT_BYTES
    _import_from_fake_browser(c, oversized)
    with pytest.raises(ValueError, match=str(_MAX_SVG_RESULT_BYTES)):
        await c.add_svg('<svg/>', timeout=5)
    assert c._objects == {}
    assert c.last_svg_size is None
    assert not _pending_exports


async def test_add_svg_converts_deepcopy_recursion_error_to_value_error(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """Same underlying fix as ``load_json``'s sibling test, exercised through ``add_svg``'s own
    call site: a payload shallow enough to survive ``json.loads`` but deep enough to overflow
    ``copy.deepcopy`` inside ``_clean_objects`` must still raise ``ValueError``."""
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    nested: Any = 'leaf'
    for _ in range(600):
        nested = [nested]
    _import_from_fake_browser(c, _svg_payload([{'type': 'Rect', 'junk': nested}]))
    with pytest.raises(ValueError):
        await c.add_svg('<svg/>', timeout=5)
    assert c._objects == {}


async def test_add_svg_surfaces_a_browser_side_failure(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    await user.open('/')
    c = canvas_page()
    c.initialized = _already_initialized               # type: ignore[method-assign]
    _import_from_fake_browser(c, b'DOMParser exploded', failed=True)
    with pytest.raises(RuntimeError, match='DOMParser exploded'):
        await c.add_svg('<svg/>', timeout=5)
    assert c._objects == {}
    assert not _pending_exports


async def test_add_svg_timeout_bounds_the_wait_for_initialization(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """Same contract as the exports: ``timeout`` covers the wait for a client too, so an import
    fired where no browser will ever connect raises at ``timeout`` instead of hanging."""
    await user.open('/')
    c = canvas_page()
    assert not c.is_initialized                        # the user fixture never runs JS
    started = asyncio.get_running_loop().time()
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(c.add_svg('<svg/>', timeout=0.2), timeout=10)
    elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < 2, f'add_svg(timeout=0.2) took {elapsed:.1f}s — the outer guard fired, not it'
    assert not _pending_exports


async def test_moving_is_off_unless_a_handler_is_given(user: User) -> None:
    """The continuous stream is opt-in: one socket message per mousemove is not a default."""
    canvases: list[FabricCanvas] = []

    @ui.page('/')
    def page() -> None:
        canvases.append(FabricCanvas())
        canvases.append(FabricCanvas(on_moving=lambda e: None))
        canvases.append(FabricCanvas(on_moving=lambda e: None, moving_interval=0.2))

    await user.open('/')
    quiet, live, slow = canvases
    assert quiet._props['movingInterval'] == 0
    assert live._props['movingInterval'] == 50            # 0.05 s default
    assert slow._props['movingInterval'] == 200


async def test_moving_updates_the_registry_like_modified(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """A drag must keep Python's registry current, so a mid-drag to_dict() is not stale."""
    await user.open('/')
    c = canvas_page()
    r = c.add_rect(left=0, top=0)
    c._on_modified(_ev(c, {'id': r.id, 'props': {'left': 120, 'top': 80, 'fill': 'green'}}))
    entry = c._objects[r.id]
    assert (entry['left'], entry['top']) == (120, 80)
    assert entry.get('fill') != 'green'                   # geometry only, same gate as modified


async def test_leading_underscore_props_are_not_flagged_as_snake_case(
        user: User, canvas_page: Callable[[], FabricCanvas]) -> None:
    """Fabric's own internals are `_camelCase` (e.g. `_controlsVisibility`) — warning on those
    trains users to ignore the warning that catches real snake_case slips."""
    await user.open('/')
    c = canvas_page()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        c.add_rect(_controlsVisibility={'ml': True})
    assert not caught
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        c.add_rect(stroke_width=2)
    assert len(caught) == 1 and 'strokeWidth' in str(caught[0].message)
