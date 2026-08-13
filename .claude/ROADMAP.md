# Roadmap / feature log

Shipped features and stated future direction. Deep design detail lives in `ARCHITECTURE.md`;
defects and audit findings live in `ISSUES.md`.

## NiceFabric — FabricCanvas element

**v0.1.0 — shipped.** `pip install nicefabric` gives NiceGUI a Fabric.js 7.4.0 canvas element.
Neither Fabric nor NiceGUI is forked: the prebuilt Fabric browser bundle is vendored unmodified
as `nicefabric/lib/nicefabric.min.mjs` and NiceGUI is an ordinary `>=3.6,<4` dependency.

In the box:

- shape helpers (`add_rect`/`add_circle`/`add_ellipse`/`add_line`/`add_polygon`/`add_polyline`/
  `add_path`/`add_text`/`add_image`) returning `FabricObject` handles, plus `update_object`,
  `remove_object`, `bring_to_front`, `send_to_back`;
- free drawing (`enable_drawing`/`disable_drawing`) with drawn paths synced back into the Python
  registry;
- selection tracking (`get_selected`, `remove_selected`, `discard_selection`, `on_selection`) and
  optional keyboard delete;
- serialization: `to_dict`/`to_json` server-side, `load_json` with size/count/type/`src` caps on
  untrusted input;
- async export: `to_svg()` and `to_data_url()` over a one-time-token HTTP endpoint, not the
  ~1 MB websocket;
- generic escape hatches under the helpers: `add_object`, `run_canvas_method`,
  `run_object_method`, `FabricObject.run_method`, and NiceGUI's `:`-prefixed JS passthrough;
- demo (`examples/main.py`), 65 unit tests, 9 browser E2E checks, README, CI.

**Not built, reachable from what exists** (README, "Extensions and non-goals"): undo/redo via
`to_dict()` snapshots + `load_json()`; dark-mode background via `set_background`; groups and
`animate` (only through `run_canvas_method`/`run_object_method`, ephemeral — they do not
round-trip through `to_dict()`); per-object event handlers (events are canvas-wide, dispatch on
`e.args['id']`); responsive scaling; touch gestures beyond Fabric's defaults.

**v0.2 — shipped.** `on_moving`: an opt-in, throttled `object:moving` stream for live drag
feedback (alignment guides, running dimensions, connectors that re-route while you drag). Off
unless a handler is passed, since it is the only continuously-firing event; `moving_interval`
sets the throttle and the trailing edge is always delivered, so the drop position is never lost.
The registry is updated from it, so `to_dict()` is current mid-drag.

**Groups: already reachable, undocumented.** `add_object('Group', objects=[...])` round-trips
through the existing enliven pipeline — it drags as one unit, reports its own id on selection and
survives `to_dict()`/`load_json()`. Two constraints make it work: the descriptor MUST carry
explicit `width`/`height` (Fabric's `Group.fromObject` does not compute bounds, so a group without
them renders nothing), and children are positioned by their CENTRE relative to the group's centre.
Worth first-class helpers and README coverage in v0.3.

**v2 candidates:** a typed group helper, an undo/redo helper, per-object event dispatch,
viewport interaction (wheel-zoom-at-cursor, drag-to-pan) synced back to Python, and selective
control handles (e.g. expose only `ml`/`mr` so a length can be dragged).
