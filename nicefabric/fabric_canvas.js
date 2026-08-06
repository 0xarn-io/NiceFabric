import * as fabric from "nicefabric";

fabric.FabricObject.customProperties = ["id"];

export default {
  template: "<div></div>",
  props: { width: Number, height: Number, background: String, selection: Boolean, keyboardDelete: Boolean },
  mounted() {
    // a <canvas> root would be re-parented by Fabric into .canvas-container,
    // breaking NiceGUI .classes()/.style() — so the root is a <div>
    const el = document.createElement("canvas");
    this.$el.appendChild(el);
    this.canvas = new fabric.Canvas(el, {
      width: this.width,
      height: this.height,
      backgroundColor: this.background,
      selection: this.selection,
    });
    // ops are enqueued on this chain so they apply in the order Python issued them:
    // add_object/sync_objects are async (enlivening an image is a network load) and NiceGUI
    // does not await a method before dispatching the next one
    this._queue = Promise.resolve();
    this._initInterval = setInterval(() => {
      if (window.socket.id === undefined) return;  // Leaflet handshake pattern
      this.$emit("init");
      clearInterval(this._initInterval);
    }, 100);

    // --- sync-back: browser-side changes flow back into Python's canonical registry.
    // Every payload here is a bandwidth courtesy only — the server re-validates everything.
    const GEOMETRY_KEYS = ["left", "top", "scaleX", "scaleY", "angle",
                           "skewX", "skewY", "flipX", "flipY", "width", "height"];
    const geometryOf = (o) => Object.fromEntries(GEOMETRY_KEYS.map((k) => [k, o[k]]));
    const c = this.canvas;

    c.on("object:modified", (e) => {
      const t = e.target;
      if (!t || t instanceof fabric.ActiveSelection) return;  // multi-select: synced on deselect below
      if (t.id) this.$emit("object-modified", { id: t.id, props: geometryOf(t) });
    });
    const syncDeselected = (e) => {
      const gone = e.deselected ?? [];
      setTimeout(() => {  // next tick: fabric has restored absolute coords
        for (const o of gone) {
          if (o.id && !o.group) this.$emit("object-modified", { id: o.id, props: geometryOf(o) });
        }
      }, 0);
    };
    const emitSelection = (kind) =>
      this.$emit("selection", { kind, ids: c.getActiveObjects().map((o) => o.id).filter(Boolean) });
    c.on("selection:created", () => emitSelection("created"));
    c.on("selection:updated", (e) => { syncDeselected(e); emitSelection("updated"); });
    c.on("selection:cleared", (e) => { syncDeselected(e); emitSelection("cleared"); });

    c.on("path:created", (e) => {
      e.path.id = crypto.randomUUID().replaceAll("-", "");
      this.$emit("object-added", { id: e.path.id, obj: e.path.toObject(["id"]) });
    });
    c.on("text:changed", (e) => {
      if (e.target?.id) this.$emit("text-changed", { id: e.target.id, text: e.target.text });
    });
    for (const ev of ["mouse:down", "mouse:up"]) {
      c.on(ev, (e) => {
        const p = c.getScenePoint(e.e);
        this.$emit(ev.replace(":", "-"), { x: p.x, y: p.y, id: e.target?.id ?? null });
      });
    }
    if (this.keyboardDelete) {
      c.upperCanvasEl.tabIndex = 0;
      c.upperCanvasEl.addEventListener("keydown", (e) => {
        if (e.key === "Delete" || e.key === "Backspace") {
          this.$emit("request-delete", { ids: c.getActiveObjects().map((o) => o.id).filter(Boolean) });
        }
      });
    }
  },
  beforeUnmount() {
    clearInterval(this._initInterval);
    this.canvas?.dispose();  // async, but DOM cleanup is synchronous — safe fire-and-forget
  },
  methods: {
    find(id) {
      return this.canvas.getObjects().find((o) => o.id === id);
    },
    _enqueue(op) {
      const result = this._queue.then(op);
      this._queue = result.catch(() => {});  // a failing op must not poison the ops behind it
      return result;  // callers (and Python awaits) still see the real value or rejection
    },
    async enliven_and_add(objs) {
      const results = await Promise.allSettled(
        objs.map((o) => fabric.util.enlivenObjects([o]).then(([x]) => x)),
      );
      results.forEach((r, i) => {
        if (r.status === "fulfilled" && r.value) this.canvas.add(r.value);
        else {
          const message = String(r.reason ?? "enliven failed");
          console.error("nicefabric: failed to enliven object", objs[i].id, message);
          this.$emit("object-error", { id: objs[i].id, message });
        }
      });
      this.canvas.requestRenderAll();
    },
    sync_objects(objs) {
      return this._enqueue(async () => {
        this.canvas.remove(...this.canvas.getObjects());
        await this.enliven_and_add(objs);
      });
    },
    add_object(obj) {
      return this._enqueue(async () => {
        if (this.find(obj.id)) return;  // idempotent — replay-safe
        await this.enliven_and_add([obj]);
      });
    },
    update_object(id, props) {
      return this._enqueue(() => {
        const o = this.find(id);
        if (!o) return;
        o.set(props);
        o.setCoords();
        this.canvas.requestRenderAll();
      });
    },
    remove_object(id) {
      return this._enqueue(() => {
        const o = this.find(id);
        if (o) this.canvas.remove(o);
        this.canvas.requestRenderAll();
      });
    },
    clear() {
      return this._enqueue(() => {
        this.canvas.remove(...this.canvas.getObjects());
        this.canvas.requestRenderAll();
      });
    },
    set_background(color) {
      return this._enqueue(() => {
        this.canvas.backgroundColor = color;
        this.canvas.requestRenderAll();
      });
    },
    set_zoom(z) { return this._enqueue(() => this.canvas.setZoom(z)); },
    absolute_pan(x, y) { return this._enqueue(() => this.canvas.absolutePan(new fabric.Point(x, y))); },
    resize(w, h) { return this._enqueue(() => this.canvas.setDimensions({ width: w, height: h })); },
    bring_to_front(id) {
      return this._enqueue(() => {
        const o = this.find(id);
        if (o) this.canvas.bringObjectToFront(o);
        this.canvas.requestRenderAll();
      });
    },
    send_to_back(id) {
      return this._enqueue(() => {
        const o = this.find(id);
        if (o) this.canvas.sendObjectToBack(o);
        this.canvas.requestRenderAll();
      });
    },
    discard_selection() {
      return this._enqueue(() => {
        this.canvas.discardActiveObject();
        this.canvas.requestRenderAll();
      });
    },
    set_draw_mode(on, opts) {
      return this._enqueue(() => {
        this.canvas.isDrawingMode = on;
        if (on) {
          const b = new fabric.PencilBrush(this.canvas);
          b.color = opts.color;
          b.width = opts.width;
          this.canvas.freeDrawingBrush = b;
        }
      });
    },
    // exports go back over HTTP, not the socket: a >1 MB socket message closes the connection.
    // Only the canvas read (toDataURL/toSVG) needs the queue — it must see everything enqueued
    // ahead of it — so the upload itself runs after `_enqueue` has already released the lock.
    export_data_url(token, opts) {
      return this._enqueue(() => this.canvas.toDataURL(opts)).then(
        (body) => this._post_export(token, body),
        (err) => this._post_export(token, String(err?.message ?? err), true),
      );
    },
    export_svg(token) {
      return this._enqueue(() => this.canvas.toSVG()).then(
        (body) => this._post_export(token, body),
        (err) => this._post_export(token, String(err?.message ?? err), true),
      );
    },
    _post_export(token, body, failed = false) {
      const url = (window.path_prefix || "") + "/_nicefabric/export/" + token + (failed ? "?error=1" : "");
      return fetch(url, { method: "POST", body });
    },
    run_canvas_method(name, ...args) {
      return this._enqueue(() => this._run(this.canvas, name, args));
    },
    run_object_method(id, name, ...args) {
      return this._enqueue(() => {
        const o = this.find(id);
        if (o) return this._run(o, name, args);
      });
    },
    _run(target, name, args) {
      if (name.startsWith(":")) {
        name = name.slice(1);
        args = args.map((a) => new Function(`return (${a})`)());
      }
      return runMethod(target, name, args);
    },
  },
};
