/** Animated “in progress” vignette + speech bubble under method nodes (kanban running). */

export const METHOD_ACTIVITY_H = 52;

const BUBBLE_TICK_MS = 3800;
const ZOOM_PREVIEW_RATIO = 0.28;
const ZOOM_CARDS_METHOD_RATIO = 0.82;
/** Inline activity is readable from this fraction of method-level fit zoom. */
const ACTIVITY_INLINE_ZOOM_RATIO = 0.68;
const timers = new Map();
let previewEl = null;
let previewAnchor = null;
let previewBoundViewport = null;
let overlayEl = null;

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function truncate(s, max = 52) {
  const t = String(s || "").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

/** @param {string} description */
export function subtasksFromDescription(description) {
  const open = [];
  const done = [];
  const body = String(description || "").replace(/\\n/g, "\n");
  const re = /-\s*\[([ xX])\]\s*([^\n]*?)(?=\s*-\s*\[|$)/gm;
  let m;
  while ((m = re.exec(body)) !== null) {
    const text = m[2].trim();
    if (!text) continue;
    if (m[1].toLowerCase() === "x") done.push(text);
    else open.push(text);
  }
  return { open, done };
}

/**
 * @param {{ cards?: Array<{ column_id: string, title: string, description?: string }> }} board
 */
export function getMethodActivityState(board) {
  if (!board?.cards?.length) {
    return { running: [], recentDone: [], bubbles: [] };
  }
  const running = board.cards.filter((c) => c.column_id === "running");
  const done = board.cards.filter(
    (c) => c.column_id === "done" || c.column_id === "successful"
  );
  const recentDone = done.slice(-3).reverse();

  /** @type {{ tag: string, text: string, kind: string }[]} */
  const bubbles = [];

  for (const card of running) {
    const { open, done: subDone } = subtasksFromDescription(card.description);
    const current = open[0] || null;
    const lastDone = subDone.length ? subDone[subDone.length - 1] : null;
    const cardTag = running.length > 1 ? truncate(card.title || card.id, 20) : "Сейчас";

    if (current) {
      bubbles.push({ tag: cardTag, text: current, kind: "running", cardId: card.id });
    }
    if (lastDone) {
      bubbles.push({
        tag: running.length > 1 ? cardTag : "Готово",
        text: lastDone,
        kind: "done",
        cardId: card.id,
      });
    }
    if (!current && !lastDone) {
      bubbles.push({
        tag: cardTag,
        text: card.title,
        kind: "running",
        cardId: card.id,
      });
    }
  }

  if (!bubbles.length && running.length) {
    bubbles.push({ tag: "Сейчас", text: running[0].title, kind: "running" });
  }

  return { running, recentDone, bubbles };
}

/** @param {{ id?: string, title?: string }} node */
export function pickActivityTheme(node) {
  const id = String(node?.id || "").toLowerCase();
  const title = String(node?.title || "").toLowerCase();
  if (id.includes("op-") || id.includes("agent") || title.includes("агент") || title.includes("оператор")) {
    return "agent";
  }
  if (id.includes("rem") || id.includes("pretrain") || id.includes("div") || title.includes("обучен")) {
    return "train";
  }
  if (id.includes("ev") || id.includes("bench") || title.includes("бенч") || title.includes("метрик")) {
    return "scan";
  }
  return "lab";
}

/** @param {string} theme @param {string} uid unique suffix for SVG ids */
function activitySvgMarkup(theme, uid) {
  const g = `ma-${uid}`;
  const common = `
    <defs>
      <linearGradient id="${g}-grad" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="var(--pink)"/>
        <stop offset="50%" stop-color="var(--purple)"/>
        <stop offset="100%" stop-color="var(--cyan)"/>
      </linearGradient>
    </defs>`;

  if (theme === "agent") {
    return `<svg class="method-activity-svg theme-agent" viewBox="0 0 88 44" aria-hidden="true">${common}
      <ellipse class="ma-floor" cx="44" cy="38" rx="28" ry="4"/>
      <circle class="ma-core" cx="44" cy="22" r="9" fill="url(#${g}-grad)"/>
      <circle class="ma-core-ring" cx="44" cy="22" r="13"/>
      <g class="ma-orbit ma-orbit-a"><circle cx="44" cy="8" r="2.5" fill="var(--cyan)"/></g>
      <g class="ma-orbit ma-orbit-b"><circle cx="68" cy="22" r="2" fill="var(--pink)"/></g>
      <g class="ma-orbit ma-orbit-c"><circle cx="44" cy="36" r="1.8" fill="var(--lime)"/></g>
      <text class="ma-q" x="58" y="14">?</text>
    </svg>`;
  }

  if (theme === "train") {
    return `<svg class="method-activity-svg theme-train" viewBox="0 0 88 44" aria-hidden="true">${common}
      <rect class="ma-bar ma-bar-1" x="14" y="28" width="10" height="12" rx="2" fill="var(--purple)"/>
      <rect class="ma-bar ma-bar-2" x="30" y="20" width="10" height="20" rx="2" fill="var(--pink)"/>
      <rect class="ma-bar ma-bar-3" x="46" y="14" width="10" height="26" rx="2" fill="url(#${g}-grad)"/>
      <rect class="ma-bar ma-bar-4" x="62" y="22" width="10" height="18" rx="2" fill="var(--cyan)"/>
      <path class="ma-spark" d="M12 10 Q44 4 76 12" fill="none" stroke="url(#${g}-grad)" stroke-width="1.5"/>
    </svg>`;
  }

  if (theme === "scan") {
    return `<svg class="method-activity-svg theme-scan" viewBox="0 0 88 44" aria-hidden="true">${common}
      <circle class="ma-radar-bg" cx="44" cy="24" r="16"/>
      <path class="ma-radar-sweep" d="M44 24 L44 8 A16 16 0 0 1 58 18 Z" fill="url(#${g}-grad)" opacity="0.45"/>
      <circle class="ma-blip ma-blip-1" cx="52" cy="16" r="2"/>
      <circle class="ma-blip ma-blip-2" cx="36" cy="28" r="1.6"/>
      <polyline class="ma-chart" points="12,36 24,30 36,32 48,22 60,26 72,18" fill="none" stroke="var(--cyan)" stroke-width="1.4"/>
    </svg>`;
  }

  return `<svg class="method-activity-svg theme-lab" viewBox="0 0 88 44" aria-hidden="true">${common}
    <circle class="ma-nucleus" cx="44" cy="22" r="5" fill="url(#${g}-grad)"/>
    <ellipse class="ma-orbit-path" cx="44" cy="22" rx="22" ry="10"/>
    <g class="ma-orbit ma-orbit-a"><circle cx="66" cy="22" r="2.2" fill="var(--cyan)"/></g>
    <g class="ma-orbit ma-orbit-b"><circle cx="22" cy="22" r="2" fill="var(--pink)"/></g>
    <g class="ma-orbit ma-orbit-c"><circle cx="44" cy="12" r="1.6" fill="var(--lime)"/></g>
  </svg>`;
}

/**
 * @param {{ author?: string, task?: string, projectTitle?: string, methodTitle?: string }} meta
 */
export function formatActivityPreview(meta) {
  const author = String(meta?.author || "коллега").trim() || "коллега";
  const task = String(meta?.task || "эксперимент").trim() || "эксперимент";
  return `${author} и агент работают над задачей «${task}»`;
}

/**
 * @param {{ running: Array<{ id?: string }>, bubbles: { text: string }[] }} state
 * @param {{ author?: string, projectTitle?: string }} context
 */
export function activityPreviewMeta(state, context = {}) {
  const firstCard = state.running[0];
  const author =
    (firstCard?.id && context.authors?.[firstCard.id]) ||
    context.author ||
    "коллега";
  let task = "эксперимент";
  if (firstCard) {
    const { open } = subtasksFromDescription(firstCard.description);
    task = open[0] || firstCard.title || task;
  } else {
    const runningBubble = state.bubbles.find((b) => b.kind === "running");
    if (runningBubble) task = runningBubble.text;
  }
  return {
    author,
    task,
    projectTitle: context.projectTitle || "",
    methodTitle: context.methodTitle || "",
  };
}

/**
 * @param {{ running: unknown[], bubbles: { tag: string, text: string }[] }} state
 * @param {{ id?: string, title?: string }} node
 * @param {{ author?: string, projectTitle?: string, authors?: Record<string, string> }} [context]
 */
export function methodActivityHtml(state, node, context = {}) {
  if (!state.running.length) return "";

  const uid = String(node?.id || "m").replace(/[^a-z0-9_-]/gi, "").slice(0, 12) || "m";
  const theme = pickActivityTheme(node);
  const preview = activityPreviewMeta(
    { ...state, running: state.running },
    { ...context, methodTitle: node?.title }
  );
  const previewText = formatActivityPreview(preview);
  const hideInspect = Boolean(context.hideInspect);

  const firstCard = state.running[0];
  const cardId = firstCard?.id ? String(firstCard.id) : "";
  const monitorHint =
    state.running.length > 1
      ? `Монитор — ${state.running.length} в работе`
      : "Открыть монитор";

  const inspectBtn = hideInspect
    ? ""
    : `<button type="button" class="method-activity-inspect" data-card-id="${escapeHtml(cardId)}" title="${escapeHtml(monitorHint)}" aria-label="${escapeHtml(monitorHint)}">
        <svg class="method-activity-inspect-icon" viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="10.5" cy="10.5" r="5.75" fill="none" stroke="currentColor" stroke-width="2.25"/>
          <path d="M14.8 14.8 L19.5 19.5" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round"/>
        </svg>
      </button>`;

  return `<div class="method-activity" data-theme="${theme}"
    data-preview-author="${escapeHtml(preview.author)}"
    data-preview-task="${escapeHtml(preview.task)}"
    data-preview-project="${escapeHtml(preview.projectTitle)}"
    data-running-count="${state.running.length}"
    ${cardId ? `data-card-id="${escapeHtml(cardId)}"` : ""}
    aria-label="${escapeHtml(previewText)}">
    <div class="method-activity-stage">
      ${activitySvgMarkup(theme, uid)}
      ${inspectBtn}
    </div>
  </div>`;
}

function previewMetaFromEl(el) {
  if (!el) return null;
  const tagEl = el.querySelector(".method-activity-bubble-tag");
  const textEl = el.querySelector(".method-activity-bubble-text");
  const liveTask =
    tagEl?.textContent?.trim() === "Сейчас" ? textEl?.textContent?.trim() : "";
  return {
    author: el.dataset.previewAuthor || "коллега",
    task: liveTask || el.dataset.previewTask || "эксперимент",
    projectTitle: el.dataset.previewProject || "проект",
  };
}

function ensureActivityPreview() {
  if (previewEl) return previewEl;
  previewEl = document.createElement("div");
  previewEl.className = "method-activity-preview hidden";
  previewEl.setAttribute("role", "tooltip");
  previewEl.innerHTML = `<p class="method-activity-preview-text"></p>`;
  document.body.appendChild(previewEl);
  return previewEl;
}

function positionActivityPreview(anchor) {
  const tip = ensureActivityPreview();
  const rect = anchor.getBoundingClientRect();
  const margin = 10;
  let left = rect.left + rect.width / 2;
  let top = rect.top - margin;
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
  tip.classList.remove("is-below");
  const tipRect = tip.getBoundingClientRect();
  if (tipRect.top < margin) {
    top = rect.bottom + margin;
    tip.style.top = `${top}px`;
    tip.classList.add("is-below");
  }
  const half = tipRect.width / 2;
  left = Math.min(window.innerWidth - margin - half, Math.max(margin + half, left));
  tip.style.left = `${left}px`;
}

function showActivityPreview(anchor) {
  const meta = previewMetaFromEl(anchor);
  if (!meta) return;
  const tip = ensureActivityPreview();
  const textEl = tip.querySelector(".method-activity-preview-text");
  if (textEl) textEl.textContent = formatActivityPreview(meta);
  previewAnchor = anchor;
  tip.classList.remove("hidden");
  positionActivityPreview(anchor);
}

function hideActivityPreview() {
  previewAnchor = null;
  previewEl?.classList.add("hidden");
}

/** @param {{ x: number, y: number, scale: number }} cam */
export function worldToScreen(cam, wx, wy) {
  return { x: cam.x + wx * cam.scale, y: cam.y + wy * cam.scale };
}

function ensureActivityOverlay(viewport) {
  if (overlayEl?.parentElement === viewport) return overlayEl;
  overlayEl?.remove();
  overlayEl = document.createElement("div");
  overlayEl.id = "method-activity-overlay";
  overlayEl.className = "method-activity-overlay hidden";
  overlayEl.setAttribute("aria-hidden", "true");
  viewport.appendChild(overlayEl);
  return overlayEl;
}

function stopOverlayTimers() {
  for (const [key, t] of timers.entries()) {
    if (!key.startsWith("overlay:")) continue;
    clearInterval(t);
    timers.delete(key);
  }
}

function overlayPinScreenPosition(viewport, camera, item) {
  const pid = item.projectId;
  const nid = item.nodeId;
  if (pid && nid) {
    const below = document.querySelector(
      `.node-wrap[data-project-id="${pid}"][data-node-id="${nid}"] .node-kanban-below`
    );
    if (below) {
      const br = below.getBoundingClientRect();
      const vr = viewport.getBoundingClientRect();
      if (br.width > 0 && br.height > 0) {
        return {
          x: br.left + br.width / 2 - vr.left,
          y: br.bottom - vr.top - Math.min(br.height * 0.22, 14),
        };
      }
    }
    const inline = document.querySelector(
      `.node-wrap[data-project-id="${pid}"][data-node-id="${nid}"] .method-activity:not(.is-overlay-beacon)`
    );
    if (inline) {
      const ir = inline.getBoundingClientRect();
      const vr = viewport.getBoundingClientRect();
      if (ir.width > 0 && ir.height > 0) {
        return {
          x: ir.left + ir.width / 2 - vr.left,
          y: ir.top + ir.height / 2 - vr.top,
        };
      }
    }
  }
  return worldToScreen(camera, item.wx, item.wy);
}

function overlayItemsSignature(items) {
  return items.map((item) => item.key).join("|");
}

/**
 * Screen-space beacons for running methods (DOM-anchored when on map).
 * @returns {boolean} whether overlay pins were rebuilt (re-bind inspect handlers)
 */
export function syncMethodActivityOverlay(viewport, camera, items, visible) {
  const layer = ensureActivityOverlay(viewport);
  if (!visible || !items.length || !camera) {
    stopOverlayTimers();
    layer.replaceChildren();
    delete layer.dataset.itemsSig;
    layer.classList.add("hidden");
    layer.setAttribute("aria-hidden", "true");
    return false;
  }

  layer.classList.remove("hidden");
  layer.setAttribute("aria-hidden", "false");

  const sig = overlayItemsSignature(items);
  let rebuilt = false;
  if (layer.dataset.itemsSig !== sig) {
    stopOverlayTimers();
    layer.replaceChildren();
    layer.dataset.itemsSig = sig;
    rebuilt = true;

    for (const item of items) {
      const { x, y } = overlayPinScreenPosition(viewport, camera, item);
      const wrap = document.createElement("div");
      wrap.className = "method-activity-overlay-pin";
      wrap.dataset.projectId = item.projectId || "";
      wrap.dataset.nodeId = item.nodeId || "";
      wrap.style.left = `${x}px`;
      wrap.style.top = `${y}px`;
      wrap.innerHTML = methodActivityHtml(item.state, item.node, item.context || {});
      const block = wrap.firstElementChild;
      if (!block) continue;
      block.classList.add("is-overlay-beacon");
      layer.appendChild(wrap);
      startBubbleRotation(block, item.state.bubbles, `overlay:${item.key}`);
    }
  }

  const pins = layer.querySelectorAll(".method-activity-overlay-pin");
  items.forEach((item, idx) => {
    const pin = pins[idx];
    if (!pin) return;
    const { x, y } = overlayPinScreenPosition(viewport, camera, item);
    pin.style.left = `${x}px`;
    pin.style.top = `${y}px`;
  });

  return rebuilt;
}

/** Screen-fixed activity beacons when map zoom is too low for inline vignette. */
export function shouldUseActivityOverlay(cam) {
  if (!cam) return false;
  const fit = Math.max(cam.methodMaxScale ?? cam.maxScale ?? cam.scale, cam.minScale);
  // At native size the inline SVG is readable and must grow with its node.
  return cam.scale < Math.min(1, fit * ACTIVITY_INLINE_ZOOM_RATIO);
}

/** @param {{ scale: number, minScale: number, maxScale: number }} cam */
export function isMapZoomedOut(cam) {
  if (!cam) return false;
  const span = Math.max(cam.maxScale - cam.minScale, 0.001);
  return cam.scale <= cam.minScale + span * ZOOM_PREVIEW_RATIO;
}

/** @param {{ scale: number, minScale: number, maxScale: number, projectMaxScale?: number, methodMaxScale?: number }} cam */
export function isMapZoomedToCards(cam) {
  if (!cam || isMapZoomedOut(cam)) return false;
  const methodFit = cam.methodMaxScale ?? 0;
  if (methodFit <= (cam.projectMaxScale ?? cam.minScale) * 1.08) {
    return cam.scale >= cam.maxScale * 0.9;
  }
  return cam.scale >= methodFit * ZOOM_CARDS_METHOD_RATIO;
}

/** @param {HTMLElement | null} viewport @param {{ scale: number, minScale: number, maxScale: number } | null} cam @param {boolean | null} overlayActive */
export function syncMethodActivityZoomMode(viewport, cam, overlayActive = null) {
  if (!viewport) return;
  const overlay = overlayActive ?? shouldUseActivityOverlay(cam);
  const zoomedOut = isMapZoomedOut(cam);
  viewport.classList.toggle("is-activity-overlay", overlay);
  viewport.classList.toggle("is-map-zoomed-out", zoomedOut);
  onPreviewReposition();
}

function onPreviewReposition() {
  if (previewAnchor && !previewEl?.classList.contains("hidden")) {
    positionActivityPreview(previewAnchor);
  }
}

/** @param {HTMLElement} viewport @param {() => { scale: number, minScale: number, maxScale: number } | null} getCamera */
export function bindMethodActivityZoomPreview(viewport, getCamera) {
  if (!viewport || previewBoundViewport === viewport) return;
  previewBoundViewport = viewport;

  viewport.addEventListener("pointerover", (e) => {
    const block = e.target.closest?.(".method-activity");
    if (!block || !viewport.contains(block)) return;
    showActivityPreview(block);
  });

  viewport.addEventListener("pointerout", (e) => {
    const block = e.target.closest?.(".method-activity");
    if (!block) return;
    const related = e.relatedTarget;
    if (related && block.contains(related)) return;
    hideActivityPreview();
  });

  window.addEventListener("scroll", onPreviewReposition, true);
  window.addEventListener("resize", onPreviewReposition);
}

function stopBubbleRotation(key) {
  const t = timers.get(key);
  if (t) clearInterval(t);
  timers.delete(key);
}

function startBubbleRotation(el, bubbles, key) {
  stopBubbleRotation(key);
  if (!el || bubbles.length < 2) return;
  let idx = 0;
  const tagEl = el.querySelector(".method-activity-bubble-tag");
  const textEl = el.querySelector(".method-activity-bubble-text");
  const bubbleEl = el.querySelector(".method-activity-bubble");
  if (!tagEl || !textEl || !bubbleEl) return;

  const tick = () => {
    idx = (idx + 1) % bubbles.length;
    const item = bubbles[idx];
    tagEl.textContent = item.tag;
    textEl.textContent = truncate(item.text);
    bubbleEl.classList.remove("is-running", "is-done");
    bubbleEl.classList.add(item.kind === "done" ? "is-done" : "is-running");
    bubbleEl.classList.remove("is-switching");
    void bubbleEl.offsetWidth;
    bubbleEl.classList.add("is-switching");
  };

  timers.set(key, setInterval(tick, BUBBLE_TICK_MS));
}

function applyActivityPreviewDataset(block, state, node, context = {}) {
  const preview = activityPreviewMeta(state, { ...context, methodTitle: node?.title });
  const previewText = formatActivityPreview(preview);
  block.dataset.previewAuthor = preview.author;
  block.dataset.previewTask = preview.task;
  block.dataset.previewProject = preview.projectTitle;
  block.setAttribute("aria-label", previewText);
  block.removeAttribute("title");
  block.querySelector(":scope > .method-activity-author")?.remove();
}

function mountActivityInBelow(belowEl, block) {
  if (!belowEl || !block) return;
  belowEl.appendChild(block);
}

/**
 * @param {HTMLElement} belowEl .node-kanban-below
 * @param {{ id: string, title?: string }} node
 * @param {{ cards?: object[] } | null} board
 * @param {{ author?: string, projectTitle?: string, authors?: Record<string, string> }} [context]
 */
export function syncMethodActivity(belowEl, node, board, context = {}) {
  const state = getMethodActivityState(board);
  belowEl.querySelector(":scope > .method-activity-stack")?.remove();
  belowEl.querySelector(".node-kanban-compact .method-activity")?.remove();
  belowEl.querySelector(".node-kanban-compact .method-activity-stack")?.remove();
  let block = belowEl.querySelector(":scope > .method-activity");
  const key = `${belowEl.closest(".node-wrap")?.dataset?.projectId || ""}:${node.id}`;
  const runningSig = state.running.map((c) => c.id).join("|");

  if (!state.running.length) {
    stopBubbleRotation(key);
    block?.remove();
    belowEl.classList.remove("has-method-activity");
    return;
  }

  belowEl.classList.add("has-method-activity");

  const needsRebuild =
    !block || block.dataset.runningCount !== String(state.running.length);

  if (needsRebuild) {
    stopBubbleRotation(key);
    block?.remove();
    const wrap = document.createElement("div");
    wrap.innerHTML = methodActivityHtml(state, node, context);
    block = wrap.firstElementChild;
    if (!block) return;
    block.dataset.runningCount = String(state.running.length);
    block.dataset.runningSig = runningSig;
    mountActivityInBelow(belowEl, block);
    return;
  }

  if (!block) {
    const wrap = document.createElement("div");
    wrap.innerHTML = methodActivityHtml(state, node, context);
    block = wrap.firstElementChild;
    if (!block) return;
    block.dataset.runningCount = String(state.running.length);
    block.dataset.runningSig = runningSig;
    mountActivityInBelow(belowEl, block);
  } else {
    applyActivityPreviewDataset(block, state, node, context);
    block.dataset.runningCount = String(state.running.length);
    if (runningSig !== block.dataset.runningSig) {
      block.dataset.runningSig = runningSig;
      const inspect = block.querySelector(".method-activity-inspect");
      const firstId = state.running[0]?.id;
      const hint =
        state.running.length > 1
          ? `Монитор — ${state.running.length} в работе`
          : "Открыть монитор";
      if (inspect && firstId) {
        inspect.dataset.cardId = String(firstId);
        inspect.title = hint;
        inspect.setAttribute("aria-label", hint);
      }
    }
  }
}

export function disposeMethodActivityTimers() {
  for (const t of timers.values()) clearInterval(t);
  timers.clear();
  overlayEl?.remove();
  overlayEl = null;
}
