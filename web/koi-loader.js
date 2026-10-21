/** Animated loader with rotating status hints (literature, related work, agent chat). */

const HINT_FADE_MS = 280;
const HINT_ROTATE_MS = 2400;

export const KOI_LOADER_POOLS = {
  literature: [
    "Подключаюсь к Literature Inbox…",
    "Ищу статьи по ключевым словам проекта…",
    "Листаю arXiv…",
    "Скачиваю PDF…",
    "Читаю абстракты…",
    "Выделяю ключевые идеи…",
    "Анализирую кластеры…",
    "Смотрю детали литературы…",
    "Группирую ответы по темам…",
    "Сверяю с контекстом проекта…",
  ],
  related: [
    "Подключаюсь к Literature Inbox…",
    "Читаю выбранные кластеры…",
    "Сопоставляю с гипотезами проекта…",
    "Ищу пробелы в related work…",
    "Смотрю, что уже известно…",
    "Формулирую связь с вашей работой…",
    "Пишу черновик обзора…",
  ],
  relatedQueue: [
    "Скоро агент возьмётся за вашу задачу…",
    "Задача стоит в очереди Literature Inbox…",
    "Watcher скоро подхватит запрос…",
    "Ждём свободного агента в Cursor…",
    "Related Work уже в списке задач…",
    "Обычно это занимает несколько секунд…",
    "Агент скоро подключится…",
  ],
  agent: [
    "Подключаюсь к ResearcherOS Chat Inbox…",
    "Сверяю research.json…",
    "Ищу отчёты экспериментов…",
    "Проверяю гипотезы на карте…",
    "Читаю выводы методов…",
    "Смотрю базу знаний…",
    "Формирую ответ…",
  ],
  paper: [
    "Подключаюсь к Paper Inbox…",
    "Читаю граф гипотез проекта…",
    "Сверяю выводы research.json…",
    "Собираю отчёты экспериментов…",
    "Вставляю графики из assets…",
    "Пишу черновик в LaTeX…",
    "Форматирую под NeurIPS…",
    "Компилирую PDF…",
    "Проверяю библиографию…",
    "Финальная сборка статьи…",
  ],
};

const hintTimers = new WeakMap();

const LOADER_VIZ_HTML = `
  <div class="koi-loader__viz" aria-hidden="true">
    <div class="koi-loader__ring"></div>
    <div class="koi-loader__ring koi-loader__ring--delay"></div>
    <span class="koi-loader__dot koi-loader__dot--a"></span>
    <span class="koi-loader__dot koi-loader__dot--b"></span>
    <span class="koi-loader__dot koi-loader__dot--c"></span>
    <div class="koi-loader__center">
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <path fill="currentColor" d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2.5L18.5 10H13V4.5zM8 13h8v2H8v-2zm0 4h5v2H8v-2z"/>
      </svg>
    </div>
  </div>`;

function resolveRoot(rootOrId) {
  if (!rootOrId) return null;
  if (typeof rootOrId === "string") return document.getElementById(rootOrId);
  return rootOrId;
}

function stepEl(root) {
  return (
    root.querySelector(".koi-loader__step") ||
    root.querySelector(".rw-loader-step") ||
    root.querySelector("#rw-loader-step") ||
    root.querySelector("#rw-related-loader-step") ||
    root.querySelector("#paper-loader-step")
  );
}

function hintEl(root) {
  return root.querySelector(".koi-loader__hint");
}

function ensureLoaderStructure(root) {
  if (!root || root.dataset.koiLoaderReady) return;
  root.classList.add("koi-loader");
  const hasViz = root.querySelector(".koi-loader__viz");
  const legacySpinner = root.querySelector(".rw-loader-spinner");
  if (!hasViz) {
    if (legacySpinner) legacySpinner.remove();
    root.insertAdjacentHTML("afterbegin", LOADER_VIZ_HTML);
  }
  if (!hintEl(root)) {
    const step = stepEl(root);
    const hint = document.createElement("p");
    hint.className = "koi-loader__hint";
    hint.setAttribute("aria-hidden", "true");
    if (step?.nextSibling) root.insertBefore(hint, step.nextSibling);
    else root.appendChild(hint);
  }
  if (stepEl(root) && !stepEl(root).classList.contains("koi-loader__step")) {
    stepEl(root).classList.add("koi-loader__step");
  }
  root.dataset.koiLoaderReady = "1";
}

