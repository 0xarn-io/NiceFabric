"""Browser end-to-end tests for NiceFabric.

Run standalone::

    python tests/e2e_playwright.py

or through pytest (the file is not collected by ``pytest tests/`` — its name does not match
``test_*.py``, so it has to be named explicitly)::

    pytest tests/e2e_playwright.py -m e2e

Chromium is expected to be pre-installed (``PLAYWRIGHT_BROWSERS_PATH``); never run
``playwright install`` here.

Two servers are started for the duration of a run:

* the shipped demo, launched exactly as a user launches it (``python examples/main.py``, port
  8080), so the demo itself is covered;
* a *probe* server (this same file, ``--probe-server``) whose pages dump the Python-side
  registry into the DOM — the demo has no such hook, and the interesting claims of this suite
  are about what the registry ends up holding.

A third, non-NiceGUI HTTP server runs in-process and serves one PNG. It exists only to give the
probe pages a genuinely cross-origin image (different host *and* port), which is what taints a
canvas and makes ``toDataURL`` throw — the trigger for the export *failure* path.
"""
from __future__ import annotations

import base64
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
from playwright.sync_api import Browser, Page, sync_playwright

REPO = Path(__file__).resolve().parent.parent
DEMO_PORT = 8080          # fixed by examples/main.py's own ui.run()
PROBE_PORT = 8611
IMAGE_PORT = 8613
DEMO_URL = f'http://localhost:{DEMO_PORT}'
PROBE_URL = f'http://localhost:{PROBE_PORT}'
IMAGE_URL = f'http://127.0.0.1:{IMAGE_PORT}/probe.png'   # 127.0.0.1 != localhost -> cross-origin

# 1x1 red PNG, scaled up on the canvas; only its origin matters.
_RED_PIXEL_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')

DEMO_BACKGROUND = (248, 250, 252)     # '#f8fafc' from examples/main.py
WHITE = (255, 255, 255)

# The document the '/svg' probe page imports. Two of its three shapes are nested in a translated
# <g>, which Fabric bakes into each object and then discards — so the registry must end up with
# three flat objects at absolute positions. Fabric 7 positions from the CENTRE, so the expected
# left/top below are shape centres: the rect's is (0+60/2, 0+40/2) + (100, 40), the circle's is
# its (cx, cy) + (100, 40), and the untransformed triangle's is its bounding-box centre.
SVG_SOURCE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="140" viewBox="0 0 220 140">'
    '<g transform="translate(100, 40)">'
    '<rect x="0" y="0" width="60" height="40" fill="#ff0000"/>'
    '<circle cx="20" cy="80" r="20" fill="#0000ff"/>'
    '</g>'
    '<path d="M 10 10 L 60 10 L 60 30 Z" fill="#00ff00"/>'
    '</svg>')
SVG_EXPECTED = [('Rect', 130, 60), ('Circle', 120, 120), ('Path', 35, 20)]
# An <image> Fabric cannot load rejects the WHOLE parse (observed on 7.4.0: the parser
# dereferences the null object it just failed to build). The data URL keeps that off the
# network, so the failure is immediate and deterministic rather than a connection timeout.
SVG_UNLOADABLE_IMAGE = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
    '<image href="data:image/png;base64,notreallybase64" width="5" height="5"/>'
    '<rect width="5" height="5"/></svg>')
SVG_PIXELS = (3200, 5600)             # 60x40 rect + r=20 circle + a 500px triangle, ~4157 nominal

# Overridable so CI can widen the budget for gates that depend on the ~2s init handshake
# (window.socket.id poll + websocket connect) without editing code. 20s matches what has been
# observed to be comfortable on an unloaded local machine.
E2E_TIMEOUT = float(os.environ.get('E2E_TIMEOUT', '20'))


# --------------------------------------------------------------------------- probe server


