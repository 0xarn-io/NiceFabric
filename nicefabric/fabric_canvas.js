import * as fabric from "nicefabric";

fabric.FabricObject.customProperties = ["id"];

export default {
  template: "<div></div>",
  props: { width: Number, height: Number, background: String, selection: Boolean },
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
