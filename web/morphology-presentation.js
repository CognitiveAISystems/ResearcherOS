import { KoiApi } from "./api.js?v=20260821e";

const COPY = {
  ru: {
    presentationTitle: "Презентация статьи",
    sources: "Источники",
    showSources: "Показать источники",
    hideSources: "Скрыть источники",
    fullscreen: "На весь экран",
    previous: "Предыдущий слайд",
    next: "Следующий слайд",
    close: "Закрыть презентацию",
    language: "Язык презентации",
    noQuotes: "Для этого слайда нет дословных цитат.",
    noSource: "без якоря",
    figure: "Рисунок из статьи",
    table: "Таблица из статьи",
    math: "Формула из статьи",
    algorithm: "Шаги метода",
    assemble: "Собрать презентацию",
    open: "Открыть презентацию",
    copyPrompt: "Показать задание презентации",
    staged: "Презентация ещё собирается. Вставьте текст задания в чат Cursor.",
    invalid: "Проверка не приняла слайды. Соберите презентацию заново.",
    missing: "В этом прогоне нет разбора формул. Откройте более новый прогон морфологии.",
    copied: "Текст задания скопирован.",
    shown: "Текст задания ниже. Скопируйте его вручную, если буфер обмена пуст.",
  },
  en: {
    presentationTitle: "Article presentation",
    sources: "Sources",
    showSources: "Show sources",
    hideSources: "Hide sources",
    fullscreen: "Full screen",
    previous: "Previous slide",
    next: "Next slide",
    close: "Close presentation",
    language: "Presentation language",
    noQuotes: "This slide has no direct quotes.",
    noSource: "—",
    figure: "Figure from the paper",
    table: "Table from the paper",
    math: "Formula from the paper",
    algorithm: "Method steps",
    assemble: "Build presentation",
    open: "Open presentation",
    copyPrompt: "Show presentation task",
    staged: "The presentation is still being built. Paste the task text into Cursor chat.",
    invalid: "The review rejected the slides. Build the presentation again.",
    missing: "This run has no formula lessons. Open a newer morphology run.",
    copied: "The task text is copied.",
    shown: "The task text is below. Copy it by hand if the clipboard is empty.",
  },
};

const PRESENTATION_LANGUAGE_KEY = "koi-morph-presentation-language";
const POLL_MS = 4000;