def _probe_pages() -> None:
    """Register the probe pages. Runs in the ``--probe-server`` subprocess only.

    Every page follows the same two rules, because breaking them makes mouse-driven tests
    flaky: readouts are placed *below* the canvas and start out non-empty. A label that grows
    from '' to one line above the canvas pushes the canvas ~21px down, and every coordinate
    measured before that lands somewhere else (observed: a click meant for scene y=100 arrived
    at y=79).
    """
    from nicegui import ui

    from nicefabric import FabricCanvas

    @ui.page('/multi-select')
    def multi_select() -> None:
        """Three rects at known absolute positions, plus a live dump of the registry.

        Fabric 7 positions objects from their centre, so these 50x50 rects are centred on
        (100, 100), (300, 100) and (500, 100) — that is where the tests have to click.
        """
        # both readouts append rather than replace: a test that only ever sees the latest event
        # cannot tell "never happened" from "happened and was undone", and the difference is
        # exactly what goes wrong when a click misses
        canvas = FabricCanvas(width=600, height=400, background='#ffffff',
                              on_selection=lambda e: selection.set_text(
                                  f'{selection.text}|{e.args["kind"]}:{len(e.args["ids"])}'),
                              on_mouse_down=lambda e: pointer.set_text(
                                  f'{pointer.text}|{e.args["x"]:.0f},{e.args["y"]:.0f}'
                                  f',{e.args["id"] is not None}'))
        canvas.add_rect(left=100, top=100, width=50, height=50, fill='red')
        canvas.add_rect(left=300, top=100, width=50, height=50, fill='blue')
        canvas.add_rect(left=500, top=100, width=50, height=50, fill='green')  # deselect by proxy
        selection = ui.label('sel').classes('selection')
        pointer = ui.label('down').classes('pointer')
        dump = ui.label('-').classes('registry-dump')
        ui.timer(0.2, lambda: dump.set_text(canvas.to_json()))

    @ui.page('/draw')
    def draw() -> None:
        """Free-drawing canvas whose registry can be inspected, and round-tripped on demand."""
        canvas = FabricCanvas(width=400, height=300, background='#ffffff',
                              on_error=lambda e: errors.set_text(f'{errors.text} {e.args}'))
        errors = ui.label('none').classes('errors')
        status = ui.label('idle').classes('status')
        dump = ui.label('-').classes('registry-dump')
        ui.timer(0.2, lambda: dump.set_text(canvas.to_json()))
        canvas.enable_drawing('#ff0000', 5)      # set before init: replayed by the init handshake

        def geometry() -> list:
            return [[o.get('type'), round(o.get('left', 0), 2), round(o.get('top', 0), 2),
                     round(o.get('width', 0), 2), round(o.get('height', 0), 2)]
                    for o in canvas.to_dict()['objects']]

        async def roundtrip() -> None:
            """to_dict() -> clear_objects() -> load_json(), comparing the rendered pixels."""
            status.set_text('running')
            try:
                before_png = await canvas.to_data_url(timeout=20)
                before_geometry = geometry()
                data = canvas.to_dict()
                canvas.clear_objects()
                canvas.load_json(data)
                # the browser applies clear/sync_objects before this export: all three are
                # enqueued on the same JS promise chain, in the order Python issued them
                after_png = await canvas.to_data_url(timeout=20)
                same = 'SAME' if before_png == after_png else 'DIFF'
                status.set_text(f'{same} n={len(geometry())} '
                                f'before={json.dumps(before_geometry)} after={json.dumps(geometry())}')
            except Exception as e:                                    # noqa: BLE001 - reported to the test
                status.set_text(f'EXC {type(e).__name__}: {e}')

        ui.button('roundtrip', on_click=roundtrip).classes('roundtrip-btn')

    @ui.page('/svg')
    def svg_import() -> None:
        """SVG import: browser-side parse -> HTTP POST -> the Python registry, then a round trip.

        The document deliberately nests two of its three shapes in a translated ``<g>``: what
        must land in the registry is three *flat* objects carrying absolute coordinates, since
        Fabric bakes parent transforms in and throws the group away.
        """
        canvas = FabricCanvas(width=300, height=200, background='#ffffff',
                              on_error=lambda e: errors.set_text(f'{errors.text} {e.args}'))
        errors = ui.label('none').classes('errors')
        status = ui.label('idle').classes('status')
        dump = ui.label('-').classes('registry-dump')
        ui.timer(0.2, lambda: dump.set_text(canvas.to_json()))

        async def run(what: Callable[[], Any]) -> None:
            status.set_text('running')
            try:
                status.set_text(await what())
            except Exception as e:                                    # noqa: BLE001 - reported to the test
                status.set_text(f'EXC {type(e).__name__}: {e}')

        async def import_svg() -> str:
            objects = await canvas.add_svg(SVG_SOURCE, timeout=20)
            return (f'OK n={len(objects)} types={",".join(o.type for o in objects)} '
                    f'size={canvas.last_svg_size}')

        async def import_garbage() -> str:
            """The judgment call under test: a document the XML parser rejects returns []."""
            objects = await canvas.add_svg('<not-an-svg ka-boom', timeout=20)
            return f'BAD n={len(objects)} size={canvas.last_svg_size} kept={len(canvas.to_dict()["objects"])}'

        async def import_unloadable_image() -> str:
            objects = await canvas.add_svg(SVG_UNLOADABLE_IMAGE, timeout=20)
            return f'UNEXPECTED_OK n={len(objects)}'

        async def roundtrip() -> str:
            """to_dict() -> clear_objects() -> load_json(), comparing the rendered pixels."""
            before_png = await canvas.to_data_url(timeout=20)
            data = canvas.to_dict()
            canvas.clear_objects()
            canvas.load_json(data)
            after_png = await canvas.to_data_url(timeout=20)
            return (f'{"SAME" if before_png == after_png else "DIFF"} '
                    f'n={len(canvas.to_dict()["objects"])}')

        ui.button('import', on_click=lambda: run(import_svg)).classes('import-btn')
        ui.button('garbage', on_click=lambda: run(import_garbage)).classes('garbage-btn')
        ui.button('unloadable', on_click=lambda: run(import_unloadable_image)).classes('image-btn')
        ui.button('roundtrip', on_click=lambda: run(roundtrip)).classes('roundtrip-btn')

    @ui.page('/export')
    def export() -> None:
        """Export success path: the browser renders and POSTs the result back."""
        canvas = FabricCanvas(width=400, height=300, background='#ffffff')
        canvas.add_rect(left=50, top=60, width=100, height=80, fill='#ff0000')
        result = ui.label('idle').classes('result')
        # the full data URL, so the test can decode the PNG itself rather than trust a byte
        # count; kept off the '.result' summary label to keep that one short and regex-friendly
        raw_url = ui.label('').classes('raw-url')

        async def png() -> None:
            try:
                url = await canvas.to_data_url(timeout=20)
                raw = base64.b64decode(url.split(',', 1)[1])
                result.set_text(f'PNG prefix={url[:22]} magic={raw[:4].hex()} '
                                f'size={int.from_bytes(raw[16:20], "big")}x'
                                f'{int.from_bytes(raw[20:24], "big")} bytes={len(raw)}')
                raw_url.set_text(url)
            except Exception as e:                                    # noqa: BLE001 - reported to the test
                result.set_text(f'EXC {type(e).__name__}: {e}')

        async def svg() -> None:
            # reset first: '.result' still holds the PNG summary from the button above, and the
            # test needs a value it knows can only mean "the SVG click's own result is in"
            result.set_text('idle')
            try:
                src = await canvas.to_svg(timeout=20)
                flat = src.replace(' ', '')
                result.set_text(f'SVG len={len(src)} root={src.count("<svg")} '
                                f'rects={src.count("<rect")} red={"rgb(255,0,0)" in flat}')
            except Exception as e:                                    # noqa: BLE001 - reported to the test
                result.set_text(f'EXC {type(e).__name__}: {e}')

        ui.button('png', on_click=png).classes('png-btn')
        ui.button('svg', on_click=svg).classes('svg-btn')

    @ui.page('/taint')
    def taint() -> None:
        """Export failure path: a cross-origin image without CORS taints the canvas."""
        canvas = FabricCanvas(width=300, height=200, background='#ffffff',
                              on_error=lambda e: errors.set_text(f'{errors.text} {e.args}'))
        # add_object, not add_image: add_image would default crossOrigin to 'anonymous' and the
        # image would simply fail to load instead of tainting the canvas
        canvas.add_object('Image', src=IMAGE_URL, left=10, top=10, scaleX=200, scaleY=150)
        errors = ui.label('none').classes('errors')
        result = ui.label('idle').classes('result')

        async def png() -> None:
            try:
                # a generous timeout on purpose: the test asserts the failure comes back long
                # before it, i.e. that ?error=1 short-circuits instead of running out the clock
                url = await canvas.to_data_url(timeout=30)
                result.set_text(f'UNEXPECTED_OK len={len(url)}')
            except Exception as e:                                    # noqa: BLE001 - reported to the test
                result.set_text(f'{type(e).__name__}: {e}')

        ui.button('png', on_click=png).classes('png-btn')


