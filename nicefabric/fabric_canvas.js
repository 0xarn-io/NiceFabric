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
    async sync_objects(objs) {
      this.canvas.remove(...this.canvas.getObjects());
      await this.enliven_and_add(objs);
    },
    async add_object(obj) {
      if (this.find(obj.id)) return;  // idempotent — replay-safe
      await this.enliven_and_add([obj]);
    },
  },
};
