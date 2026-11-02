/** Пояснения типов узлов дерева проекта и подсказки при добавлении. */

export const NODE_TYPE_HELP = {
  problem: {
    title: "Проблема",
    subtitle: "Проблемная ситуация в предметной области",
    what:
      "Что не так в научной или инженерной задаче и как это проявляется на практике. Только наблюдаемый провал — без объяснения «почему».",
    content:
      "Заголовок — суть проблемы. В описании — контекст, условия воспроизведения, метрики, как именно видите сбой.",
    example:
      "«На длинных эпизодах агент плохо принимает решения: не помнит, что было раньше»",
  },
  cause: {
    title: "Причина",
    subtitle: "Объяснительная гипотеза",
    what:
      "Предположение о механизме: из-за чего возникает проблема. Это не решение, а ответ на вопрос «почему так?».",
    content:
      "Заголовок: «Причина: …». В описании — какой компонент, процесс или ограничение даёт сбой и при каких условиях.",
    example: "«Причина: у агента нет модуля памяти — контекст прошлых шагов теряется»",
  },
  cause_evidence: {
    title: "Доказательство",
    subtitle: "Эмпирическая проверка причины",
    what:
      "Какие наблюдения или измерения покажут, верна ли объяснительная гипотеза — до того как предлагать устранение.",
    content:
      "Заголовок: «Доказательство: …». В описании — что именно измеряете или сравниваете. Протокол эксперимента — в методе ниже.",
    example:
      "«Доказательство: на эпизодах 50+ шагов в логе нет ссылок на ранние события»",
  },
  remediation: {
    title: "Гипотеза устранения",
    subtitle: "Интервенционная гипотеза",
    what:
      "Предположение, как ослабить причину, обойти её или убрать проблему целиком — снизить влияние или решить напрямую.",
    content:
      "Заголовок: «Устранение: …». В описании — что меняете в системе, какой эффект ждёте и по какой метрике поймёте успех.",
    example:
      "«Устранение: episodic memory с суммаризацией прошлых шагов перед каждым действием»",
  },
  method: {
    title: "Метод",
    subtitle: "Протокол проверки",
    what:
      "Конкретный способ проверить доказательство или гипотезу устранения: что делаем, что измеряем, как интерпретируем результат.",
    content:
      "Заголовок — название протокола. В описании — шаги, датасет, метрики, критерий supported/refuted. Карточки прогонов — в канбане.",
    example:
      "«A/B: агент с памятью vs без на эпизодах 50+ шагов, метрика — success rate»",
  },
};

/** Зачем добавлять дочерний узел от данного родителя. */
export const ADD_CHILD_WHY = {
  problem: {
    cause: "Сформулировать объяснительную гипотезу — почему проблема возникает.",
  },
  cause: {
    cause_evidence:
      "Проверить причину данными: что должно наблюдаться, если гипотеза верна.",
    remediation:
      "Предложить интервенцию: как ослабить эту причину или обойти её.",
  },
  cause_evidence: {
    method: "Спланировать эксперимент, который соберёт эти наблюдения.",
  },
  remediation: {
    method: "Спланировать эксперимент, который проверит гипотезу устранения.",
  },
};

const TYPE_LABELS_FALLBACK = {
  problem: "Проблема",
  cause: "Причина",
  cause_evidence: "Доказательство",
  remediation: "Гипотеза",
  method: "Метод",
};

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

export function typeLabel(nodeType, labels = TYPE_LABELS_FALLBACK) {
  return labels[nodeType] || TYPE_LABELS_FALLBACK[nodeType] || nodeType;
}

export function addChildWhy(parentType, childType) {
  return ADD_CHILD_WHY[parentType]?.[childType] || "";
}

export function addChildPreviewItems(parentType, allowedTypes, labels) {
  return allowedTypes.map((t) => ({
    type: t,
    label: typeLabel(t, labels),
    why: addChildWhy(parentType, t),
    help: NODE_TYPE_HELP[t],
  }));
}

export function formatAddChildFormatHint(nodeType) {
  const h = NODE_TYPE_HELP[nodeType];
  if (!h) return "";
  let html = `<strong>Формат блока:</strong> ${escapeHtml(h.content)}`;
  if (h.example) {
    html += `<br><span class="add-child-format-example">Пример заголовка: ${escapeHtml(h.example)}</span>`;
  }
  return html;
}