def _run_probe_server() -> None:
    sys.path.insert(0, str(REPO))
    from nicegui import ui
    _probe_pages()
    ui.run(show=False, port=PROBE_PORT, reload=False, show_welcome_message=False)


# --------------------------------------------------------------------------- server plumbing


class _ImageHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:                                          # noqa: N802 - BaseHTTPRequestHandler API
        self.send_response(200)
        self.send_header('Content-Type', 'image/png')
        self.send_header('Content-Length', str(len(_RED_PIXEL_PNG)))
        self.end_headers()                    # deliberately no Access-Control-Allow-Origin
        self.wfile.write(_RED_PIXEL_PNG)

    def log_message(self, *args: Any) -> None:
        pass


def _port_is_free(port: int) -> bool:
    """True if nothing is listening on ``port``.

    ``SO_REUSEADDR`` is set so a port merely sitting in ``TIME_WAIT`` after a previous run
    counts as free — only a live listener makes ``bind`` fail.
    """
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def _wait_for_server(url: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1).read()
            return
        except urllib.error.HTTPError:
            return                            # answered, even if not with a 200
        except Exception:                     # noqa: BLE001 - not up yet
            time.sleep(0.2)
    raise TimeoutError(f'server at {url} did not start within {timeout}s')


@contextmanager
def running_servers() -> Iterator[None]:
    """Start the demo, the probe server and the cross-origin image server; stop them all after."""
    for port in (DEMO_PORT, PROBE_PORT, IMAGE_PORT):
        assert _port_is_free(port), f'port {port} is already in use'
    images = ThreadingHTTPServer(('127.0.0.1', IMAGE_PORT), _ImageHandler)
    threading.Thread(target=images.serve_forever, daemon=True).start()
    # NiceGUI's ui.run() switches to its screen-test branch when PYTEST_CURRENT_TEST is set and
    # then demands NICEGUI_SCREEN_TEST_PORT — the servers must not inherit it from a pytest run
    env = {k: v for k, v in os.environ.items() if k != 'PYTEST_CURRENT_TEST'}
    # start_new_session so the demo's auto-reload child dies with its parent
    demo = subprocess.Popen([sys.executable, 'examples/main.py'], cwd=REPO, env=env,
                            start_new_session=True)
    probe = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--probe-server'],
                             cwd=REPO, env=env, start_new_session=True)
    try:
        _wait_for_server(f'{DEMO_URL}/')
        _wait_for_server(f'{PROBE_URL}/export')
        _wait_for_server(IMAGE_URL)
        yield
    finally:
        for proc in (demo, probe):
            try:
                os.killpg(os.getpgid(proc.pid), 15)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), 9)
        images.shutdown()
        images.server_close()
        for port in (DEMO_PORT, PROBE_PORT, IMAGE_PORT):
            deadline = time.monotonic() + 10
            while not _port_is_free(port) and time.monotonic() < deadline:
                time.sleep(0.2)
            assert _port_is_free(port), f'port {port} is still open after shutdown'


# --------------------------------------------------------------------------- page helpers