async function writeClipboard(text) {
  if (!text) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.left = "-9999px";
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function localized(value, language) {
  if (!value || typeof value !== "object") return String(value || "");
  return String(value[language] || value.ru || value.en || "");
}

function sourceMath(anchor) {
  if (!anchor) return null;
  for (const root of document.querySelectorAll(".morph-article-body")) {
    const math = root.querySelector(`#${CSS.escape(anchor)}`);
    if (math) return math;
  }
  return null;
}

function renderMathMarkup(expression) {
  const occurrence = expression?.occurrences?.[0];
  const original = sourceMath(occurrence?.source_anchor);
  const supportsMath = "MathMLElement" in window || CSS.supports?.("math-style", "normal");
  if (original && supportsMath) {
    const clone = original.cloneNode(true);
    clone.removeAttribute("id");
    clone.querySelectorAll("[id]").forEach((element) => element.removeAttribute("id"));
    const host = document.createElement("div");
    host.className = "morph-presentation-math";
    host.append(clone);
    return host.outerHTML;
  }
  return `<code class="morph-presentation-math">${escapeHtml(expression?.latex || "")}</code>`;
}

function renderVisual(slide, language, mathAnalysis) {
  const visual = slide?.visual;
  if (!visual) return "";
  if (visual.kind === "math") {
    const expressions = Array.isArray(mathAnalysis?.expressions) ? mathAnalysis.expressions : [];
    return (visual.expression_ids || [])
      .map((expressionId) => {
        const expression = expressions.find((row) => row.id === expressionId);
        return `
          <section class="morph-presentation-math-block">
            ${renderMathMarkup(expression)}
            <p>${escapeHtml(localized(expression?.meaning, language) || localized(slide.body, language))}</p>
          </section>`;
      })
      .join("");
  }
  if (visual.kind === "algorithm") {
    const steps = (visual.steps || [])
      .map(
        (step) => `
          <li>
            <span>${escapeHtml(step.order)}</span>
            <p>${escapeHtml(localized(step.text, language))}</p>
          </li>`
      )
      .join("");
    return `<ol class="morph-presentation-steps">${steps}</ol>`;
  }
  if (visual.kind === "figure") {
    const width = Math.max(55, Math.round(Number(visual.render_width_fraction || 0.7) * 100));
    return `
      <figure class="morph-presentation-paper-figure is-large">
        <div class="morph-presentation-paper-figure-media" style="--figure-width: ${width}%">
          <img src="${escapeHtml(visual.src)}" alt="${escapeHtml(localized(visual.explanation, language))}" />
        </div>
        <figcaption>
          <small>${escapeHtml(COPY[language].figure)}</small>
          <strong>${escapeHtml(visual.source_caption || "")}</strong>
          <p>${escapeHtml(localized(visual.explanation, language))}</p>
        </figcaption>
      </figure>`;
  }
  if (visual.kind === "table") {
    const highlights = new Set(visual.highlight_cell_ids || []);
    const header = (visual.columns || [])
      .map((column) => `<th>${escapeHtml(column)}</th>`)
      .join("");
    const rows = (visual.rows || [])
      .map((row) => {
        const cells = (row.cells || [])
          .map((cell) => {
            const on = highlights.has(cell.source_anchor);
            return `<td class="${on ? "is-highlight" : ""}">${escapeHtml(cell.value)}</td>`;
          })
          .join("");
        return `<tr><th scope="row">${escapeHtml(row.label)}</th>${cells}</tr>`;
      })
      .join("");
    return `
      <figure class="morph-presentation-table">
        <table>
          <thead><tr><th></th>${header}</tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <figcaption>
          <small>${escapeHtml(COPY[language].table)}</small>
          <strong>${escapeHtml(visual.source_caption || "")}</strong>
          <p>${escapeHtml(localized(visual.explanation, language))}</p>
        </figcaption>
      </figure>`;
  }
  return "";
}

function renderCover(slide, paper, language) {
  const copy = COPY[language];
  const meta = [paper?.year, paper?.authors].filter(Boolean).join(" · ");
  const link = paper?.url
    ? `<a class="morph-presentation-cover-link" href="${escapeHtml(
        paper.url
      )}" target="_blank" rel="noreferrer">${escapeHtml(
        String(paper.url).replace(/^https?:\/\//, "")
      )}</a>`
    : "";
  return `
    <article class="morph-presentation-slide is-cover">
      <span class="morph-presentation-brand">ResearcherOS</span>
      <div class="morph-presentation-cover-copy">
        <p class="morph-presentation-eyebrow">${escapeHtml(copy.presentationTitle)}</p>
        <h2>${escapeHtml(localized(slide.title, language))}</h2>
        <p class="morph-presentation-cover-meta">${escapeHtml(localized(slide.body, language))}</p>
        ${meta ? `<p class="morph-presentation-cover-meta">${escapeHtml(meta)}</p>` : ""}
        ${link}
      </div>
      <div class="morph-presentation-orbit" aria-hidden="true">
        <span></span><span></span><span></span>
      </div>
    </article>`;
}

function renderContentSlide(slide, index, total, language, mathAnalysis) {
  const copy = COPY[language];
  const visual = renderVisual(slide, language, mathAnalysis);
  return `
    <article class="morph-presentation-slide is-${escapeHtml(slide.kind)}">
      <header class="morph-presentation-slide-head">
        <p class="morph-presentation-eyebrow">${String(index).padStart(2, "0")} / ${String(
          total
        ).padStart(2, "0")} · ${escapeHtml(slide.section_anchor || "")}</p>
        <h2>${escapeHtml(localized(slide.title, language))}</h2>
      </header>
      <div class="morph-presentation-slide-grid ${visual ? "has-visual" : "is-text"}">
        <div class="morph-presentation-claim">
          <span class="morph-presentation-quote-mark" aria-hidden="true">“</span>
          <p>${escapeHtml(localized(slide.body, language))}</p>
        </div>
        ${visual ? `<div class="morph-presentation-visual">${visual}</div>` : ""}
      </div>
    </article>`;
}

function renderSources(slide, language) {
  const copy = COPY[language];
  const parts = [];
  if (slide?.evidence_quote) {
    parts.push(`
      <figure class="morph-presentation-source">
        <div class="morph-presentation-source-head">
          <span>${escapeHtml(copy.sources)}</span>
          <span>${escapeHtml(slide.section_anchor || copy.noSource)}</span>
        </div>
        <blockquote>${escapeHtml(slide.evidence_quote)}</blockquote>
      </figure>`);
  }
  const visual = slide?.visual;
  if (visual?.kind === "figure" && visual.source_caption) {
    parts.push(`
      <figure class="morph-presentation-source is-figure">
        <div class="morph-presentation-source-head">
          <span>${escapeHtml(copy.figure)}</span>
        </div>
        <blockquote>${escapeHtml(visual.source_caption)}</blockquote>
      </figure>`);
  }
  if (visual?.kind === "table" && visual.source_caption) {
    parts.push(`
      <figure class="morph-presentation-source">
        <div class="morph-presentation-source-head">
          <span>${escapeHtml(copy.table)}</span>
        </div>
        <blockquote>${escapeHtml(visual.source_caption)}</blockquote>
      </figure>`);
  }
  return parts.join("") || `<p class="morph-presentation-sources-empty">${escapeHtml(copy.noQuotes)}</p>`;
}

export function initPresentation({
  getProjectId,
  getMorphologyRunId,
  getGraph,
  getPaper,
  getMath,
  canStage,
  copyPrompt,
  setStatus,
} = {}) {
  const trigger = document.getElementById("morph-present");
  const promptBlock = document.getElementById("morph-presentation-prompt-block");
  const promptText = document.getElementById("morph-presentation-prompt");
  const promptHint = document.getElementById("morph-presentation-prompt-hint");
  const promptCopy = document.getElementById("morph-presentation-copy");
  const modal = document.getElementById("morph-presentation-modal");
  const panel = document.getElementById("morph-presentation-panel");
  const stage = document.getElementById("morph-presentation-stage");
  const sources = document.getElementById("morph-presentation-sources");
  const sourcesBody = document.getElementById("morph-presentation-sources-body");
  const counter = document.getElementById("morph-presentation-counter");
  const prev = document.getElementById("morph-presentation-prev");
  const next = document.getElementById("morph-presentation-next");
  const sourceToggle = document.getElementById("morph-presentation-source-toggle");
  const fullscreen = document.getElementById("morph-presentation-fullscreen");
  const languageSelect = document.getElementById("morph-presentation-language");
  const languageLabel = document.getElementById("morph-presentation-language-label");
  const sourcesTitle = document.getElementById("morph-presentation-sources-title");
  const previousLabel = document.getElementById("morph-presentation-prev-label");
  const nextLabel = document.getElementById("morph-presentation-next-label");
  const closeButton = modal?.querySelector(".morph-presentation-close");
  if (!trigger || !modal || !panel || !stage) {
    return { sync() {}, close() {} };
  }

  let deck = null;
  let latestRun = null;
  let index = 0;
  let sourcesOpen = false;
  let returnFocus = null;
  let language = "ru";
  let pollTimer = null;
  try {
    const saved = localStorage.getItem(PRESENTATION_LANGUAGE_KEY);
    if (saved === "en" || saved === "ru") language = saved;
  } catch {
    /* private mode */
  }

  const isOpen = () => !modal.classList.contains("hidden");

  function stopPolling() {
    if (pollTimer) window.clearInterval(pollTimer);
    pollTimer = null;
  }

  async function showTask(text, { copy = true } = {}) {
    const copyText = COPY.ru;
    if (promptText) promptText.textContent = text || "";
    promptBlock?.classList.remove("hidden");
    if (promptText && text) promptText.scrollIntoView({ block: "nearest" });
    let copied = false;
    if (copy && text) copied = await writeClipboard(text);
    if (promptHint) {
      promptHint.textContent = copied
        ? "Текст скопирован. Вставьте его в чат Cursor."
        : copyText.shown;
    }
    setStatus?.(copied ? copyText.copied : copyText.shown, copied ? "ok" : "warn");
    return copied;
  }

  function updateTrigger() {
    const copy = COPY.ru;
    const available = Boolean(getGraph?.());
    trigger.classList.toggle("hidden", !available);
    if (!available) {
      trigger.disabled = true;
      return;
    }
    trigger.disabled = false;
    if (latestRun?.status === "ready") trigger.textContent = copy.open;
    else if (latestRun?.status === "staged") trigger.textContent = copy.copyPrompt;
    else if (latestRun?.status === "invalid") trigger.textContent = copy.assemble;
    else trigger.textContent = copy.assemble;
  }

  function updateInterface() {
    const copy = COPY[language];
    panel.setAttribute("aria-label", copy.presentationTitle);
    sources?.setAttribute("aria-label", copy.sources);
    if (sourcesTitle) sourcesTitle.textContent = copy.sources;
    if (languageLabel) languageLabel.textContent = copy.language;
    if (fullscreen) fullscreen.textContent = copy.fullscreen;
    if (previousLabel) previousLabel.textContent = copy.previous;
    if (nextLabel) nextLabel.textContent = copy.next;
    closeButton?.setAttribute("aria-label", copy.close);
    if (sourceToggle) {
      sourceToggle.textContent = sourcesOpen ? copy.hideSources : copy.showSources;
    }
    if (languageSelect) languageSelect.value = language;
  }

  function render() {
    const slide = deck?.slides?.[index];
    if (!slide) return;
    const total = deck.slides.length;
    updateInterface();
    stage.innerHTML =
      slide.kind === "cover"
        ? renderCover(slide, getPaper?.() || {}, language)
        : renderContentSlide(slide, index + 1, total, language, getMath?.() || null);
    if (sourcesBody) sourcesBody.innerHTML = renderSources(slide, language);
    if (counter) counter.textContent = `${index + 1} / ${total}`;
    if (prev) prev.disabled = index === 0;
    if (next) next.disabled = index === total - 1;
    if (sourceToggle) {
      sourceToggle.disabled = slide.kind === "cover";
      const copy = COPY[language];
      sourceToggle.textContent = sourcesOpen ? copy.hideSources : copy.showSources;
    }
    if (slide.kind === "cover" && sourcesOpen) setSourcesOpen(false);
  }

  function setSourcesOpen(open) {
    sourcesOpen = Boolean(open);
    sources?.classList.toggle("hidden", !sourcesOpen);
    panel.classList.toggle("has-sources", sourcesOpen);
    sourceToggle?.setAttribute("aria-expanded", sourcesOpen ? "true" : "false");
    if (sourceToggle) {
      const copy = COPY[language];
      sourceToggle.textContent = sourcesOpen ? copy.hideSources : copy.showSources;
    }
  }

  function goTo(nextIndex) {
    if (!deck?.slides?.length) return;
    index = Math.max(0, Math.min(deck.slides.length - 1, nextIndex));
    render();
  }

  function openDeck(presentation) {
    deck = presentation;
    language = presentation.default_language === "en" ? language || "en" : language;
    if (languageSelect) {
      languageSelect.querySelectorAll("option").forEach((option) => {
        option.disabled = false;
      });
    }
    index = 0;
    setSourcesOpen(false);
    returnFocus = document.activeElement;
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    render();
    requestAnimationFrame(() => panel.focus());
  }

  function close() {
    if (!isOpen()) return;
    if (document.fullscreenElement === panel) void document.exitFullscreen?.();
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    setSourcesOpen(false);
    returnFocus?.focus?.();
  }

  async function refreshLatest() {
    const projectId = getProjectId?.();
    const morphologyRunId = getMorphologyRunId?.();
    if (!projectId || !morphologyRunId) {
      latestRun = null;
      updateTrigger();
      return null;
    }
    let listed = { runs: [] };
    try {
      listed = await KoiApi.listMorphologyPresentations(projectId, morphologyRunId);
    } catch (err) {
      if (!/not found/i.test(String(err.message || ""))) throw err;
    }
    const runs = listed?.runs || [];
    const row =
      runs.find((item) => item.status === "ready") ||
      runs.find((item) => item.status === "invalid") ||
      runs[0] ||
      null;
    if (!row) {
      latestRun = null;
      updateTrigger();
      return null;
    }
    latestRun = await KoiApi.getMorphologyPresentation(
      projectId,
      morphologyRunId,
      row.run_id
    );
    updateTrigger();
    return latestRun;
  }

  function startPolling() {
    stopPolling();
    pollTimer = window.setInterval(() => {
      void refreshLatest().then((run) => {
        if (run?.status === "ready") {
          stopPolling();
          setStatus?.(COPY.ru.copied.replace("Текст задания скопирован. ", ""), "ok");
        } else if (run?.status === "invalid") {
          stopPolling();
          setStatus?.(COPY.ru.invalid, "error");
        }
      });
    }, POLL_MS);
  }

  async function handleTrigger() {
    const copy = COPY.ru;
    if (!getGraph?.()) return;
    if (!canStage?.()) {
      setStatus?.(copy.missing, "error");
      return;
    }
    try {
      await refreshLatest();
    } catch (err) {
      setStatus?.(err.message, "error");
      return;
    }
    if (latestRun?.status === "ready" && latestRun.presentation) {
      promptBlock?.classList.add("hidden");
      openDeck(latestRun.presentation);
      return;
    }
    const existingPrompt = latestRun?.prompt || latestRun?.cursor_message || "";
    if (latestRun?.status === "staged" && existingPrompt) {
      await showTask(existingPrompt);
      startPolling();
      return;
    }
    try {
      const staged = await KoiApi.stageMorphologyPresentation(
        getProjectId?.(),
        getMorphologyRunId?.()
      );
      latestRun = staged;
      updateTrigger();
      await showTask(staged.cursor_message || staged.prompt || "");
      startPolling();
    } catch (err) {
      setStatus?.(err.message, "error");
    }
  }

  trigger.addEventListener("click", () => void handleTrigger());
  promptCopy?.addEventListener("click", () => {
    void showTask(promptText?.textContent || latestRun?.prompt || "", { copy: true });
  });
  prev?.addEventListener("click", () => goTo(index - 1));
  next?.addEventListener("click", () => goTo(index + 1));
  languageSelect?.addEventListener("change", () => {
    language = languageSelect.value === "en" ? "en" : "ru";
    try {
      localStorage.setItem(PRESENTATION_LANGUAGE_KEY, language);
    } catch {
      /* private mode */
    }
    render();
  });
  sourceToggle?.addEventListener("click", () => setSourcesOpen(!sourcesOpen));
  fullscreen?.addEventListener("click", () => {
    if (document.fullscreenElement === panel) void document.exitFullscreen?.();
    else void panel.requestFullscreen?.();
  });
  modal.querySelectorAll("[data-close='morph-presentation-modal']").forEach((element) => {
    element.addEventListener("click", close);
  });

  document.addEventListener(
    "keydown",
    (event) => {
      if (!isOpen()) return;
      if (event.key === "Tab") {
        const focusable = [...panel.querySelectorAll("button:not(:disabled), a[href], [tabindex]")]
          .filter((element) => element.getAttribute("tabindex") !== "-1" && element.offsetParent);
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!first || !last) {
          event.preventDefault();
          panel.focus();
        } else if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      } else if (event.key === "Escape") {
        event.preventDefault();
        close();
      } else if (event.key === "ArrowRight" || event.key === "PageDown") {
        event.preventDefault();
        goTo(index + 1);
      } else if (event.key === "ArrowLeft" || event.key === "PageUp") {
        event.preventDefault();
        goTo(index - 1);
      } else if (event.key === "Home") {
        event.preventDefault();
        goTo(0);
      } else if (event.key === "End") {
        event.preventDefault();
        goTo((deck?.slides || []).length - 1);
      } else if (
        event.key === " " &&
        !event.target.closest?.("button, a, input, textarea, select")
      ) {
        event.preventDefault();
        goTo(index + 1);
      }
    },
    true
  );

  return {
    sync() {
      updateTrigger();
      if (getGraph?.() && canStage?.()) {
        void refreshLatest().then((run) => {
          const text = run?.prompt || run?.cursor_message || "";
          if (run?.status === "staged" && text && promptText && !promptText.textContent) {
            void showTask(text, { copy: false });
          }
        });
      } else {
        latestRun = null;
        promptBlock?.classList.add("hidden");
        updateTrigger();
        stopPolling();
        close();
      }
    },
    close,
  };
}