export function formatAddChildContextHint(parentType, childType) {
  const why = addChildWhy(parentType, childType);
  if (!why) return "";
  return why;
}

export function formatAddParentIntro(parentType, allowedTypes, labels) {
  const items = addChildPreviewItems(parentType, allowedTypes, labels);
  if (!items.length) return "";
  if (items.length === 1) {
    return `От «${typeLabel(parentType, labels)}» добавится узел «${items[0].label}».`;
  }
  const names = items.map((i) => `«${i.label}»`).join(" или ");
  return `От «${typeLabel(parentType, labels)}» можно добавить ${names} — выберите тип ниже.`;
}

let helpOverlay = null;
let helpOverlayKeyHandler = null;

function buildHelpPanelHtml(help) {
  return `
    <p class="node-type-help-popover-title">${escapeHtml(help.title)}</p>
    ${help.subtitle ? `<p class="node-type-help-popover-subtitle">${escapeHtml(help.subtitle)}</p>` : ""}
    <p class="node-type-help-popover-what">${escapeHtml(help.what)}</p>
    <p class="node-type-help-popover-content"><span class="node-type-help-popover-label">Что писать:</span> ${escapeHtml(help.content)}</p>
    ${help.example ? `<p class="node-type-help-popover-example"><span class="node-type-help-popover-label">Пример:</span> ${escapeHtml(help.example)}</p>` : ""}`;
}

function ensureHelpOverlay() {
  if (helpOverlay) return helpOverlay;

  helpOverlay = document.createElement("div");
  helpOverlay.id = "node-type-help-overlay";
  helpOverlay.className = "node-type-help-overlay hidden";
  helpOverlay.innerHTML = `
    <div class="node-type-help-backdrop" data-close="node-type-help"></div>
    <div class="node-type-help-panel" role="dialog" aria-modal="true" aria-labelledby="node-type-help-title">
      <button type="button" class="node-type-help-close" aria-label="Закрыть">×</button>
      <div class="node-type-help-panel-body"></div>
    </div>`;

  helpOverlay.querySelector(".node-type-help-backdrop")?.addEventListener("click", closeNodeTypeHelp);
  helpOverlay.querySelector(".node-type-help-close")?.addEventListener("click", closeNodeTypeHelp);

  document.body.appendChild(helpOverlay);
  return helpOverlay;
}

export function closeNodeTypeHelp() {
  if (!helpOverlay || helpOverlay.classList.contains("hidden")) return;
  helpOverlay.classList.add("hidden");
  document.body.classList.remove("node-type-help-open");
  if (helpOverlayKeyHandler) {
    document.removeEventListener("keydown", helpOverlayKeyHandler);
    helpOverlayKeyHandler = null;
  }
}

export function openNodeTypeHelp(nodeType) {
  const help = NODE_TYPE_HELP[nodeType];
  if (!help) return;

  const overlay = ensureHelpOverlay();
  const body = overlay.querySelector(".node-type-help-panel-body");
  const panel = overlay.querySelector(".node-type-help-panel");
  if (!body || !panel) return;

  body.innerHTML = buildHelpPanelHtml(help);
  const titleEl = body.querySelector(".node-type-help-popover-title");
  if (titleEl) titleEl.id = "node-type-help-title";

  overlay.classList.remove("hidden");
  document.body.classList.add("node-type-help-open");

  if (!helpOverlayKeyHandler) {
    helpOverlayKeyHandler = (e) => {
      if (e.key === "Escape") closeNodeTypeHelp();
    };
    document.addEventListener("keydown", helpOverlayKeyHandler);
  }

  overlay.querySelector(".node-type-help-close")?.focus();
}

/**
 * «?» в углу карточки узла — открывает полноэкранную подсказку.
 */
export function mountNodeTypeHelp(wrap, nodeType) {
  const help = NODE_TYPE_HELP[nodeType];
  if (!help || !wrap) return;

  const mapEl = wrap.querySelector(".map-node");
  if (!mapEl || mapEl.querySelector(".node-type-help-trigger")) return;

  mapEl.classList.add("has-type-help");

  const trigger = document.createElement("span");
  trigger.className = "node-type-help-trigger";
  trigger.title = help.title;
  trigger.innerHTML = `<span class="node-type-help-q" aria-hidden="true">?</span>`;

  trigger.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    openNodeTypeHelp(nodeType);
  });
  trigger.addEventListener("mousedown", (e) => e.stopPropagation());

  mapEl.appendChild(trigger);
}