@dataclass
class Probe:
    """One browser page plus everything the browser complained about while it was open."""

    page: Page
    problems: list[str] = field(default_factory=list)

    def open(self, url: str) -> 'Probe':
        self.page.on('pageerror', lambda e: self.problems.append(f'pageerror: {e}'))
        self.page.on('console', lambda m: m.type == 'error' and self.problems.append(
            f'console.error: {m.text}'))
        self.page.goto(url)
        self.page.wait_for_selector('div.canvas-container')
        return self

    def box(self) -> dict:
        box = self.page.locator('canvas.upper-canvas').bounding_box()
        assert box is not None, 'upper canvas has no bounding box'
        return box

    def registry(self) -> list[dict]:
        return json.loads(self.page.locator('.registry-dump').inner_text())['objects']

    def painted_pixels(self, background: tuple[int, int, int]) -> int:
        """Count pixels on the rendered canvas that differ from the background colour.

        Careful with the result: a canvas element that Fabric has not painted yet is
        transparent, so *every* pixel differs from the background and this returns the full
        pixel count. Any 'is it drawn yet?' gate therefore needs an upper bound as well — see
        ``wait_for_render``.
        """
        return self.page.evaluate(
            """([r, g, b]) => {
                const c = document.querySelector('canvas.lower-canvas');
                const d = c.getContext('2d', {willReadFrequently: true})
                           .getImageData(0, 0, c.width, c.height).data;
                let n = 0;
                for (let i = 0; i < d.length; i += 4)
                    if (d[i] !== r || d[i + 1] !== g || d[i + 2] !== b) n++;
                return n;
            }""", list(background))

    def text_of(self, selector: str) -> str:
        return self.page.locator(selector).inner_text()

    def assert_clean_console(self) -> None:
        assert not self.problems, f'browser reported: {self.problems}'


def wait_until(condition: Callable[[], Any], what: str, timeout: float = E2E_TIMEOUT,
               diagnose: Callable[[], Any] | None = None) -> Any:
    """Poll ``condition`` until it returns something truthy. Returns that value.

    Polling a condition, rather than sleeping a guessed amount, is what keeps this suite
    honest on a slow CI box. ``diagnose`` is called once on failure to enrich the message.
    """
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = condition()
            if last:
                return last
        except Exception as e:                # noqa: BLE001 - the DOM may not be ready yet
            last = f'{type(e).__name__}: {e}'
        time.sleep(0.1)
    extra = ''
    if diagnose is not None:
        try:
            extra = f'; state: {diagnose()!r}'
        except Exception as e:                # noqa: BLE001 - diagnostics must not mask the timeout
            extra = f'; diagnosis failed: {e}'
    raise AssertionError(f'timed out after {timeout}s waiting for {what} (last: {last!r}){extra}')


def draw_stroke(probe: Probe, points: list[tuple[float, float]]) -> None:
    """Drag the mouse across the canvas in canvas-relative coordinates."""
    box = probe.box()
    mouse = probe.page.mouse
    mouse.move(box['x'] + points[0][0], box['y'] + points[0][1])
    mouse.down()
    for x, y in points[1:]:
        mouse.move(box['x'] + x, box['y'] + y, steps=10)
    mouse.up()


def wait_for_render(probe: Probe, background: tuple[int, int, int],
                    low: int, high: int, what: str) -> int:
    """Wait until the painted-pixel count settles inside ``[low, high]``.

    Both bounds matter. Below, because Fabric only draws the objects once Python's ``init``
    handshake has completed (about two seconds after mount here, while the websocket connects);
    above, because an unpainted canvas is transparent and would otherwise sail through any
    'more than N pixels differ' test — which is how an earlier version of this suite managed to
    click on an empty canvas and still believe two rects were there.
    """
    seen: list[int] = []

    def rendered() -> bool:
        seen.append(probe.painted_pixels(background))
        return low <= seen[-1] <= high

    wait_until(rendered, what, diagnose=lambda: f'last painted-pixel counts: {seen[-3:]}')
    return seen[-1]


def wait_for_draw_mode(probe: Probe) -> None:
    """Block until the browser really is in free-drawing mode.

    ``enable_drawing`` is a fire-and-forget message to the browser, so a stroke sent too early
    would be a rubber-band selection instead of a path. Fabric sets ``freeDrawingCursor`` on the
    upper canvas while drawing mode is on, and it does so from the mouse-move handler — hence
    the nudge before each read. This is a condition, not a sleep.
    """
    box = probe.box()
    cursor = "() => document.querySelector('canvas.upper-canvas').style.cursor"
    for i in range(200):
        probe.page.mouse.move(box['x'] + 10 + i % 20, box['y'] + 10)
        if probe.page.evaluate(cursor) == 'crosshair':
            return
        time.sleep(0.1)
    raise AssertionError(f'drawing mode never became active (cursor={probe.page.evaluate(cursor)!r})')


# --------------------------------------------------------------------------- checks
# Each check takes a fresh Probe. They are shared by the pytest tests and by main().


def check_demo_mounts_and_adds_shapes(probe: Probe) -> None:
    """Canvas mounts at the size the demo asked for, and Python->JS add actually paints."""
    probe.open(f'{DEMO_URL}/')
    box = probe.box()
    assert (box['width'], box['height']) == (800, 450), box
    assert probe.page.evaluate(
        "() => [document.querySelector('canvas.lower-canvas').width, "
        "document.querySelector('canvas.lower-canvas').height]") == [800, 450]

    wait_for_render(probe, DEMO_BACKGROUND, 0, 0, 'an empty canvas painted in its background')
    probe.page.get_by_role('button', name='Rect', exact=True).click()
    # the demo drops an 80x60 rect at a random position, and Fabric 7 positions from the
    # object's CENTRE — so at left=0/top=0 only a quarter of it (1200px) is on the canvas
    wait_for_render(probe, DEMO_BACKGROUND, 1200, 5200, 'one 80x60 rect worth of pixels')
    probe.assert_clean_console()


