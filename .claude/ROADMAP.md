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

**v2 candidates:** first-class group support (needs a Python-side model that survives
serialization), an undo/redo helper, per-object event dispatch.