function stopLoaderHints(root) {
  const timer = hintTimers.get(root);
  if (timer) {
    clearInterval(timer);
    hintTimers.delete(root);
  }
  const hint =
    root?.classList?.contains("koi-loader__hint") ||
    root?.classList?.contains("koi-loader__hint--inline") ||
    root?.classList?.contains("koi-loader__hint--panel")
      ? root
      : hintEl(root);
  if (hint) {
    hint.textContent = "";
    hint.classList.remove("is-fading");
    hint.setAttribute("aria-hidden", "true");
  }
}

function startLoaderHints(root, pool = "literature", targetHint = null) {
  stopLoaderHints(root);
  const hint = targetHint || hintEl(root);
  if (!hint) return;
  const messages = KOI_LOADER_POOLS[pool] || KOI_LOADER_POOLS.literature;
  if (!messages.length) return;

  let idx = Math.floor(Math.random() * messages.length);
  hint.setAttribute("aria-hidden", "false");
  hint.classList.add("koi-loader__hint");

  const tick = () => {
    hint.classList.add("is-fading");
    setTimeout(() => {
      hint.textContent = messages[idx % messages.length];
      idx += 1;
      hint.classList.remove("is-fading");
    }, HINT_FADE_MS);
  };

  tick();
  hintTimers.set(root, setInterval(tick, HINT_ROTATE_MS));
}

export function attachRotatingHint(hintEl, pool = "literature") {
  if (!hintEl) return;
  startLoaderHints(hintEl, pool, hintEl);
}

export function detachRotatingHint(hintEl) {
  if (!hintEl) return;
  stopLoaderHints(hintEl);
}

export function showKoiLoader(rootOrId, { step = "Подготовка…", pool = "literature" } = {}) {
  const root = resolveRoot(rootOrId);
  if (!root) return;
  ensureLoaderStructure(root);
  const stepNode = stepEl(root);
  if (stepNode) stepNode.textContent = step;
  root.classList.remove("hidden");
  root.setAttribute("aria-busy", "true");
  startLoaderHints(root, pool);
}

export function hideKoiLoader(rootOrId) {
  const root = resolveRoot(rootOrId);
  if (!root) return;
  stopLoaderHints(root);
  root.classList.add("hidden");
  root.setAttribute("aria-busy", "false");
}

export function setKoiLoaderStep(rootOrId, step, { pool } = {}) {
  const root = resolveRoot(rootOrId);
  if (!root) return;
  const stepNode = stepEl(root);
  if (stepNode && step) stepNode.textContent = step;
  if (pool && hintTimers.has(root)) startLoaderHints(root, pool);
}

export function koiLoaderTypingHtml(pool = "agent") {
  const messages = KOI_LOADER_POOLS[pool] || KOI_LOADER_POOLS.agent;
  const first = messages[0] || "Агент думает…";
  return (
    `<div class="agent-chat-typing koi-loader-inline" data-koi-loader-pool="${pool}" aria-label="Агент работает">` +
    `<div class="koi-loader koi-loader--inline" aria-hidden="true">` +
    LOADER_VIZ_HTML +
    `</div>` +
    `<div class="agent-chat-typing-text">` +
    `<span class="agent-chat-typing-label">Агент работает</span>` +
    `<span class="koi-loader__hint koi-loader__hint--inline">${first}</span>` +
    `</div>` +
    `</div>`
  );
}

export function refreshInlineLoaderHints(container) {
  if (!container) return;
  container.querySelectorAll("[data-koi-loader-pool]").forEach((block) => {
    const hint = block.querySelector(".koi-loader__hint--inline");
    if (!hint || hintTimers.has(hint)) return;
    const pool = block.dataset.koiLoaderPool || "agent";
    const messages = KOI_LOADER_POOLS[pool] || KOI_LOADER_POOLS.agent;
    let idx = Math.floor(Math.random() * messages.length);

    const tick = () => {
      hint.classList.add("is-fading");
      setTimeout(() => {
        hint.textContent = messages[idx % messages.length];
        idx += 1;
        hint.classList.remove("is-fading");
      }, HINT_FADE_MS);
    };

    tick();
    hintTimers.set(hint, setInterval(tick, HINT_ROTATE_MS));
  });
}

export function clearInlineLoaderHints(container) {
  if (!container) return;
  container.querySelectorAll(".koi-loader__hint--inline").forEach((hint) => {
    const timer = hintTimers.get(hint);
    if (timer) {
      clearInterval(timer);
      hintTimers.delete(hint);
    }
  });
}