def check_demo_free_draw_reaches_python(probe: Probe) -> None:
    """A stroke drawn in the browser round-trips to the demo's on_added handler."""
    probe.open(f'{DEMO_URL}/')
    wait_for_render(probe, DEMO_BACKGROUND, 0, 0, 'an empty canvas painted in its background')
    probe.page.get_by_text('draw', exact=True).click()
    wait_for_draw_mode(probe)
    draw_stroke(probe, [(300, 300), (380, 360), (420, 300)])
    probe.page.wait_for_selector('text=drawn:', timeout=15_000)
    log = probe.page.locator('text=drawn:').first.inner_text()
    assert re.search(r'drawn: [0-9a-f]{8}', log), log
    painted = probe.painted_pixels(DEMO_BACKGROUND)
    assert 100 < painted < 40_000, f'the stroke should be visible on the canvas, painted={painted}'
    probe.assert_clean_console()


def check_demo_export_downloads_png(probe: Probe) -> None:
    """Export PNG: browser render -> HTTP POST -> ui.download, end to end."""
    probe.open(f'{DEMO_URL}/')
    wait_for_render(probe, DEMO_BACKGROUND, 0, 0, 'an empty canvas painted in its background')
    probe.page.get_by_role('button', name='Rect', exact=True).click()
    wait_for_render(probe, DEMO_BACKGROUND, 1200, 5200, 'the rect to be painted')
    with probe.page.expect_download(timeout=45_000) as download:
        probe.page.get_by_role('button', name='Export PNG').click()
    raw = Path(download.value.path()).read_bytes()
    assert download.value.suggested_filename == 'canvas.png', download.value.suggested_filename
    assert raw[:4] == b'\x89PNG', raw[:8]
    width, height = int.from_bytes(raw[16:20], 'big'), int.from_bytes(raw[20:24], 'big')
    assert (width, height) == (800, 450), (width, height)
    assert len(raw) > 1000, len(raw)
    probe.assert_clean_console()


def _group_two_rects_and_drag(probe: Probe) -> dict:
    """Shift-select the red and blue rects, drag the pair down 100px. Returns the canvas box.

    Shared by the two multi-select checks, which differ only in how the group is dismissed —
    and that is the interesting part, because the JS side syncs member coordinates from
    ``selection:cleared`` *and* ``selection:updated``.
    """
    probe.open(f'{PROBE_URL}/multi-select')
    # 3 x 50 x 50 painted means the browser really has the rects; clicking before that is
    # clicking on an empty canvas, and every assertion below becomes meaningless
    wait_for_render(probe, WHITE, 7400, 9000, 'all three rects to be rendered')
    start = wait_until(lambda: probe.registry() or None, 'the registry dump')
    assert sorted(round(r['left']) for r in start) == [100, 300, 500], start
    assert [round(r['top']) for r in start] == [100, 100, 100], start

    page = probe.page
    box = probe.box()                                         # after the page has settled
    page.mouse.click(box['x'] + 100, box['y'] + 100)          # centre of the red rect
    # the canvas maps that click to scene (100, 100) AND finds an object there; without this
    # the clicks below could all be landing on empty canvas and the test would never say so
    down = wait_until(lambda: probe.text_of('.pointer') != 'down' and probe.text_of('.pointer'),
                      'the mouse-down round trip')
    assert down.endswith('|100,100,True'), f'the click missed the red rect: {down}'

    page.keyboard.down('Shift')
    page.mouse.click(box['x'] + 300, box['y'] + 100)          # centre of the blue one
    page.keyboard.up('Shift')
    # two ids in one selection == Fabric built an ActiveSelection; dragging before that would
    # move a single rect and quietly turn this into a different (much weaker) test
    wait_until(lambda: probe.text_of('.selection').endswith(':2'),
               'both rects to end up in one selection',
               diagnose=lambda: (probe.text_of('.selection'), probe.text_of('.pointer')))

    page.mouse.move(box['x'] + 100, box['y'] + 100)           # grab inside the selection
    page.mouse.down()
    page.mouse.move(box['x'] + 100, box['y'] + 200, steps=20)  # drag both down 100px
    page.mouse.up()
    return box


def _assert_dragged_pair_synced(probe: Probe) -> None:
    """The red and blue rects must now be at their ABSOLUTE positions, 100px lower."""
    rects = wait_until(lambda: [r for r in [probe.registry()]
                                if len(r) == 3 and sum(o['top'] != 100 for o in r) == 2],
                       'the dragged rects to be synced back',
                       diagnose=probe.registry)[0]
    moved = [r for r in rects if round(r['top']) != 100]
    lefts = sorted(round(r['left']) for r in moved)
    tops = [round(r['top']) for r in moved]
    assert lefts == [100, 300], f'ABSOLUTE coords expected, got lefts={lefts} (rects={rects})'
    assert all(abs(t - 200) <= 5 for t in tops), f'both moved +100px, got tops={tops}'
    # the rect that was never touched must not have been dragged along by the sync
    untouched = [r for r in rects if round(r['top']) == 100]
    assert [round(r['left']) for r in untouched] == [500], untouched
    probe.assert_clean_console()


def check_multi_select_sync_on_cleared(probe: Probe) -> None:
    """ActiveSelection members are synced in ABSOLUTE coordinates when the selection is cleared."""
    box = _group_two_rects_and_drag(probe)
    probe.page.mouse.click(box['x'] + 550, box['y'] + 380)    # empty corner -> selection:cleared
    _assert_dragged_pair_synced(probe)