function parentWrapSelector(parent, projectId) {
  const pid = projectId ? `[data-project-id="${projectId}"]` : "";
  return `.node-wrap[data-node-id="${parent.id}"]${pid}`;
}

function setAddParentHighlight(parent, projectId, on) {
  const sel = parentWrapSelector(parent, projectId);
  document.querySelectorAll(sel).forEach((w) => {
    w.classList.toggle("is-add-parent-highlight", on);
  });
}

function buildAddPreviewGhosts(items) {
  const ghosts = document.createElement("div");
  ghosts.className = "add-preview-ghosts";
  ghosts.setAttribute("aria-hidden", "true");
  ghosts.innerHTML = items
    .map(
      (item) => `
    <div class="add-preview-ghost add-preview-ghost--${item.type}">
      <span class="add-preview-ghost-label">${escapeHtml(item.label)}</span>
      ${item.why ? `<span class="add-preview-ghost-why">${escapeHtml(item.why)}</span>` : ""}
    </div>`
    )
    .join("");
  return ghosts;
}

/**
 * Кнопка «+» с подсветкой родителя и превью добавляемых типов.
 * @param {{ readOnly?: boolean }} opts
 */
export function mountAddNodeButton({
  pos,
  parent,
  projectId,
  labels,
  allowedTypes,
  onOpen,
  mount,
  readOnly = false,
}) {
  const size = { w: 80, h: 80, round: "50%" };
  const items = addChildPreviewItems(parent.node_type, allowedTypes, labels);
  const singleLabel = items.length === 1 ? items[0].label : null;
  const hubHint = "В Hub нельзя добавлять узлы — только просмотр";

  const el = document.createElement("button");
  el.type = "button";
  el.className = "map-node add-node" + (readOnly ? " add-node--readonly" : "");
  el.dataset.parentId = parent.id;
  if (readOnly) {
    el.disabled = true;
    el.setAttribute("aria-disabled", "true");
    el.title = hubHint;
    el.setAttribute("aria-label", hubHint);
  } else {
    const ariaLabel =
      items.length === 1
        ? `Добавить ${items[0].label.toLowerCase()}`
        : `Добавить: ${items.map((i) => i.label.toLowerCase()).join(" или ")}`;
    el.setAttribute("aria-label", ariaLabel);
  }
  el.innerHTML = `
    <span class="node-label add-node-dynamic-label">${singleLabel ? `+ ${singleLabel}` : "Добавить"}</span>
    <span class="add-plus">+</span>`;

  const addWrap = document.createElement("div");
  addWrap.className =
    "node-wrap add-slot-wrap" + (readOnly ? " add-slot-wrap--readonly" : "");
  if (projectId) addWrap.dataset.projectId = projectId;
  addWrap.dataset.parentId = parent.id;
  addWrap.style.left = `${pos.x}px`;
  addWrap.style.top = `${pos.y}px`;
  addWrap.style.transform = "translate(-50%, -50%)";
  if (readOnly) addWrap.title = hubHint;

  addWrap.appendChild(buildAddPreviewGhosts(items));

  el.style.width = `${size.w}px`;
  el.style.height = `${size.h}px`;
  el.style.borderRadius = size.round;

  const showPreview = () => {
    if (readOnly) return;
    addWrap.classList.add("is-add-preview-active");
    setAddParentHighlight(parent, projectId, true);
  };
  const hidePreview = () => {
    addWrap.classList.remove("is-add-preview-active");
    setAddParentHighlight(parent, projectId, false);
  };

  addWrap.addEventListener("mouseenter", showPreview);
  addWrap.addEventListener("mouseleave", hidePreview);
  addWrap.addEventListener("focusin", showPreview);
  addWrap.addEventListener("focusout", (e) => {
    if (!addWrap.contains(e.relatedTarget)) hidePreview();
  });

  el.addEventListener("click", (e) => {
    e.stopPropagation();
    if (readOnly) return;
    hidePreview();
    onOpen(parent);
  });

  addWrap.appendChild(el);
  if (mount) {
    mount(addWrap);
  }
  return addWrap;
}
