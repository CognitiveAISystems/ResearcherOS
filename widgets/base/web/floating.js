/**
 * Shared helpers for floating ResearchOS widgets (drag + position persistence).
 */

export function bindFloatingDrag(root, { storageKey, handle, onTap } = {}) {
  const dragHandle = handle || root;
  let dragging = false;
  let moved = false;
  let offsetX = 0;
  let offsetY = 0;

  const save = () => {
    if (!storageKey) return;
    try {
      const rect = root.getBoundingClientRect();
      localStorage.setItem(
        storageKey,
        JSON.stringify({ x: Math.round(rect.left), y: Math.round(rect.top) })
      );
    } catch {
      /* ignore */
    }
  };

  const load = () => {
    if (!storageKey) return false;
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return false;
      const data = JSON.parse(raw);
      if (!Number.isFinite(data?.x) || !Number.isFinite(data?.y)) return false;
      root.style.left = `${data.x}px`;
      root.style.top = `${data.y}px`;
      root.style.right = "auto";
      return true;
    } catch {
      return false;
    }
  };

  const margin = 12;
  const header = document.querySelector(".topbar");

  const bounds = () => {
    const style = getComputedStyle(root);
    // Widgets may be hidden until their first API response or stylesheet load.
    const width = root.offsetWidth || parseFloat(style.width) || 76;
    const height = root.offsetHeight || parseFloat(style.height) || 76;
    const minY = Math.max(margin, (header?.getBoundingClientRect().bottom || 0) + margin);
    return {
      minX: margin,
      minY,
      maxX: Math.max(margin, window.innerWidth - width - margin),
      // Keep the drag handle below the header even for a very tall widget.
      maxY: Math.max(minY, window.innerHeight - height - margin),
    };
  };

  const place = (x, y) => {
    const { minX, minY, maxX, maxY } = bounds();
    root.style.left = `${Math.min(maxX, Math.max(minX, x))}px`;
    root.style.top = `${Math.min(maxY, Math.max(minY, y))}px`;
    root.style.right = "auto";
  };

  const keepVisible = () => {
    const rect = root.getBoundingClientRect();
    const x = parseFloat(root.style.left);
    const y = parseFloat(root.style.top);
    place(Number.isFinite(x) ? x : rect.left, Number.isFinite(y) ? y : rect.top);
    // A hidden widget has a zero rect; do not replace its saved position with it.
    if (root.getClientRects().length) save();
  };

  if (!load()) {
    const x = parseFloat(root.style.left);
    const y = parseFloat(root.style.top);
    // Respect each package's horizontal starting position.
    place(Number.isFinite(x) ? x : bounds().maxX, Number.isFinite(y) ? y : bounds().minY);
  }
  keepVisible();

  dragHandle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    dragging = true;
    moved = false;
    const rect = root.getBoundingClientRect();
    offsetX = event.clientX - rect.left;
    offsetY = event.clientY - rect.top;
    dragHandle.setPointerCapture?.(event.pointerId);
    root.classList.add("koi-widget--dragging");
    event.preventDefault();
  });

  dragHandle.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const x = event.clientX - offsetX;
    const y = event.clientY - offsetY;
    if (Math.abs(x - root.offsetLeft) > 2 || Math.abs(y - root.offsetTop) > 2) {
      moved = true;
    }
    place(x, y);
  });

  const endDrag = (event) => {
    if (!dragging) return;
    dragging = false;
    root.classList.remove("koi-widget--dragging");
    dragHandle.releasePointerCapture?.(event.pointerId);
    save();
    if (!moved && typeof onTap === "function") {
      onTap(event);
    }
  };

  dragHandle.addEventListener("pointerup", endDrag);
  dragHandle.addEventListener("pointercancel", endDrag);

  window.addEventListener("resize", keepVisible);
  // Re-clamp after header wrapping, widget expansion, or delayed stylesheet load.
  const sizes = new ResizeObserver(keepVisible);
  sizes.observe(root);
  if (header) sizes.observe(header);

  const destroy = () => {
    sizes.disconnect();
    removals.disconnect();
    window.removeEventListener("resize", keepVisible);
  };
  // Existing packages need no changes to their unmount callbacks.
  const removals = new MutationObserver(() => {
    if (!root.isConnected) destroy();
  });
  removals.observe(document.body, { childList: true, subtree: true });

  return {
    endDrag,
    destroy,
    wasMoved: () => moved,
    save,
  };
}

export function injectStylesheet(href) {
  const existing = document.querySelector(`link[data-koi-widget-css="${href}"]`);
  if (existing) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.dataset.koiWidgetCss = href;
  document.head.appendChild(link);
}