def check_multi_select_sync_on_updated(probe: Probe) -> None:
    """Same, but one member is shift-clicked out of a group that stays alive.

    This pins the JS side's member-coordinate sync to the ``selection:updated`` branch, not just
    ``selection:cleared``: blue leaves the ActiveSelection and must come back with absolute
    ``left``/``top`` while red, still selected, must NOT have been touched yet. Fabric does not
    take this path when another object is clicked instead — that fires ``selection:cleared``
    followed by ``created``.

    What this does *not* pin down, despite appearances: the JS side also has a ``setTimeout(0)``
    next-tick read and a ``!o.group`` guard, seemingly there to handle the moment blue leaves the
    selection while its coordinates are still group-relative. Temporary instrumentation inside
    ``syncDeselected`` on Fabric 7.4.0 showed that by the time either ``selection:cleared`` or
    ``selection:updated`` actually fires, Fabric has already restored absolute coordinates and
    already cleared ``o.group`` — the sync-time read and the next-tick read are identical
    (observed: ``DBG sync-time group=false left=300 top=200``). Mutation-testing confirmed it:
    replacing the ``setTimeout(0)`` with a synchronous read and dropping the ``!o.group`` guard
    was NOT caught by this check, nor by ``check_multi_select_sync_on_cleared``. Those two details
    are defensive against other Fabric versions where the event could plausibly fire before
    coordinates are restored; a regression in either one would pass this suite silently. What is
    actually under test here is narrower and still real: that the sync fires on deselection at
    all, on the ``updated`` branch as well as ``cleared``.
    """
    box = _group_two_rects_and_drag(probe)
    page = probe.page
    page.keyboard.down('Shift')
    page.mouse.click(box['x'] + 300, box['y'] + 200)          # blue, at its dragged position
    page.keyboard.up('Shift')
    wait_until(lambda: probe.text_of('.selection').endswith('updated:1'),
               'blue to be removed from the selection, leaving red in it',
               diagnose=lambda: probe.text_of('.selection'))

    blue = wait_until(lambda: [r for r in probe.registry() if round(r['left']) == 300
                               and round(r['top']) != 100],
                      'blue to be synced back on its way out of the group',
                      diagnose=probe.registry)[0]
    assert abs(blue['top'] - 200) <= 5, f'blue should be at absolute top 200: {blue}'
    # red is still in the group, so it must NOT have been synced yet
    current = probe.registry()
    reds = [r for r in current if round(r['left']) == 100]
    # under the group-relative regression this check exists to catch, red's synced 'left' would
    # read ~-100 (group-relative) instead of 100, so this list would be empty — report the whole
    # registry rather than raising IndexError, which is precisely that regression in disguise
    assert reds, f'no rect with left==100 found in registry: {current}'
    red = reds[0]
    assert round(red['top']) == 100, f'red is still selected, nothing should have synced it: {red}'

    page.mouse.click(box['x'] + 550, box['y'] + 380)          # now drop red too
    _assert_dragged_pair_synced(probe)


def check_free_draw_lands_in_registry(probe: Probe) -> None:
    """path:created -> object-added -> the Python registry holds a real Path."""
    probe.open(f'{PROBE_URL}/draw')
    wait_for_render(probe, WHITE, 0, 0, 'an empty canvas')
    wait_for_draw_mode(probe)
    assert probe.registry() == []
    draw_stroke(probe, [(80, 80), (160, 140), (240, 90)])
    objects = wait_until(lambda: probe.registry(), 'the drawn path to reach the registry')
    assert len(objects) == 1, objects
    path = objects[0]
    assert path['type'] == 'Path', path
    assert len(path['path']) >= 3, path['path']
    assert path['stroke'] == '#ff0000' and path['strokeWidth'] == 5, path
    assert 60 < path['width'] < 260 and 20 < path['height'] < 160, path
    assert probe.text_of('.errors') == 'none'
    probe.assert_clean_console()


def check_drawn_path_survives_roundtrip(probe: Probe) -> None:
    """A filtered (originX/originY-less) path can be revived: to_dict -> clear -> load_json."""
    probe.open(f'{PROBE_URL}/draw')
    wait_for_render(probe, WHITE, 0, 0, 'an empty canvas')
    wait_for_draw_mode(probe)
    draw_stroke(probe, [(80, 80), (160, 140), (240, 90)])
    wait_until(lambda: probe.registry(), 'the drawn path to reach the registry')
    painted_before = wait_for_render(probe, WHITE, 100, 40_000, 'the stroke to be painted')

    probe.page.locator('.roundtrip-btn').click()
    status = wait_until(lambda: (t := probe.text_of('.status')) not in ('idle', 'running') and t,
                        'the round trip to finish', timeout=60)
    assert status.startswith('SAME'), f'round trip did not render identically: {status}'
    assert ' n=1 ' in status, status
    # guarded like the registry read at the top of _assert_dragged_pair_synced: a '-' placeholder
    # or a dump caught mid-update raises JSONDecodeError instead of failing meaningfully
    objects = wait_until(lambda: probe.registry() or None, 'the revived path in the registry',
                         diagnose=probe.registry)
    assert len(objects) == 1 and objects[0]['type'] == 'Path', objects
    painted_after = probe.painted_pixels(WHITE)
    assert painted_after == painted_before, (painted_before, painted_after)
    assert probe.text_of('.errors') == 'none', 'an object failed to revive in the browser'
    probe.assert_clean_console()


