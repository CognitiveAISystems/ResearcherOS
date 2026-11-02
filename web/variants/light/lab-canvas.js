/** Pan/zoom camera for the laboratory mindmap canvas. */

/** Padding when fitting a single project at max zoom (px). */
const PROJECT_ZOOM_PADDING = 8;
/** Padding when fitting a method node + kanban at max zoom (px). */
const NODE_ZOOM_PADDING = 12;

export class MindmapCamera {
  /**
   * @param {HTMLElement} viewport
   * @param {HTMLElement} canvas
   * @param {{ onChange?: () => void }} options
   */
  constructor(viewport, canvas, options = {}) {
    this.viewport = viewport;
    this.canvas = canvas;
    this.onChange = options.onChange || (() => {});
    this.x = 0;
    this.y = 0;
    this.scale = 1;
    this.minScale = 0.1;
    this.maxScale = 2;
    this.world = { x: 0, y: 0, width: 800, height: 600 };
    this.projectRegions = {};
    this.nodeRegions = {};
    this.projectMaxScale = 1;
    this.methodMaxScale = 1;
    this._drag = null;
    this._anim = null;
    this._bind();
  }

  _bind() {
    this.viewport.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const rect = this.viewport.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
        this.zoomAt(mx, my, this.scale * factor);
      },
      { passive: false }
    );

    this.viewport.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      const t = e.target;
      if (
        t.closest?.(
          ".map-node, .node-delete, .node-type-help-trigger, .project-list__btn, .method-questions-trigger, .kanban-below, .node-kanban-below, .map-kanban-board, .kanban-card, .kanban-col, .method-activity-overlay, .method-activity-overlay-pin, .method-activity-inspect, .method-activity.is-overlay-beacon, .method-activity-stage"
        )
      ) {
        return;
      }
      this.viewport.setPointerCapture(e.pointerId);
      this._drag = { x: e.clientX, y: e.clientY, camX: this.x, camY: this.y };
      this.viewport.classList.add("is-panning");
    });

    this.viewport.addEventListener("pointermove", (e) => {
      if (!this._drag) return;
      this.x = this._drag.camX + (e.clientX - this._drag.x);
      this.y = this._drag.camY + (e.clientY - this._drag.y);
      this._apply();
    });

    const endDrag = (e) => {
      if (!this._drag) return;
      this._drag = null;
      this.viewport.classList.remove("is-panning");
      try {
        this.viewport.releasePointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
    };
    this.viewport.addEventListener("pointerup", endDrag);
    this.viewport.addEventListener("pointercancel", endDrag);
  }

  setWorldBounds(bbox) {
    this.world = { ...bbox };
    this._recomputeScaleLimits();
  }

  setProjectRegions(regions) {
    this.projectRegions = regions || {};
    this._recomputeScaleLimits();
  }

  setNodeRegions(regions) {
    this.nodeRegions = regions || {};
    this._recomputeScaleLimits();
  }

  _regionFitScale(region, padding) {
    const { width: vw, height: vh } = this.viewportSize();
    const rw = Math.max(region.width, 1);
    const rh = Math.max(region.height, 1);
    return Math.min((vw - padding) / rw, (vh - padding) / rh);
  }

  _recomputeScaleLimits() {
    const { width: vw, height: vh } = this.viewportSize();
    const pad = 40;
    const w = Math.max(this.world.width, 1);
    const h = Math.max(this.world.height, 1);
    this.minScale = Math.max(
      0.01,
      Math.min((vw - pad) / w, (vh - pad) / h)
    );

    let maxFit = this.minScale;
    let projectMaxFit = this.minScale;
    let methodMaxFit = this.minScale;
    for (const region of Object.values(this.projectRegions || {})) {
      const fit = this._regionFitScale(region, PROJECT_ZOOM_PADDING);
      projectMaxFit = Math.max(projectMaxFit, fit);
      maxFit = Math.max(maxFit, fit);
    }
    for (const region of Object.values(this.nodeRegions || {})) {
      const fit = this._regionFitScale(region, NODE_ZOOM_PADDING);
      methodMaxFit = Math.max(methodMaxFit, fit);
      maxFit = Math.max(maxFit, fit);
    }
    this.projectMaxScale = projectMaxFit;
    this.methodMaxScale = methodMaxFit;
    this.maxScale = Math.max(maxFit, this.minScale);
    this.scale = Math.min(Math.max(this.scale, this.minScale), this.maxScale);
  }

  viewportSize() {
    const r = this.viewport.getBoundingClientRect();
    return { width: Math.max(r.width, 1), height: Math.max(r.height, 1) };
  }

  clampScale(scale) {
    return Math.min(this.maxScale, Math.max(this.minScale, scale));
  }

  zoomAt(mx, my, nextScale) {
    const newScale = this.clampScale(nextScale);
    const wx = (mx - this.x) / this.scale;
    const wy = (my - this.y) / this.scale;
    this.scale = newScale;
    this.x = mx - wx * this.scale;
    this.y = my - wy * this.scale;
    this._apply();
  }

  zoomBy(factor) {
    const { width, height } = this.viewportSize();
    this.zoomAt(width / 2, height / 2, this.scale * factor);
  }

  fitWorld(padding = 48) {
    const { width: vw, height: vh } = this.viewportSize();
    const w = Math.max(this.world.width, 1);
    const h = Math.max(this.world.height, 1);
    this.scale = this.clampScale(
      Math.min((vw - padding) / w, (vh - padding) / h)
    );
    this.x = (vw - w * this.scale) / 2;
    this.y = (vh - h * this.scale) / 2;
    this._apply();
  }

  fitRegion(region, padding = PROJECT_ZOOM_PADDING) {
    if (!region) {
      this.fitWorld();
      return;
    }
    const { width: vw, height: vh } = this.viewportSize();
    const rw = Math.max(region.width, 1);
    const rh = Math.max(region.height, 1);
    this.scale = this.clampScale(
      Math.min((vw - padding) / rw, (vh - padding) / rh)
    );
    const cx = region.x + rw / 2;
    const cy = region.y + rh / 2;
    this.x = vw / 2 - cx * this.scale;
    this.y = vh / 2 - cy * this.scale;
    this._apply();
  }

  flyToRegion(region, duration = 380, padding = PROJECT_ZOOM_PADDING) {
    if (!region) return;
    const { width: vw, height: vh } = this.viewportSize();
    const rw = Math.max(region.width, 1);
    const rh = Math.max(region.height, 1);
    const targetScale = this.clampScale(
      Math.min((vw - padding) / rw, (vh - padding) / rh)
    );
    const cx = region.x + rw / 2;
    const cy = region.y + rh / 2;
    const targetX = vw / 2 - cx * targetScale;
    const targetY = vh / 2 - cy * targetScale;
    this._animateTo(targetX, targetY, targetScale, duration);
  }

  _animateTo(tx, ty, ts, duration) {
    if (this._anim) cancelAnimationFrame(this._anim);
    const sx = this.x;
    const sy = this.y;
    const ss = this.scale;
    const t0 = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - t0) / duration);
      const ease = 1 - (1 - t) ** 3;
      this.x = sx + (tx - sx) * ease;
      this.y = sy + (ty - sy) * ease;
      this.scale = ss + (ts - ss) * ease;
      this._apply();
      if (t < 1) this._anim = requestAnimationFrame(step);
      else this._anim = null;
    };
    this._anim = requestAnimationFrame(step);
  }

  _apply() {
    this.scale = this.clampScale(this.scale);
    this.canvas.style.transform = `translate(${this.x}px, ${this.y}px) scale(${this.scale})`;
    this.onChange();
  }

  /** Viewport rectangle in world coordinates. */
  viewportWorldRect() {
    const { width, height } = this.viewportSize();
    return {
      x: -this.x / this.scale,
      y: -this.y / this.scale,
      width: width / this.scale,
      height: height / this.scale,
    };
  }
}