def _count_red_pixels(probe: Probe, data_url: str) -> int:
    """Decode a PNG data URL in the browser and count pixels that are the demo's red fill.

    Uses the browser's own PNG decoder (an offscreen ``<img>`` + canvas ``drawImage``), the same
    approach ``painted_pixels`` uses on the live canvas — no new Python-side dependency needed.
    """
    return probe.page.evaluate(
        """(url) => new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = () => {
                const c = document.createElement('canvas');
                c.width = img.naturalWidth;
                c.height = img.naturalHeight;
                const ctx = c.getContext('2d', {willReadFrequently: true});
                ctx.drawImage(img, 0, 0);
                const d = ctx.getImageData(0, 0, c.width, c.height).data;
                let n = 0;
                for (let i = 0; i < d.length; i += 4)
                    if (d[i] > 200 && d[i + 1] < 80 && d[i + 2] < 80 && d[i + 3] > 200) n++;
                resolve(n);
            };
            img.onerror = () => reject(new Error('failed to decode exported PNG'));
            img.src = url;
        })""", data_url)


def check_export_success_path(probe: Probe) -> None:
    """toDataURL/toSVG -> HTTP POST -> the awaiting Python coroutine gets the bytes."""
    probe.open(f'{PROBE_URL}/export')
    probe.page.locator('.png-btn').click()
    png = wait_until(lambda: (t := probe.text_of('.result')) != 'idle' and t, 'the PNG export')
    assert png.startswith('PNG prefix=data:image/png;base64, magic=89504e47 size=400x300'), png
    # bytes>1000 alone is not content-blind-proof: a blank 400x300 white PNG already measures
    # ~925-1135 bytes, straddling that bound. Decode the PNG and require the red rect (drawn at
    # left=50 top=60 width=100 height=80, Fabric's centre origin puts it at canvas (0,20)-(100,100)
    # = 8000px nominal) to actually be there, not just "some bytes came back".
    assert int(re.search(r'bytes=(\d+)', png).group(1)) > 1000, png
    data_url = wait_until(lambda: probe.text_of('.raw-url') or None, 'the exported PNG data url')
    red_pixels = _count_red_pixels(probe, data_url)
    assert red_pixels > 5000, f'red rect not found in exported PNG: red_pixels={red_pixels} ({png})'

    before = png                                             # '.result' still shows the PNG summary
    probe.page.locator('.svg-btn').click()
    # compares against 'idle' like the PNG wait above (the '/export' page resets '.result' to
    # 'idle' before running the SVG export) so a failure surfaces the real 'EXC ...' message
    # instead of a bare "last: False" the way ".startswith('SVG')" used to. Also excludes
    # `before`: the click's websocket round trip can take longer than one poll interval, and the
    # very first poll would otherwise still see the PNG summary (which is != 'idle') and return
    # that stale value as if it were the SVG result.
    svg = wait_until(lambda: (t := probe.text_of('.result')) not in ('idle', before) and t,
                     'the SVG export')
    assert 'root=1' in svg and 'red=True' in svg, f'the red rect is missing from the SVG: {svg}'
    assert int(re.search(r'len=(\d+)', svg).group(1)) > 300, svg
    probe.assert_clean_console()


def check_export_failure_path(probe: Probe) -> None:
    """A tainted canvas fails the export fast with RuntimeError instead of hanging."""
    probe.open(f'{PROBE_URL}/taint')

    def is_tainted() -> str:
        """Reading back pixels throws once a cross-origin image has been drawn — that is taint."""
        try:
            probe.painted_pixels(WHITE)
        except Exception as e:                # noqa: BLE001 - that is the point
            return str(e) if 'SecurityError' in str(e) or 'tainted' in str(e) else ''
        return ''

    wait_until(is_tainted, 'the cross-origin image to load and taint the canvas')
    assert probe.text_of('.errors') == 'none', 'the image reported an enliven error'

    started = time.monotonic()
    probe.page.locator('.png-btn').click()
    result = wait_until(lambda: (t := probe.text_of('.result')) != 'idle' and t,
                        'the failed export to be reported', timeout=25)
    elapsed = time.monotonic() - started
    assert result.startswith('RuntimeError: browser-side export failed:'), result
    assert 'tainted' in result.lower(), result
    # Scaled by E2E_TIMEOUT so a contended runner can widen it, but capped well below the
    # to_data_url(timeout=30) this exists to distinguish "failed fast" from "ran out the clock".
    fast_budget = min(15, E2E_TIMEOUT / 2)
    assert elapsed < fast_budget, (
        f'the failure took {elapsed:.1f}s (budget {fast_budget:.1f}s) — with '
        f'to_data_url(timeout=30) that means it waited for the timeout instead of failing fast')
    probe.assert_clean_console()   # the export failed, but it failed cleanly


def check_svg_import_flattens_and_survives_roundtrip(probe: Probe) -> None:
    """add_svg: parse in the browser -> flat, absolute objects in the registry -> round trip.

    The whole claim of flattening in one check: what comes back from Fabric's parser is not a
    group but three ordinary objects, they are painted, they carry absolute coordinates (so the
    ``<g transform>`` really was baked in), and — because they are ordinary — they survive
    ``to_dict`` -> ``clear_objects`` -> ``load_json`` pixel-for-pixel.
    """
    probe.open(f'{PROBE_URL}/svg')
    wait_for_render(probe, WHITE, 0, 0, 'an empty canvas')
    assert probe.registry() == []

    previous = 'idle'

    def click(selector: str, what: str) -> str:
        """Click one button and return the status it produced.

        Excluding the *previous* status matters as much as excluding 'running': the click's
        websocket round trip can outlast a poll interval, and the stale value left by the step
        before would otherwise be returned as if it were this step's result.
        """
        nonlocal previous
        probe.page.locator(selector).click()
        previous = wait_until(
            lambda: (t := probe.text_of('.status')) not in ('running', previous) and t,
            what, timeout=60)
        return previous

    status = click('.import-btn', 'the SVG import to finish')
    assert status.startswith('OK n=3 types=Rect,Circle,Path'), status
    assert 'size=(220, 140)' in status, f'the document dimensions were not reported: {status}'

    objects = wait_until(lambda: probe.registry() or None, 'the parsed shapes in the registry',
                         diagnose=probe.registry)
    assert len(objects) == 3, objects
    # flat: the <g> is gone, and nothing nested came through pretending to be a shape
    assert all('objects' not in o for o in objects), objects
    for (type_, left, top), obj in zip(SVG_EXPECTED, objects):
        assert obj['type'] == type_, (obj, type_)
        assert abs(obj['left'] - left) <= 3 and abs(obj['top'] - top) <= 3, (
            f'{type_} should be at absolute ({left}, {top}) with the <g> transform baked in, '
            f'got ({obj["left"]}, {obj["top"]})')
    painted_before = wait_for_render(probe, WHITE, *SVG_PIXELS, 'the three imported shapes')
    assert probe.text_of('.errors') == 'none', 'an imported shape failed to revive in the browser'

    # a document the browser's XML parser rejects: [] and an untouched canvas, not an exception
    bad = click('.garbage-btn', 'the malformed import to be reported')
    assert bad == 'BAD n=0 size=None kept=3', bad
    assert probe.painted_pixels(WHITE) == painted_before, 'the malformed import changed the canvas'

    probe.assert_clean_console()      # before the step below, which makes the browser log a failure

    # an <image> the browser cannot load fails the whole parse in Fabric 7.4.0 — that has to
    # reach the caller as RuntimeError, with nothing half-imported behind it
    unloadable = click('.image-btn', 'the unloadable-image import to be reported')
    assert unloadable.startswith('EXC RuntimeError:'), unloadable
    assert len(probe.registry()) == 3, 'a failed import must not leave shapes behind'
    assert probe.painted_pixels(WHITE) == painted_before, 'the failed import changed the canvas'

    result = click('.roundtrip-btn', 'the round trip to finish')
    assert result == 'SAME n=3', f'imported shapes did not survive the round trip: {result}'
    assert probe.painted_pixels(WHITE) == painted_before, 'the round trip changed the rendering'
    assert probe.text_of('.errors') == 'none', 'a revived shape errored in the browser'


CHECKS: list[Callable[[Probe], None]] = [
    check_demo_mounts_and_adds_shapes,
    check_demo_free_draw_reaches_python,
    check_demo_export_downloads_png,
    check_multi_select_sync_on_cleared,
    check_multi_select_sync_on_updated,
    check_free_draw_lands_in_registry,
    check_drawn_path_survives_roundtrip,
    check_export_success_path,
    check_export_failure_path,
    check_svg_import_flattens_and_survives_roundtrip,
]


# --------------------------------------------------------------------------- pytest wiring


@pytest.fixture(scope='module')
def servers() -> Iterator[None]:
    with running_servers():
        yield


@pytest.fixture(scope='module')
def browser() -> Iterator[Browser]:
    with sync_playwright() as p:
        chromium = p.chromium.launch()
        yield chromium
        chromium.close()


@pytest.fixture
def probe(servers: None, browser: Browser) -> Iterator[Probe]:
    page = browser.new_page()
    try:
        yield Probe(page)
    finally:
        page.close()


@pytest.mark.e2e
@pytest.mark.parametrize('check', CHECKS, ids=lambda c: c.__name__.removeprefix('check_'))
def test_e2e(check: Callable[[Probe], None], probe: Probe) -> None:
    check(probe)


# --------------------------------------------------------------------------- standalone


def main(names: list[str] | None = None) -> int:
    checks = [c for c in CHECKS if not names or any(n in c.__name__ for n in names)]
    failures: list[str] = []
    started = time.monotonic()
    with running_servers(), sync_playwright() as p:
        chromium = p.chromium.launch()
        for check in checks:
            page = chromium.new_page()
            t0 = time.monotonic()
            try:
                check(Probe(page))
                print(f'PASS  {check.__name__}  ({time.monotonic() - t0:.1f}s)', flush=True)
            except Exception as e:            # noqa: BLE001 - report and continue
                failures.append(f'{check.__name__}: {type(e).__name__}: {e}')
                shot = Path(tempfile.gettempdir()) / f'e2e-{check.__name__}.png'
                page.screenshot(path=str(shot))
                print(f'FAIL  {check.__name__}  ({time.monotonic() - t0:.1f}s)\n      '
                      f'{type(e).__name__}: {e}\n      screenshot: {shot}', flush=True)
            finally:
                page.close()
        chromium.close()
    print(f'\n{len(checks) - len(failures)}/{len(checks)} passed '
          f'in {time.monotonic() - started:.1f}s')
    return 1 if failures else 0


if __name__ == '__main__':
    if '--probe-server' in sys.argv:
        _run_probe_server()
    else:
        sys.exit(main(sys.argv[1:]))
