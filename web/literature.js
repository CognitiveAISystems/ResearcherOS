import { KoiApi } from "./api.js?v=20260811a";
import {
  showKoiLoader,
  hideKoiLoader,
  attachRotatingHint,
  detachRotatingHint,
} from "./koi-loader.js";
import { renderMarkdown } from "./markdown.js";

const THEME_STORAGE_KEY = "koi-theme";
const RW_SETTINGS_KEY = "koi-rw-settings";

const BRAND_TAGLINES = [
  "Discovery through collaboration across minds",
  "Every experiment should make the next one smarter",
  "Creating a memory that grows with every question",
  "Organizing ideas for discovery",
  "Making research cumulative, not repetitive.",
];

const TAGLINE_ROTATE_MS = 60_000;
const TAGLINE_FADE_MS = 450;
const CONTEXT_APPEND_MARKER = "\n\nProject context:\n";
const MORPH_HANDOFF_KEY = "koi-morph-paper";
const MORPH_ICON_SVG =
  '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M12 2a2.5 2.5 0 0 1 1 4.79V9h4a3 3 0 0 1 3 3v1.21a2.5 2.5 0 1 1-2 0V12a1 1 0 0 0-1-1h-4v2.21a2.5 2.5 0 1 1-2 0V11H7a1 1 0 0 0-1 1v1.21a2.5 2.5 0 1 1-2 0V12a3 3 0 0 1 3-3h4V6.79A2.5 2.5 0 0 1 12 2z"/></svg>';

let literatureResults = [];
let selectedPaperUrls = new Set();
let latestPaperAnswerRun = null;
let selectedClusterKeys = new Set();
let activeClusterKey = null;
let activeReadingView = "resume"; // "resume" | cluster key
const READING_VIEW_RESUME = "resume";
let activeClusterModal = null;
let activeSettingsModal = null;
let activeContextModal = null;
let projectContextItems = [];
let selectedProjectContextKeys = new Set();
let projectLiteratureKeywords = [];
let libraryExists = false;
let appSettings = {
  agent_chat_mode: "cursor_inbox",
  literature_inbox_configured: false,
  literature_inbox_watcher_running: false,
  literature_inbox_bootstrap_prompt: "",
  inbox_configured: false,
  inbox_pending_counts: { agent_chat: 0, related_work: 0 },
};
let literatureInboxStatusPollTimer = null;
let literatureInboxBootstrapCopied = false;
let literatureClusterPrompt = "";
let literatureClusterPendingHash = "";
let literatureClusterPollTimer = null;
let activeClusterPromptModal = null;
let collectionPapersCache = null;
let collectionSelectionCache = null;
let workspaceGenerating = false;

const LITERATURE_INBOX_CONFIGURED_KEY = "koi_literature_inbox_configured";
const LITERATURE_CLUSTER_POLL_MS = 4000;

function isLiteratureInboxConfigured() {
  return Boolean(appSettings.literature_inbox_configured);
}

function isLiteratureInboxWatcherRunning() {
  return Boolean(appSettings.literature_inbox_watcher_running);
}

function isLiteratureInboxOperational() {
  return isLiteratureInboxConfigured() && isLiteratureInboxWatcherRunning();
}

function literatureInboxStatus() {
  if (!isInboxAgentMode()) return "not_inbox_mode";
  if (!isLiteratureInboxConfigured()) return "unconfigured";
  if (!isLiteratureInboxWatcherRunning()) return "no_watcher";
  return "ready";
}

function syncLiteratureInboxConfiguredCache() {
  try {
    if (isLiteratureInboxConfigured()) {
      localStorage.setItem(LITERATURE_INBOX_CONFIGURED_KEY, "1");
    } else {
      localStorage.removeItem(LITERATURE_INBOX_CONFIGURED_KEY);
      localStorage.removeItem("koi_inbox_configured");
      localStorage.removeItem("koi_inbox_hint_dismissed");
    }
  } catch {
    /* private mode */
  }
}

function ensureLiteratureInboxBootstrapCached() {
  const bootstrap =
    appSettings.literature_inbox_bootstrap_prompt ||
    appSettings.inbox_bootstrap_prompt ||
    "";
  if (bootstrap && !lastRelatedWorkInboxMessage) {
    lastRelatedWorkInboxMessage = bootstrap;
  }
}

function updateLiteratureInboxSetupNotice() {
  const box = document.getElementById("rw-inbox-message");
  if (!box) return;

  const split = document.getElementById("rw-workspace")?.classList.contains("is-split");
  const insights = document.getElementById("rw-insights-column");
  const insightsVisible = insights && !insights.classList.contains("hidden");

  // Keep the reading canvas quiet: never auto-open the setup panel.
  // Users open it via the inbox indicator / explicit setup action.
  if (!isInboxAgentMode() || isLiteratureInboxConfigured() || !split || !insightsVisible) {
    box.classList.add("hidden");
    stopLiteratureInboxStatusPoll();
    return;
  }

  const status = literatureInboxStatus();
  const markBtn = document.getElementById("rw-inbox-mark-configured");
  if (markBtn) {
    if (literatureInboxBootstrapCopied) {
      markBtn.removeAttribute("disabled");
    } else {
      markBtn.setAttribute("disabled", "disabled");
      markBtn.title = "Сначала скопируйте сообщение и вставьте в Cursor";
    }
  }
  const label = box.querySelector(".rw-inbox-message-label");
  const hint = box.querySelector(".rw-inbox-message-hint");
  const resetBtn = document.getElementById("rw-inbox-reset-configured");

  if (status === "no_watcher") {
    if (label) label.textContent = "Literature Inbox: watcher не запущен";
    if (hint) {
      hint.innerHTML =
        "Запустите сервер: <code>./scripts/koi-serve.sh start</code> — он поднимет watcher и будет писать RELATED_WORK_WAKE в лог. " +
        "Скопируйте bootstrap в чат Literature Inbox — агент сам поднимет мониторинг с автопробуждением.";
    }
    resetBtn?.classList.remove("hidden");
  } else {
    if (label) label.textContent = "Literature Inbox не настроен";
    if (hint) {
      hint.innerHTML =
        "Скопируйте bootstrap → чат <strong>ResearchOS Literature Inbox</strong> → дождитесь настройки мониторинга → «Inbox готов».";
    }
    resetBtn?.classList.add("hidden");
  }

  ensureLiteratureInboxBootstrapCached();
  // Do not remove `hidden` here — open only via showLiteratureInboxSetup().
  startLiteratureInboxStatusPoll();
}

function startLiteratureInboxStatusPoll() {
  if (literatureInboxStatusPollTimer) return;
  literatureInboxStatusPollTimer = setInterval(() => {
    if (isLiteratureInboxConfigured()) {
      stopLiteratureInboxStatusPoll();
      return;
    }
    const split = document.getElementById("rw-workspace")?.classList.contains("is-split");
    if (!split || !isInboxAgentMode()) return;
    void refreshAppSettings();
  }, 10000);
}

function stopLiteratureInboxStatusPoll() {
  if (!literatureInboxStatusPollTimer) return;
  clearInterval(literatureInboxStatusPollTimer);
  literatureInboxStatusPollTimer = null;
}

function isInboxConfigured() {
  return isLiteratureInboxConfigured();
}

async function markInboxConfigured() {
  try {
    const data = await KoiApi.setInboxConfigured(true, "literature");
    appSettings = { ...appSettings, ...data };
  } catch {
    setRelatedWorksStatus("Не удалось сохранить настройку Inbox.", true);
    return;
  }
  await refreshAppSettings();
  syncLiteratureInboxConfiguredCache();
  updateInboxIndicator();
  updateLiteratureInboxSetupNotice();
  return isLiteratureInboxOperational();
}

async function resetLiteratureInboxConfigured() {
  try {
    const data = await KoiApi.setInboxConfigured(false, "literature");
    appSettings = { ...appSettings, ...data, literature_inbox_configured: false };
  } catch {
    setRelatedWorksStatus("Не удалось сбросить настройку Inbox.", true);
    return false;
  }
  syncLiteratureInboxConfiguredCache();
  literatureInboxBootstrapCopied = false;
  updateInboxIndicator();
  updateLiteratureInboxSetupNotice();
  updateInboxRestartButton();
  updateRelatedWorkWaitingActions();
  const status = document.getElementById("rw-inbox-message-status");
  if (status) status.textContent = "";
  return true;
}

async function restartLiteratureInboxSetup() {
  const savedItemId = activeRelatedWorkItemId;
  const ok = await resetLiteratureInboxConfigured();
  if (!ok) return;

  await refreshAppSettings();

  let message =
    appSettings.literature_inbox_bootstrap_prompt ||
    appSettings.inbox_bootstrap_prompt ||
    "";

  if (savedItemId) {
    try {
      const item = await KoiApi.getRelatedWorkItem(savedItemId);
      const taskMsg = composeRelatedWorkInboxMessage(item);
      if (taskMsg) message = taskMsg;
      else if (item.cursor_message) message = item.cursor_message;
    } catch {
      /* keep bootstrap */
    }
  }

  ensureLiteratureInboxBootstrapCached();
  if (message) {
    lastRelatedWorkInboxMessage = message;
    lastRelatedWorkCursorMessage = message;
  }

  showLiteratureInboxSetup();

  if (relatedWorkSubmitted && activeRelatedWorkPhase === "pending") {
    setRelatedWorkWaiting(true, "pending");
  }

  if (message) {
    showRelatedInboxModal(message);
  }

  setRelatedWorksStatus(
    "Inbox сброшен — скопируйте сообщение заново и нажмите «Inbox готов».",
    false
  );
}
let relatedWorkPollTimer = null;
let activeRelatedWorkItemId = null;
let activeRelatedWorkPhase = null;
let activeRelatedInboxModal = null;
let lastRelatedWorkCursorMessage = "";
let lastRelatedWorkInboxMessage = "";
let relatedWorkSubmitted = false;

const RELATED_WORK_POLL_MS = 15000;
const RW_PENDING_STORAGE_PREFIX = "koi-rw-pending-item";
let relatedWorkWaitStartedAt = null;
let relatedWorkWaitTimer = null;

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s ?? "";
  return d.innerHTML;
}

function defaultSettings() {
  return {
    searchMode: "internet",
    autoTranslate: true,
    limit: 10,
    overwriteAnswers: false,
    zoteroUserId: "",
    zoteroApiKey: "",
    zoteroUsername: "",
    zoteroCollectionKey: "",
  };
}

function loadSettings() {
  try {
    const raw = localStorage.getItem(RW_SETTINGS_KEY);
    if (!raw) return defaultSettings();
    return { ...defaultSettings(), ...JSON.parse(raw) };
  } catch {
    return defaultSettings();
  }
}

function saveSettingsToStorage(settings) {
  localStorage.setItem(RW_SETTINGS_KEY, JSON.stringify(settings));
}

function readSettingsFromDom() {
  const mode =
    document.querySelector('input[name="rw-search-mode"]:checked')?.value || "internet";
  return {
    searchMode: mode,
    autoTranslate: Boolean(document.getElementById("literature-auto-translate")?.checked),
    limit: selectedLiteratureLimit(),
    overwriteAnswers: Boolean(document.getElementById("literature-overwrite-answers")?.checked),
    zoteroUserId: document.getElementById("rw-zotero-user-id")?.value?.trim() || "",
    zoteroApiKey: document.getElementById("rw-zotero-api-key")?.value?.trim() || "",
    zoteroUsername: loadSettings().zoteroUsername || "",
    zoteroCollectionKey: document.getElementById("rw-zotero-collection")?.value || "",
  };
}

function applySettingsToDom(settings = loadSettings()) {
  const modeInput = document.querySelector(
    `input[name="rw-search-mode"][value="${settings.searchMode}"]`
  );
  if (modeInput) modeInput.checked = true;
  else {
    const fallback = document.querySelector('input[name="rw-search-mode"][value="internet"]');
    if (fallback) fallback.checked = true;
  }
  const autoTranslate = document.getElementById("literature-auto-translate");
  if (autoTranslate) autoTranslate.checked = settings.autoTranslate;
  const overwrite = document.getElementById("literature-overwrite-answers");
  if (overwrite) overwrite.checked = settings.overwriteAnswers;
  const limit = document.getElementById("literature-limit");
  if (limit) limit.value = String(settings.limit || 10);
  const zoteroUser = document.getElementById("rw-zotero-user-id");
  if (zoteroUser) zoteroUser.value = settings.zoteroUserId || "";
  const zoteroKey = document.getElementById("rw-zotero-api-key");
  if (zoteroKey) zoteroKey.value = settings.zoteroApiKey || "";
  restoreZoteroConnectionUi(settings);
  updateSettingsSourceUi();
}

function currentSearchModeFromDom() {
  return (
    document.querySelector('input[name="rw-search-mode"]:checked')?.value ||
    loadSettings().searchMode ||
    "internet"
  );
}

const SEARCH_MODE_HINTS = {
  local: "Только CSV-библиотека",
  internet: "Прямой поиск на arXiv",
  both: "Сначала CSV, потом дополнение с arXiv",
};

function updateSettingsSourceUi() {
  const mode = currentSearchModeFromDom();
  const hint = document.getElementById("rw-settings-mode-hint");
  if (hint) hint.textContent = SEARCH_MODE_HINTS[mode] || "";

  const library = document.getElementById("rw-settings-library");
  const meta = document.getElementById("rw-settings-library-meta");
  const needsLibrary = mode === "local" || mode === "both";
  if (library) library.open = needsLibrary && !libraryExists;
  if (meta) {
    if (libraryExists) meta.textContent = "готова";
    else if (needsLibrary) meta.textContent = "нужна для режима";
    else meta.textContent = "опционально";
  }
  updateLibraryStatusHint();
}

function getSearchMode() {
  return loadSettings().searchMode || "internet";
}

function initTaglineRotation() {
  const el = document.getElementById("brand-tagline");
  if (!el) return;
  let index = Math.floor(Math.random() * BRAND_TAGLINES.length);
  el.textContent = BRAND_TAGLINES[index];
  setInterval(() => {
    el.classList.add("is-fading");
    setTimeout(() => {
      index = (index + 1) % BRAND_TAGLINES.length;
      el.textContent = BRAND_TAGLINES[index];
      el.classList.remove("is-fading");
    }, TAGLINE_FADE_MS);
  }, TAGLINE_ROTATE_MS);
}

function getTheme() {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

function updateThemeButton(theme) {
  const btn = document.getElementById("btn-theme");
  if (!btn) return;
  const isLight = theme === "light";
  btn.title = isLight ? "Тёмная тема" : "Светлая тема";
  btn.setAttribute("aria-label", btn.title);
}

function setTheme(theme) {
  const next = theme === "light" ? "light" : "dark";
  if (next === "light") document.documentElement.setAttribute("data-theme", "light");
  else document.documentElement.removeAttribute("data-theme");
  localStorage.setItem(THEME_STORAGE_KEY, next);
  updateThemeButton(next);
  window.dispatchEvent(new CustomEvent("koi-theme-change", { detail: { theme: next } }));
}

function initTheme() {
  const stored = localStorage.getItem(THEME_STORAGE_KEY);
  const theme = stored === "light" ? "light" : "dark";
  if (theme === "light") document.documentElement.setAttribute("data-theme", "light");
  updateThemeButton(theme);
  document.getElementById("btn-theme")?.addEventListener("click", () => {
    setTheme(getTheme() === "light" ? "dark" : "light");
  });
}

function setLiteratureStatus(msg, isError = false) {
  const el = document.getElementById("literature-search-status");
  if (el) {
    el.textContent = msg || "";
    el.className = "rw-library-status" + (isError ? " error" : msg ? " ok" : "");
    el.setAttribute("role", isError ? "alert" : "status");
  }
  const clustersStatus = document.getElementById("rw-clusters-status");
  if (clustersStatus) {
    clustersStatus.textContent = msg || "";
    clustersStatus.className = "rw-clusters-status" + (isError ? " error" : msg ? " ok" : "");
  }
}

function setProjectContextStatus(msg, isError = false) {
  const el = document.getElementById("literature-context-status");
  if (!el) return;
  el.textContent = msg;
  el.className = "literature-context-status" + (isError ? " error" : msg ? " ok" : "");
}

function setRelatedWorksStatus(msg, isError = false) {
  const el = document.getElementById("related-works-status");
  if (!el) return;
  el.textContent = msg;
  el.className = "rw-pane-meta rw-related-status" + (isError ? " error" : msg ? " ok" : "");
  el.classList.toggle("hidden", !msg);
}

function isWorkspaceSplit() {
  return Boolean(document.getElementById("rw-workspace")?.classList.contains("is-split"));
}

function showLoader(step = "Подготовка…") {
  if (isWorkspaceSplit() || workspaceGenerating) {
    setGeneratingMode(true, step);
    return;
  }
  hideKoiLoader("rw-loader");
  showKoiLoader("rw-search-loader", { step, pool: "literature" });
}

function hideLoader() {
  hideKoiLoader("rw-search-loader");
  if (!workspaceGenerating) {
    hideKoiLoader("rw-loader");
    document.getElementById("rw-generation-stage")?.classList.add("hidden");
  }
}

function showRelatedLoader(step = "Генерация Related Work…") {
  showKoiLoader("rw-related-loader", { step, pool: "related" });
}

function hideRelatedLoader() {
  hideKoiLoader("rw-related-loader");
}

function setGeneratingMode(enabled, step = "Исследуем литературу…") {
  workspaceGenerating = Boolean(enabled);
  const workspace = document.getElementById("rw-workspace");
  const stage = document.getElementById("rw-generation-stage");
  workspace?.classList.toggle("is-generating", workspaceGenerating);
  if (workspaceGenerating) {
    stage?.classList.remove("hidden");
    showKoiLoader("rw-loader", { step, pool: "literature" });
    syncPromptDock();
  } else {
    hideKoiLoader("rw-loader");
    stage?.classList.add("hidden");
    hidePromptDock();
  }
}

function syncPromptDock() {
  const dock = document.getElementById("rw-prompt-dock");
  const textEl = document.getElementById("rw-prompt-dock-text");
  const prompt = String(literatureClusterPrompt || "").trim();
  if (!dock) return;
  if (!prompt || !workspaceGenerating) {
    dock.classList.add("hidden");
    return;
  }
  if (textEl) textEl.textContent = prompt;
  dock.classList.remove("hidden");
}

function showPromptDock(promptText = literatureClusterPrompt) {
  literatureClusterPrompt = String(promptText || "").trim();
  syncPromptDock();
}

function hidePromptDock() {
  document.getElementById("rw-prompt-dock")?.classList.add("hidden");
}

function cacheCollectionSidebar() {
  collectionPapersCache = literatureResults.map((p) => ({ ...p }));
  collectionSelectionCache = new Set(selectedPaperUrls);
}

function restoreCollectionSidebar() {
  if (collectionPapersCache) {
    literatureResults = collectionPapersCache.map((p) => ({ ...p }));
    selectedPaperUrls = new Set(collectionSelectionCache || []);
    collectionPapersCache = null;
    collectionSelectionCache = null;
  }
  const nav = document.getElementById("rw-cluster-nav");
  nav?.classList.add("hidden");
  nav && (nav.innerHTML = "");
  document.getElementById("literature-results")?.classList.remove("hidden");
  renderLiteratureResults(literatureResults);
  updateLibrarySplitChrome(false);
}

function updateLibrarySplitChrome(enabled) {
  const backBtn = document.getElementById("rw-back-to-collection");
  const title = document.getElementById("rw-library-title");
  const empty = document.getElementById("rw-library-empty");
  const toolbar = document.getElementById("rw-library-toolbar");
  const addMenu = document.getElementById("rw-library-add-menu");
  const switchSource = document.getElementById("rw-library-switch-source");
  const results = document.getElementById("literature-results");
  const nav = document.getElementById("rw-cluster-nav");
  const countEl = document.getElementById("rw-library-count");
  backBtn?.classList.toggle("hidden", !enabled);
  if (title) title.textContent = enabled ? "Кластеры" : "Коллекция";
  if (enabled) {
    empty?.classList.add("hidden");
    toolbar?.classList.add("hidden");
    switchSource?.classList.add("hidden");
    addMenu?.classList.add("hidden");
    if (addMenu) addMenu.hidden = true;
    results?.classList.add("hidden");
    nav?.classList.remove("hidden");
    const n = latestPaperAnswerRun?.clusters?.length || 0;
    if (countEl) {
      countEl.hidden = !n;
      countEl.textContent = n ? String(n) : "";
      countEl.title = n ? `${n} кластеров` : "";
    }
  } else {
    results?.classList.remove("hidden");
    nav?.classList.add("hidden");
    updateLibraryPanelChrome();
  }
}

function renderRunPapersSidebar(_papers = []) {
  // Split mode uses the clusters nav in the left column; articles stay in cluster detail.
  updateLibrarySplitChrome(true);
}

function setRelatedPaneCollapsed(collapsed) {
  const pane = document.getElementById("rw-related-pane");
  const toggle = document.getElementById("rw-related-toggle");
  const body = document.getElementById("rw-related-body");
  const hint = document.getElementById("rw-related-toggle-hint");
  if (!pane) return;
  pane.classList.toggle("is-collapsed", Boolean(collapsed));
  if (body) body.hidden = Boolean(collapsed);
  toggle?.setAttribute("aria-expanded", collapsed ? "false" : "true");
  if (hint) hint.textContent = collapsed ? "Развернуть" : "Свернуть";
}

function toggleRelatedPaneCollapsed() {
  const pane = document.getElementById("rw-related-pane");
  if (!pane || pane.classList.contains("hidden")) return;
  setRelatedPaneCollapsed(!pane.classList.contains("is-collapsed"));
}

function scrollReadingToContent() {
  const page = document.getElementById("rw-reading-page");
  const anchor = document.getElementById("rw-clusters-top") || document.getElementById("rw-reading-content");
  if (!page || !anchor) return;
  const top = Math.max(0, anchor.offsetTop - 8);
  page.scrollTo({ top, behavior: "smooth" });
}

function syncReadingNavActive(view = activeReadingView) {
  const nav = document.getElementById("rw-cluster-nav");
  if (!nav) return;
  nav.querySelectorAll(".rw-cluster-nav-row").forEach((row) => {
    const btn = row.querySelector(".rw-cluster-nav-item");
    const key = btn?.getAttribute("data-reading-view") || "";
    const active = key === view;
    row.classList.toggle("is-active", active);
    btn?.classList.toggle("is-active", active);
    btn?.setAttribute("aria-current", active ? "true" : "false");
  });
}

function showReadingView(view, { scrollPage = true, scrollNav = false } = {}) {
  const run = latestPaperAnswerRun;
  const reportEl = document.getElementById("rw-report-markdown");
  const detail = document.getElementById("rw-cluster-detail");
  const hasReport = Boolean(String(run?.report_markdown || "").trim());
  const clusters = run?.clusters || [];

  let next = view;
  if (next === READING_VIEW_RESUME && !hasReport && clusters.length) {
    next = clusters[0].key;
  } else if (next !== READING_VIEW_RESUME && !clusters.some((c) => c.key === next)) {
    next = hasReport ? READING_VIEW_RESUME : clusters[0]?.key || READING_VIEW_RESUME;
  }
  activeReadingView = next;
  if (next !== READING_VIEW_RESUME) activeClusterKey = next;

  syncReadingNavActive(next);

  if (next === READING_VIEW_RESUME) {
    if (detail) {
      detail.classList.add("hidden");
      detail.innerHTML = "";
    }
    renderReportMarkdown(run);
    reportEl?.classList.remove("hidden");
  } else {
    reportEl?.classList.add("hidden");
    if (detail) detail.classList.remove("hidden");
    const cluster = clusters.find((item) => item.key === next);
    if (cluster) {
      renderClusterDetail(cluster, papersForCluster(run, cluster), run);
    } else if (detail) {
      detail.innerHTML = `<p class="literature-empty">Выберите раздел слева.</p>`;
    }
  }

  if (scrollNav) {
    document
      .getElementById("rw-cluster-nav")
      ?.querySelector(".rw-cluster-nav-row.is-active")
      ?.scrollIntoView({ block: "nearest" });
  }
  if (scrollPage) {
    requestAnimationFrame(() => scrollReadingToContent());
  }
}

function selectCluster(key, opts = {}) {
  showReadingView(key, opts);
}

function setWorkspaceSplit(enabled) {
  const workspace = document.getElementById("rw-workspace");
  const page = document.getElementById("rw-page");
  const insights = document.getElementById("rw-insights-column");
  const clustersBlock = document.getElementById("rw-clusters-block");
  const history = document.getElementById("rw-history-column");
  const search = document.getElementById("rw-search-column");
  const historyBack = document.getElementById("rw-history-back");
  const wasSplit = isWorkspaceSplit();

  if (enabled) {
    workspace?.classList.remove("is-history");
    page?.classList.remove("is-history");
    historyBack?.classList.add("hidden");
  }

  if (enabled && !wasSplit) {
    cacheCollectionSidebar();
  }

  workspace?.classList.toggle("is-split", enabled);
  page?.classList.toggle("is-split", enabled);
  insights?.classList.toggle("hidden", !enabled);
  clustersBlock?.classList.toggle("hidden", !enabled);
  history?.classList.toggle("hidden", !enabled && !workspace?.classList.contains("is-history"));
  search?.classList.toggle("rw-column-dormant", enabled);

  if (enabled) {
    hideKoiLoader("rw-search-loader");
    updateLibrarySplitChrome(true);
    void refreshLiteratureHistory();
  } else {
    setGeneratingMode(false);
    restoreCollectionSidebar();
  }
}

function isHistoryView() {
  return Boolean(document.getElementById("rw-workspace")?.classList.contains("is-history"));
}

function setHistoryView(enabled) {
  const workspace = document.getElementById("rw-workspace");
  const page = document.getElementById("rw-page");
  const history = document.getElementById("rw-history-column");
  const historyBack = document.getElementById("rw-history-back");
  const insights = document.getElementById("rw-insights-column");

  if (enabled) {
    if (isWorkspaceSplit()) {
      setWorkspaceSplit(false);
    }
    workspace?.classList.add("is-history");
    page?.classList.add("is-history");
    history?.classList.remove("hidden");
    historyBack?.classList.remove("hidden");
    insights?.classList.add("hidden");
    void refreshLiteratureHistory();
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else {
    workspace?.classList.remove("is-history");
    page?.classList.remove("is-history");
    historyBack?.classList.add("hidden");
    if (!isWorkspaceSplit()) {
      history?.classList.add("hidden");
    }
  }
}

function updateClustersQuestion(run = latestPaperAnswerRun) {
  const el = document.getElementById("rw-clusters-question");
  if (!el) return;
  const question = String(run?.question || "").trim();
  el.textContent = question || "Кластеры по исследовательскому вопросу";
}

function inferYearFromArxivUrl(url) {
  const match = String(url || "").match(/(?:arxiv\.org\/(?:abs|pdf|html)\/)?(\d{2})(\d{2})\.\d{4,5}/i);
  if (!match) return null;
  const yy = Number(match[1]);
  const mm = Number(match[2]);
  if (!Number.isFinite(yy) || !Number.isFinite(mm) || mm < 1 || mm > 12) return null;
  return 2000 + yy;
}

function normalizePaperRecord(paper) {
  const arxivUrl = String(paper?.arxiv_url || "").trim();
  const year =
    paper?.year != null && paper.year !== ""
      ? Number(paper.year)
      : inferYearFromArxivUrl(arxivUrl);
  return {
    ...paper,
    title: String(paper?.title || "").trim(),
    arxiv_url: arxivUrl,
    authors: String(paper?.authors || "").trim(),
    year: Number.isFinite(year) ? year : null,
    abstract_preview: paper?.abstract_preview || shortText(paper?.abstract || "", 280),
  };
}

function formatAuthorsLine(authors, max = 72) {
  const text = String(authors || "").replace(/\s+/g, " ").trim();
  if (!text) return "авторы не указаны";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1).trimEnd()}…`;
}

function paperMetaLine(paper) {
  const year = paper.year ? String(paper.year) : "—";
  return `${year} · ${formatAuthorsLine(paper.authors)}`;
}

/** Hand the full paper record to the morphology page (URL alone loses the abstract). */
function openPaperMorphology(paperUrl) {
  const paper = literatureResults.find((item) => item.arxiv_url === paperUrl);
  if (!paper) {
    setLiteratureStatus("Статья не найдена в текущем списке.", true);
    return;
  }
  const projectId = selectedProjectId();
  if (!projectId) {
    setLiteratureStatus("Сначала выберите проект.", true);
    return;
  }
  try {
    sessionStorage.setItem(
      MORPH_HANDOFF_KEY,
      JSON.stringify({
        title: paper.title,
        url: paper.arxiv_url,
        authors: paper.authors,
        year: paper.year,
        abstract: paper.abstract || paper.abstract_preview || "",
      })
    );
  } catch {
    /* private mode — the page falls back to the library lookup */
  }
  const params = new URLSearchParams({ project: projectId, paper: paper.arxiv_url });
  window.location.href = `morphology.html?${params.toString()}`;
}

function updateLibraryPanelChrome() {
  const empty = document.getElementById("rw-library-empty");
  const toolbar = document.getElementById("rw-library-toolbar");
  const countEl = document.getElementById("rw-library-count");
  const switchSource = document.getElementById("rw-library-switch-source");
  const hasPapers = literatureResults.length > 0;
  empty?.classList.toggle("hidden", hasPapers);
  toolbar?.classList.toggle("hidden", !hasPapers);
  switchSource?.classList.toggle("hidden", !hasPapers);
  updateZoteroEmptyHint();
  if (countEl) {
    if (hasPapers) {
      countEl.hidden = false;
      countEl.textContent = `${literatureResults.length}`;
      countEl.title = `${literatureResults.length} статей`;
    } else {
      countEl.hidden = true;
      countEl.textContent = "";
    }
  }
  if (!hasPapers) hideLibraryAddMenu();
}

function updateZoteroEmptyHint() {
  const hint = document.querySelector("#rw-library-zotero .rw-library-source-hint");
  if (!hint) return;
  const connected = Boolean(loadSettings().zoteroApiKey?.trim());
  hint.textContent = connected ? "загрузить библиотеку" : "подключить";
}

function hideLibraryAddMenu() {
  const menu = document.getElementById("rw-library-add-menu");
  const addBtn = document.getElementById("rw-library-add");
  if (menu) {
    menu.classList.add("hidden");
    menu.hidden = true;
  }
  addBtn?.setAttribute("aria-expanded", "false");
}

function toggleLibraryAddMenu() {
  const menu = document.getElementById("rw-library-add-menu");
  const addBtn = document.getElementById("rw-library-add");
  if (!menu) return;
  const open = menu.classList.contains("hidden");
  menu.classList.toggle("hidden", !open);
  menu.hidden = !open;
  addBtn?.setAttribute("aria-expanded", open ? "true" : "false");
}

function setLibraryPapers(papers, { selectAll = true } = {}) {
  literatureResults = (papers || []).map(normalizePaperRecord).filter((p) => p.title && p.arxiv_url);
  try { sessionStorage.setItem("koi-mortal-library", JSON.stringify(literatureResults)); } catch { /* private mode */ }
  if (selectAll) {
    selectedPaperUrls = new Set(literatureResults.map((p) => p.arxiv_url));
  } else {
    selectedPaperUrls = new Set(
      [...selectedPaperUrls].filter((url) => literatureResults.some((p) => p.arxiv_url === url))
    );
  }
  renderLiteratureResults(literatureResults);
}

function shortText(text, max = 180) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  if (!normalized) return "";
  if (normalized.length <= max) return normalized;
  return `${normalized.slice(0, max - 1).trimEnd()}…`;
}

function contextTypeLabel(type) {
  return (
    { problem: "Problem", cause: "Cause", hypothesis: "Hypothesis", task: "Kanban task" }[
      type
    ] || "Context"
  );
}

function buildProjectContextItems(project) {
  if (!project) return [];
  const nodes = Array.isArray(project.nodes) ? project.nodes : [];
  const boards = Array.isArray(project.boards) ? project.boards : [];
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const items = [];

  for (const node of nodes) {
    if (node.node_type === "problem") {
      items.push({
        key: `node:${node.id}`,
        type: "problem",
        title: node.title,
        subtitle: shortText(node.description, 180) || "Root problem from the project map.",
        snippet: `Problem: ${node.title}${node.description ? `. ${shortText(node.description, 260)}` : ""}`,
      });
    }
    if (node.node_type === "cause") {
      items.push({
        key: `node:${node.id}`,
        type: "cause",
        title: node.title,
        subtitle: shortText(node.description, 180) || "Cause node from the project tree.",
        snippet: `Cause: ${node.title}${node.description ? `. ${shortText(node.description, 260)}` : ""}`,
      });
    }
    if (node.node_type === "cause_evidence" || node.node_type === "remediation") {
      const parent = nodeById.get(node.parent_id);
      items.push({
        key: `node:${node.id}`,
        type: "hypothesis",
        title: node.title,
        subtitle: shortText(node.description, 180) || "Hypothesis branch from the project tree.",
        meta: parent?.title ? `Under cause: ${parent.title}` : "",
        snippet:
          `Hypothesis: ${node.title}` +
          `${parent?.title ? ` (under cause: ${parent.title})` : ""}` +
          `${node.description ? `. ${shortText(node.description, 260)}` : ""}`,
      });
    }
  }

  for (const board of boards) {
    const owner = nodeById.get(board.owner_node_id);
    const ownerTitle = owner?.title || "method";
    for (const card of board.cards || []) {
      items.push({
        key: `card:${board.id}:${card.id}`,
        type: "task",
        title: card.title,
        subtitle: shortText(card.description, 180) || "Kanban task without a separate description.",
        meta: `Method: ${ownerTitle}`,
        snippet:
          `Kanban task: ${card.title}` +
          ` (method: ${ownerTitle})` +
          `${card.description ? `. ${shortText(card.description, 260)}` : ""}`,
      });
    }
  }

  const order = { problem: 0, cause: 1, hypothesis: 2, task: 3 };
  return items.sort((a, b) => {
    const oa = order[a.type] ?? 99;
    const ob = order[b.type] ?? 99;
    if (oa !== ob) return oa - ob;
    return a.title.localeCompare(b.title);
  });
}

function selectedContextItems() {
  return projectContextItems.filter((item) => selectedProjectContextKeys.has(item.key));
}

function manualQueryValue() {
  return document.getElementById("literature-query")?.value?.trim() || "";
}

function composeClusterQuestion() {
  const manual = manualQueryValue();
  const picked = selectedContextItems();
  if (!picked.length) return manual;
  const contextBlock = picked.map((item) => `- ${item.snippet}`).join("\n");
  if (!manual) return `Project context for literature search:\n${contextBlock}`;
  return `${manual}${CONTEXT_APPEND_MARKER}${contextBlock}`;
}

/** @deprecated use composeClusterQuestion */
function composeLiteratureQuery() {
  return composeClusterQuestion();
}

function composeProjectSearchQuery() {
  if (!projectLiteratureKeywords.length) return "";
  return projectLiteratureKeywords.join(" ");
}

function displaySearchLabel(searchQuery = composeProjectSearchQuery()) {
  if (!searchQuery) return "";
  return shortText(searchQuery, 120);
}

function displayQueryLabel() {
  const manual = manualQueryValue();
  if (manual) return shortText(manual, 140);
  const titles = selectedContextItems().map((item) => item.title);
  if (!titles.length) return "";
  return shortText(titles.join("; "), 140);
}

function displayResultsHeader(searchQuery, questionLabel) {
  const search = shortText(searchQuery || "", 100);
  const question = questionLabel || displayQueryLabel();
  if (search && question) return `Поиск: ${search} · Вопрос: ${question}`;
  return search || question || "";
}

function selectedLiteratureLimit() {
  const input = document.getElementById("literature-limit");
  const raw = Number(input?.value || loadSettings().limit || 10);
  const limit = Math.max(1, Math.min(50, Number.isFinite(raw) ? Math.round(raw) : 10));
  if (input) input.value = String(limit);
  return limit;
}

function selectedProjectId() {
  return document.getElementById("literature-project-select")?.value || "";
}

function updateMortalCombatLink() {
  const link = document.getElementById("mortal-combat-launch");
  if (!link) return;
  const papers = selectedPapers();
  const currentProject = selectedProjectId() || new URLSearchParams(location.search).get("project") || "";
  const params = new URLSearchParams({ project: currentProject });
  if (currentProject) { try { sessionStorage.setItem("koi-mortal-project", currentProject); } catch { /* private mode */ } }
  if (papers[0]) params.set("primary", encodeURIComponent(JSON.stringify(papers[0])));
  if (papers[1]) params.set("reviewer", encodeURIComponent(JSON.stringify(papers[1])));
  link.href = `mortal.html?${params.toString()}`;
  link.classList.toggle("is-ready", papers.length >= 2);
}

function shouldOverwritePaperAnswers() {
  return Boolean(document.getElementById("literature-overwrite-answers")?.checked);
}

function shouldAutoTranslateQuestion() {
  return Boolean(document.getElementById("literature-auto-translate")?.checked);
}

function getSelectedResults() {
  if (!literatureResults.length) return [];
  return literatureResults.filter((paper) => selectedPaperUrls.has(paper.arxiv_url));
}

function updateSelectionSummary() {
  const el = document.getElementById("literature-selection-summary");
  if (!el) return;
  const count = getSelectedResults().length;
  if (!literatureResults.length) {
    el.textContent = "Нет статей.";
    return;
  }
  el.textContent = `${count} из ${literatureResults.length} выбрано.`;
}

function updateActionButtons() {
  updateSelectionSummary();
}

function selectedClustersFromRun(run = latestPaperAnswerRun) {
  if (!run?.clusters?.length) return [];
  return run.clusters.filter((cluster) => selectedClusterKeys.has(cluster.key));
}

function updateClusterStats(run = latestPaperAnswerRun) {
  const statsEl = document.getElementById("rw-cluster-stats");
  const articlesEl = document.getElementById("rw-stat-articles");
  const clustersEl = document.getElementById("rw-stat-clusters");
  if (!statsEl) return;

  const paperCount = run?.papers?.length || literatureResults.length || 0;
  const clusterCount = run?.clusters?.length || 0;

  if (!clusterCount) {
    statsEl.classList.add("hidden");
    if (articlesEl) articlesEl.textContent = "0";
    if (clustersEl) clustersEl.textContent = "0";
    return;
  }

  statsEl.classList.remove("hidden");
  if (articlesEl) articlesEl.textContent = String(paperCount);
  if (clustersEl) clustersEl.textContent = String(clusterCount);
}

function updateRelatedWorksSummary() {
  const button = document.getElementById("related-works-generate");
  const badge = document.getElementById("rw-related-badge");
  const chosen = selectedClustersFromRun();
  updateClusterStats();
  if (button) button.disabled = chosen.length === 0 || !selectedProjectId();
  if (badge) {
    const output = document.getElementById("related-works-output");
    const hasContent = Boolean(output?.classList.contains("has-content"));
    if (hasContent) {
      badge.hidden = false;
      badge.textContent = "готово";
    } else if (chosen.length) {
      badge.hidden = false;
      badge.textContent = `${chosen.length} кл`;
    } else {
      badge.hidden = true;
      badge.textContent = "";
    }
  }
  updateInboxIndicator();
  updateLiteratureInboxSetupNotice();
}

function defaultRelatedWorksProblem() {
  return manualQueryValue() || String(latestPaperAnswerRun?.question || "").trim() || "";
}

function toggleClusterSelection(key) {
  if (!key) return;
  if (selectedClusterKeys.has(key)) selectedClusterKeys.delete(key);
  else selectedClusterKeys.add(key);
  renderClusterResults(latestPaperAnswerRun);
  updateRelatedWorksSummary();
}

function selectAllResults() {
  selectedPaperUrls = new Set(literatureResults.map((paper) => paper.arxiv_url));
  renderLiteratureResults(literatureResults, displayQueryLabel());
}

function clearSelectedResults() {
  selectedPaperUrls = new Set();
  renderLiteratureResults(literatureResults, displayQueryLabel());
}

function mapDiscoverPaperToResult(paper, index) {
  return {
    title: paper.title,
    arxiv_url: paper.arxiv_url,
    authors: paper.authors,
    abstract_preview: shortText(paper.abstract, 280),
    score: Math.max(0.61, 1 - index * 0.02),
    matched_terms: [],
  };
}

function mergePaperResults(primary, secondary, limit) {
  const seen = new Set(primary.map((p) => p.arxiv_url));
  const merged = [...primary];
  for (const paper of secondary) {
    if (seen.has(paper.arxiv_url)) continue;
    merged.push(paper);
    seen.add(paper.arxiv_url);
    if (merged.length >= limit) break;
  }
  return merged.slice(0, limit);
}

async function searchPapers(query, limit) {
  const mode = getSearchMode();
  let localResults = [];
  let internetResults = [];

  if (mode === "local" || mode === "both") {
    if (!libraryExists) {
      if (mode === "local") {
        throw new Error(
          "Локальная база не найдена. Загрузите CSV в настройках или выберите поиск в интернете."
        );
      }
    } else {
      showLoader("Поиск в локальной базе…");
      const data = await KoiApi.searchLibrary(query, limit);
      localResults = data.results || [];
    }
  }

  if (mode === "internet" || (mode === "both" && localResults.length < limit)) {
    showLoader("Поиск статей на arXiv…");
    const data = await KoiApi.searchInternet(query, limit);
    internetResults = data.results || (data.papers || []).map(mapDiscoverPaperToResult);
    if (internetResults.length) {
      libraryExists = true;
      updateLibraryStatusHint();
    }
  }

  if (mode === "both") {
    return mergePaperResults(localResults, internetResults, limit);
  }
  if (mode === "internet") return internetResults.slice(0, limit);
  return localResults.slice(0, limit);
}

function shortProjectLabel(title, id = "") {
  const raw = String(title || id || "").trim();
  if (!raw) return "Проект";
  const head = raw.split(/[—\-·|]/)[0]?.trim() || raw;
  return head.length > 48 ? `${head.slice(0, 46)}…` : head;
}

function updateProjectBanner(title, projectId = selectedProjectId()) {
  const titleEl = document.getElementById("rw-project-title");
  const backEl = document.getElementById("rw-project-back");
  const leadEl = document.getElementById("rw-search-stage-lead");
  const picker = document.querySelector(".rw-project-picker");
  const select = document.getElementById("literature-project-select");
  const hasProject = Boolean(projectId);
  if (titleEl) {
    titleEl.textContent = "Обзор литературы";
  }
  if (backEl) {
    backEl.href = hasProject
      ? `index.html?project=${encodeURIComponent(projectId)}`
      : "index.html";
    backEl.classList.toggle("hidden", !hasProject);
    const label = shortProjectLabel(title, projectId);
    backEl.title = hasProject ? `К проекту: ${label}` : "К проекту";
  }
  if (picker) {
    const multi = (select?.options?.length || 0) > 1;
    picker.classList.toggle("is-solo", !multi);
    picker.hidden = !hasProject;
  }
  if (leadEl) {
    leadEl.textContent = hasProject
      ? "Задайте вопрос — по нему сгруппируем статьи слева."
      : "Выберите проект, затем задайте вопрос.";
  }
  if (projectId && window.history?.replaceState) {
    const url = new URL(window.location.href);
    url.searchParams.set("project", projectId);
    window.history.replaceState({}, "", url);
  }
}

async function loadProjectOptions() {
  const select = document.getElementById("literature-project-select");
  if (!select) return;
  const requested = new URLSearchParams(window.location.search).get("project");
  let list = [];
  try {
    const grouped = await KoiApi.listProjectsGrouped();
    for (const g of grouped.groups || []) {
      for (const p of g.projects || []) list.push(p);
    }
    for (const p of grouped.ungrouped || []) list.push(p);
  } catch {
    list = await KoiApi.listProjects();
  }
  if (!list.length) {
    list = await KoiApi.listProjects();
  }
  const seen = new Set();
  list = list.filter((p) => {
    if (!p?.id || seen.has(p.id)) return false;
    seen.add(p.id);
    return true;
  });
  select.innerHTML = list
    .map((p) => {
      const label = shortProjectLabel(p.title, p.id);
      return `<option value="${escapeHtml(p.id)}">${escapeHtml(label)}</option>`;
    })
    .join("");
  const preferred =
    (requested && list.find((p) => p.id === requested)?.id) || list[0]?.id || "";
  if (preferred) select.value = preferred;
  if (preferred) { try { sessionStorage.setItem("koi-mortal-project", preferred); } catch { /* private mode */ } }
  updateMortalCombatLink();
  const active = list.find((p) => p.id === preferred);
  updateProjectBanner(active?.title, preferred);
}

function updateProjectKeywordsHint() {
  const el = document.getElementById("rw-project-keywords-hint");
  if (!el) return;
  if (!projectLiteratureKeywords.length) {
    el.textContent = "Нет literature_keywords в project.md";
    el.className = "rw-settings-hint rw-settings-hint--quiet error";
    return;
  }
  el.textContent = projectLiteratureKeywords.join(" · ");
  el.className = "rw-settings-hint rw-settings-hint--quiet";
}

async function loadProjectContext(projectId) {
  selectedProjectContextKeys = new Set();
  projectContextItems = [];
  projectLiteratureKeywords = [];
  renderProjectContextSummary();
  renderProjectContext();
  updateProjectKeywordsHint();
  if (!projectId) {
    updateProjectBanner("", "");
    setProjectContextStatus("Выберите проект в настройках.");
    return;
  }
  setProjectContextStatus("Загрузка контекста…");
  try {
    const project = await KoiApi.getProject(projectId);
    updateProjectBanner(project.title, projectId);
    projectLiteratureKeywords = Array.isArray(project.literature_keywords)
      ? project.literature_keywords.map((item) => String(item).trim()).filter(Boolean)
      : [];
    projectContextItems = buildProjectContextItems(project);
    renderProjectContextSummary();
    renderProjectContext();
    updateProjectKeywordsHint();
    if (!projectContextItems.length) {
      setProjectContextStatus("В проекте пока нет узлов или kanban-задач.");
    } else {
      setProjectContextStatus(`Загружено ${projectContextItems.length} элементов.`);
    }
  } catch (err) {
    projectContextItems = [];
    projectLiteratureKeywords = [];
    renderProjectContextSummary();
    renderProjectContext();
    updateProjectKeywordsHint();
    setProjectContextStatus(`Ошибка: ${err.message}`, true);
  }
}

function toggleProjectContextItem(key) {
  if (selectedProjectContextKeys.has(key)) selectedProjectContextKeys.delete(key);
  else selectedProjectContextKeys.add(key);
  renderProjectContextSummary();
  renderProjectContext();
}

function clearProjectContextSelection() {
  selectedProjectContextKeys = new Set();
  renderProjectContextSummary();
  renderProjectContext();
}

async function translateQueryToEnglish(text, { silent = false } = {}) {
  const sourceText = String(text || composeClusterQuestion() || "").trim();
  if (!sourceText) {
    if (!silent) setLiteratureStatus("Введите вопрос или добавьте контекст.", true);
    return "";
  }
  if (!silent) showLoader("Перевод вопроса на английский…");
  try {
    const data = await KoiApi.translateToEnglish(sourceText);
    let translatedText = String(data.translated_text || "").trim();
    translatedText = translatedText
      .replace(/^Project context for literature search:\n/i, "")
      .replace(/\n\nProject context:\n/g, "\n\n")
      .trim();
    if (!text) {
      clearProjectContextSelection();
      const input = document.getElementById("literature-query");
      if (input) input.value = translatedText.split("\n")[0].trim();
    }
    if (!silent) setLiteratureStatus(`Переведено (${data.backend || "agent"}).`);
    return translatedText;
  } catch (err) {
    if (!silent) setLiteratureStatus(err.message, true);
    throw err;
  }
}

function renderProjectContext() {
  const root = document.getElementById("literature-context-groups");
  if (!root) return;
  if (!projectContextItems.length) {
    root.innerHTML = `<p class="literature-empty">Нет доступного контекста для выбранного проекта.</p>`;
    return;
  }
  const groupLabels = { problem: "Problem", cause: "Causes", hypothesis: "Hypotheses", task: "Kanban Tasks" };
  const order = ["problem", "cause", "hypothesis", "task"];
  const groups = new Map();
  for (const type of order) groups.set(type, []);
  for (const item of projectContextItems) groups.get(item.type)?.push(item);

  root.innerHTML = order
    .filter((type) => groups.get(type)?.length)
    .map((type) => {
      const items = groups.get(type) || [];
      return `
        <section class="literature-context-group">
          <h4 class="literature-context-group-title">${escapeHtml(groupLabels[type] || contextTypeLabel(type))}</h4>
          <div class="literature-context-items">
            ${items
              .map((item) => {
                const selected = selectedProjectContextKeys.has(item.key);
                return `
                  <article class="literature-context-item${selected ? " is-selected" : ""}">
                    <div class="literature-context-item-main">
                      <strong>${escapeHtml(item.title)}</strong>
                      ${item.meta ? `<span>${escapeHtml(item.meta)}</span>` : ""}
                      <p>${escapeHtml(item.subtitle || "")}</p>
                    </div>
                    <button type="button" class="btn btn-small literature-context-toggle" data-context-key="${escapeHtml(item.key)}">${selected ? "Убрать" : "Добавить"}</button>
                  </article>`;
              })
              .join("")}
          </div>
        </section>`;
    })
    .join("");

  root.querySelectorAll(".literature-context-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.getAttribute("data-context-key");
      if (key) toggleProjectContextItem(key);
    });
  });
}

function renderProjectContextSummary() {
  const root = document.getElementById("literature-context-summary-list");
  if (!root) return;
  const picked = selectedContextItems();
  if (!picked.length) {
    root.innerHTML = `<p class="literature-empty">Контекст не выбран.</p>`;
    return;
  }
  root.innerHTML = picked
    .map(
      (item) => `
        <article class="literature-context-pill">
          <div class="literature-context-pill-main">
            <strong>${escapeHtml(item.title)}</strong>
            <span>${escapeHtml(contextTypeLabel(item.type))}</span>
          </div>
          <button type="button" class="btn btn-small literature-context-pill-remove" data-context-key="${escapeHtml(item.key)}">Убрать</button>
        </article>`
    )
    .join("");

  root.querySelectorAll(".literature-context-pill-remove").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.getAttribute("data-context-key");
      if (key) toggleProjectContextItem(key);
    });
  });
}

async function loadLatestPaperAnswerRun(projectId) {
  if (!projectId) {
    latestPaperAnswerRun = null;
    selectedClusterKeys = new Set();
    return;
  }
  try {
    latestPaperAnswerRun = await KoiApi.getLatestPaperQuestionAgentRun(projectId);
    selectedClusterKeys = new Set((latestPaperAnswerRun.clusters || []).map((c) => c.key));
  } catch {
    latestPaperAnswerRun = null;
    selectedClusterKeys = new Set();
  }
}

function showClusterModal(cluster, members, run) {
  const modal = document.getElementById("cluster-modal");
  const title = document.getElementById("cluster-modal-title");
  const content = document.getElementById("cluster-modal-content");
  if (!modal || !title || !content) return;

  const papersHtml = members.length
    ? members.map((paper) => renderClusterPaperCard(paper)).join("")
    : "<p>No papers found for this cluster.</p>";

  title.textContent = cluster.label || "Cluster details";
  content.innerHTML = `
    <div class="cluster-modal-meta">
      <p><strong>Question:</strong> ${escapeHtml(run.question || "n/a")}</p>
      <p><strong>Описание:</strong> ${escapeHtml(cluster.answer || cluster.description || "n/a")}</p>
    </div>
    ${
      cluster.rationale
        ? `<section class="cluster-modal-section"><h3>Почему вместе</h3><p>${escapeHtml(cluster.rationale)}</p></section>`
        : ""
    }
    <section class="cluster-modal-section">
      <h3>Статьи</h3>
      <div class="cluster-modal-paper-grid">${papersHtml}</div>
    </section>`;

  activeClusterModal = modal;
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
}

function hideClusterModal() {
  if (!activeClusterModal) return;
  activeClusterModal.classList.add("hidden");
  activeClusterModal.setAttribute("aria-hidden", "true");
  activeClusterModal = null;
  document.body.classList.remove("modal-open");
}

function setLibraryUploadStatus(msg, isError = false) {
  const el = document.getElementById("library-upload-status");
  if (!el) return;
  el.textContent = msg;
  el.className = "library-upload-status" + (isError ? " error" : msg ? " ok" : "");
}

function setLibraryBootstrapStatus(msg, isError = false) {
  const el = document.getElementById("library-agent-bootstrap-status");
  if (!el) return;
  el.textContent = msg;
  el.className = "library-upload-status" + (isError ? " error" : msg ? " ok" : "");
}

function updateLibraryUploadFilename() {
  const input = document.getElementById("library-upload-input");
  const label = document.getElementById("library-upload-filename");
  if (!label) return;
  const file = input?.files?.[0];
  label.textContent = file ? file.name : "Выберите CSV";
}

function updateLibraryStatusHint() {
  const el = document.getElementById("rw-library-status");
  if (!el) return;
  const mode = currentSearchModeFromDom();
  if (libraryExists) {
    el.textContent = mode === "internet" ? "" : "База найдена";
    el.className = "rw-settings-hint ok";
    return;
  }
  if (mode === "local" || mode === "both") {
    el.textContent = "База ещё не загружена";
    el.className = "rw-settings-hint";
    return;
  }
  el.textContent = "";
  el.className = "rw-settings-hint";
}

async function refreshLibraryStatus() {
  try {
    const status = await KoiApi.libraryStatus();
    libraryExists = Boolean(status.exists);
    updateLibraryStatusHint();
    if (!libraryExists && getSearchMode() === "local") {
      const settings = loadSettings();
      settings.searchMode = "internet";
      saveSettingsToStorage(settings);
      applySettingsToDom(settings);
    }
  } catch {
    libraryExists = false;
    updateLibraryStatusHint();
  }
}

function showSettingsModal() {
  const modal = document.getElementById("rw-settings-modal");
  if (!modal) return;
  applySettingsToDom();
  activeSettingsModal = modal;
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  void refreshLibraryStatus().then(() => updateSettingsSourceUi());
}

function hideSettingsModal() {
  if (!activeSettingsModal) return;
  activeSettingsModal.classList.add("hidden");
  activeSettingsModal.setAttribute("aria-hidden", "true");
  activeSettingsModal = null;
  if (!activeContextModal && !activeClusterModal) {
    document.body.classList.remove("modal-open");
  }
}

function showContextModal() {
  const modal = document.getElementById("literature-context-modal");
  if (!modal) return;
  activeContextModal = modal;
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
}

function hideContextModal() {
  if (!activeContextModal) return;
  activeContextModal.classList.add("hidden");
  activeContextModal.setAttribute("aria-hidden", "true");
  activeContextModal = null;
  if (!activeSettingsModal && !activeClusterModal) {
    document.body.classList.remove("modal-open");
  }
}

async function uploadLibraryFile() {
  const input = document.getElementById("library-upload-input");
  const button = document.getElementById("library-upload-submit");
  const file = input?.files?.[0];
  if (!file) {
    setLibraryUploadStatus("Сначала выберите CSV.", true);
    return;
  }
  button?.setAttribute("disabled", "disabled");
  setLibraryUploadStatus("Загрузка…");
  try {
    const data = await KoiApi.uploadLibrary(file);
    libraryExists = true;
    updateLibraryStatusHint();
    setLibraryUploadStatus(`Загружено ${data.count} статей в ${data.csv_path}.`);
    await loadLibraryIntoSidebar({ silent: true });
    setLiteratureStatus(`База обновлена: ${data.count} статей.`);
  } catch (err) {
    setLibraryUploadStatus(err.message, true);
  } finally {
    button?.removeAttribute("disabled");
  }
}

async function bootstrapLibraryFromAgent() {
  const button = document.getElementById("library-agent-bootstrap-submit");
  const limit = selectedLiteratureLimit();
  let query = composeProjectSearchQuery();
  if (!query) {
    setLibraryBootstrapStatus(
      "В project.md нет literature_keywords — добавьте ключевые слова проекта.",
      true
    );
    return;
  }
  if (shouldAutoTranslateQuestion()) {
    try {
      query = await translateQueryToEnglish(query, { silent: true });
    } catch {
      setLibraryBootstrapStatus("Не удалось перевести ключевые слова.", true);
      return;
    }
  }
  button?.setAttribute("disabled", "disabled");
  setLibraryBootstrapStatus("Обновление базы через arXiv…");
  try {
    const data = await KoiApi.discoverLibrary(query, limit);
    libraryExists = true;
    updateLibraryStatusHint();
    setLibraryBootstrapStatus(`База обновлена: ${data.count} статей.`);
    await loadLibraryIntoSidebar({ silent: true });
    setLiteratureStatus(`База обновлена: ${data.count} статей.`);
  } catch (err) {
    setLibraryBootstrapStatus(err.message, true);
  } finally {
    button?.removeAttribute("disabled");
  }
}

function isInboxAgentMode() {
  return appSettings.agent_chat_mode === "cursor_inbox";
}

async function refreshAppSettings() {
  try {
    const data = await KoiApi.getSettings();
    appSettings = {
      ...appSettings,
      ...data,
      literature_inbox_configured: Boolean(data.literature_inbox_configured),
      literature_inbox_watcher_running: Boolean(data.literature_inbox_watcher_running),
    };
    syncLiteratureInboxConfiguredCache();
    ensureLiteratureInboxBootstrapCached();
    updateInboxIndicator();
    updateLiteratureInboxSetupNotice();
    if (inboxIsReady()) stopLiteratureInboxStatusPoll();
  } catch {
    /* API may be restarting */
  }
}

/** Cursor-чат инициализирован (пользователь нажал «Inbox готов» после bootstrap). */
function inboxIsReady() {
  return isInboxAgentMode() && isLiteratureInboxConfigured();
}

function updateInboxRestartButton() {
  const btn = document.getElementById("rw-inbox-restart");
  if (!btn) return;
  const split = document.getElementById("rw-workspace")?.classList.contains("is-split");
  const show =
    split &&
    isInboxAgentMode() &&
    isLiteratureInboxConfigured() &&
    activeRelatedWorkPhase !== "processing";
  btn.classList.toggle("hidden", !show);
}

function updateRelatedWorkWaitingActions() {
  const actions = document.getElementById("rw-related-waiting-actions");
  const waiting = document.getElementById("rw-related-waiting");
  if (!actions || !waiting) return;

  const hasMessage = Boolean(
    lastRelatedWorkInboxMessage ||
      lastRelatedWorkCursorMessage ||
      appSettings.literature_inbox_bootstrap_prompt
  );
  const visible =
    !waiting.classList.contains("hidden") &&
    isInboxAgentMode() &&
    activeRelatedWorkPhase === "pending" &&
    !isLiteratureInboxOperational() &&
    hasMessage;

  actions.classList.toggle("hidden", !visible);
}

function updateInboxIndicator() {
  const box = document.getElementById("rw-inbox-indicator");
  const textEl = document.getElementById("rw-inbox-indicator-text");
  const dot = document.getElementById("rw-inbox-dot");
  if (!box || !textEl) return;

  const split = document.getElementById("rw-workspace")?.classList.contains("is-split");
  if (!split || !isInboxAgentMode()) {
    box.classList.add("hidden");
    return;
  }

  box.classList.remove("hidden");
  dot?.classList.remove("is-ok", "is-warn");
  box.classList.remove("rw-inbox-indicator--action");

  const status = literatureInboxStatus();
  if (status === "ready" && isLiteratureInboxOperational()) {
    dot?.classList.add("is-ok");
    if (activeRelatedWorkPhase === "processing") {
      textEl.textContent = "Literature Inbox · агент пишет Related Work";
    } else if (activeRelatedWorkItemId && relatedWorkSubmitted) {
      textEl.textContent = "Literature Inbox · задача в очереди";
    } else {
      textEl.textContent = "Literature Inbox · ждёт запросов из UI";
    }
  } else if (status === "no_watcher") {
    dot?.classList.add("is-warn");
    textEl.textContent = "Cursor настроен, но watcher не запущен — ./scripts/koi-serve.sh start";
    box.classList.add("rw-inbox-indicator--action");
  } else {
    dot?.classList.add("is-warn");
    textEl.textContent = isInboxAgentMode()
      ? "Literature Inbox не настроен — нажмите, чтобы показать инструкцию"
      : "Режим не Inbox — см. настройки агента";
    box.classList.add("rw-inbox-indicator--action");
  }
  updateInboxRestartButton();
}

function showLiteratureInboxSetup() {
  ensureLiteratureInboxBootstrapCached();
  updateLiteratureInboxSetupNotice();
  const box = document.getElementById("rw-inbox-message");
  box?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function formatRelatedWorkElapsed(seconds) {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function startRelatedWorkWaitTimer() {
  stopRelatedWorkWaitTimer();
  relatedWorkWaitStartedAt = Date.now();
  const tick = () => {
    if (!relatedWorkWaitStartedAt) return;
    const sec = Math.floor((Date.now() - relatedWorkWaitStartedAt) / 1000);
    const label = formatRelatedWorkElapsed(sec);
    const timerEl = document.getElementById("rw-related-waiting-timer");
    if (timerEl) timerEl.textContent = label;
  };
  tick();
  relatedWorkWaitTimer = setInterval(tick, 1000);
}

function stopRelatedWorkWaitTimer() {
  if (relatedWorkWaitTimer) {
    clearInterval(relatedWorkWaitTimer);
    relatedWorkWaitTimer = null;
  }
  relatedWorkWaitStartedAt = null;
  const timerEl = document.getElementById("rw-related-waiting-timer");
  if (timerEl) timerEl.textContent = "00:00";
}

function composeRelatedWorkInboxMessage(data = {}) {
  if (!isLiteratureInboxConfigured() && isInboxAgentMode()) {
    if (data.inbox_message) return data.inbox_message;
    if (appSettings.literature_inbox_bootstrap_prompt) {
      return appSettings.literature_inbox_bootstrap_prompt;
    }
  }
  if (data.inbox_message && isInboxAgentMode()) return data.inbox_message;
  if (inboxIsReady()) return "";
  return data.cursor_message || lastRelatedWorkCursorMessage || "";
}

function updateRelatedWorkInboxMessage(message) {
  const trimmed = String(message || "").trim();
  if (trimmed) lastRelatedWorkInboxMessage = trimmed;
  if (!isLiteratureInboxConfigured() && isInboxAgentMode()) {
    updateLiteratureInboxSetupNotice();
  }
}

async function copyRelatedWorkInboxMessage(statusEl) {
  const text =
    lastRelatedWorkInboxMessage ||
    appSettings.literature_inbox_bootstrap_prompt ||
    "";
  const ok = await copyRelatedWorkCursorMessage(text, statusEl);
  if (ok) {
    literatureInboxBootstrapCopied = true;
    updateLiteratureInboxSetupNotice();
  }
  return ok;
}

function setRelatedWorkWaiting(isWaiting, phase = "pending") {
  const waiting = document.getElementById("rw-related-waiting");
  const relatedPane = document.getElementById("rw-related-pane");
  const lead = document.getElementById("rw-related-waiting-lead");
  const hint = document.getElementById("rw-related-waiting-hint");
  const timerRow = document.querySelector(".rw-related-waiting-timer-row");
  if (!waiting) return;

  if (isWaiting) {
    relatedPane?.classList.remove("hidden");
    setRelatedPaneCollapsed(false);
    waiting.classList.remove("hidden");
    timerRow?.classList.remove("hidden");
    activeRelatedWorkPhase = phase;
    startRelatedWorkWaitTimer();
    if (phase === "processing") {
      waiting.classList.add("is-processing");
      waiting.classList.remove("is-pending-queue");
      hideRelatedWorkQueuePanel();
      hideRelatedWorkSetupText();
      updateRelatedWorkInboxMessage("");
      hideRelatedInboxModal();
      showRelatedWorkAgentPanel();
    } else {
      waiting.classList.remove("is-processing");
      hideRelatedWorkAgentPanel();
      const needsSetup = isInboxAgentMode() && !isLiteratureInboxOperational();
      if (needsSetup) {
        waiting.classList.remove("is-pending-queue");
        hideRelatedWorkQueuePanel();
        if (isLiteratureInboxConfigured()) {
          showRelatedWorkSetupText(
            "Watcher не запущен",
            "Запустите ./scripts/koi-serve.sh start — затем задача уйдёт в очередь автоматически."
          );
        } else {
          showRelatedWorkSetupText(
            "Настройте Literature Inbox один раз",
            "Скопируйте сообщение кнопкой ниже → вставьте в чат ResearchOS Literature Inbox → tail -f related-work-watch.log → «Inbox готов»."
          );
        }
        updateRelatedWorkInboxMessage(lastRelatedWorkInboxMessage);
      } else {
        waiting.classList.add("is-pending-queue");
        hideRelatedWorkSetupText();
        showRelatedWorkQueuePanel();
        updateRelatedWorkInboxMessage("");
      }
    }
    setRelatedWorksStatus("");
  } else {
    waiting.classList.add("hidden");
    waiting.classList.remove("is-processing", "is-pending-queue");
    timerRow?.classList.add("hidden");
    activeRelatedWorkPhase = null;
    stopRelatedWorkWaitTimer();
    updateRelatedWorkInboxMessage("");
    hideRelatedWorkQueuePanel();
    hideRelatedWorkAgentPanel();
    hideRelatedWorkSetupText();
  }
  updateInboxIndicator();
  updateLiteratureInboxSetupNotice();
  updateRelatedWorkWaitingActions();
}

function showRelatedWorkSetupText(leadText, hintText) {
  const lead = document.getElementById("rw-related-waiting-lead");
  const hint = document.getElementById("rw-related-waiting-hint");
  if (lead) {
    lead.textContent = leadText;
    lead.classList.remove("hidden");
  }
  if (hint) {
    hint.textContent = hintText;
    hint.classList.remove("hidden");
  }
}

function hideRelatedWorkSetupText() {
  document.getElementById("rw-related-waiting-lead")?.classList.add("hidden");
  document.getElementById("rw-related-waiting-hint")?.classList.add("hidden");
}

function showRelatedWorkQueuePanel() {
  const panel = document.getElementById("rw-related-queue-panel");
  panel?.classList.remove("hidden");
  attachRotatingHint(document.getElementById("rw-related-queue-hint"), "relatedQueue");
}

function hideRelatedWorkQueuePanel() {
  detachRotatingHint(document.getElementById("rw-related-queue-hint"));
  document.getElementById("rw-related-queue-panel")?.classList.add("hidden");
}

function showRelatedWorkAgentPanel() {
  const panel = document.getElementById("rw-related-agent-panel");
  panel?.classList.remove("hidden");
  attachRotatingHint(document.getElementById("rw-related-agent-hint"), "related");
}

function hideRelatedWorkAgentPanel() {
  detachRotatingHint(document.getElementById("rw-related-agent-hint"));
  document.getElementById("rw-related-agent-panel")?.classList.add("hidden");
}

function applyRelatedWorkProcessing(item = {}) {
  activeRelatedWorkItemId = item.id || activeRelatedWorkItemId;
  if (item.project_id || selectedProjectId()) {
    saveRelatedWorkPending(item.project_id || selectedProjectId(), activeRelatedWorkItemId);
  }
  setRelatedWorkWaiting(true, "processing");
  syncRelatedWorkPolling();
}

function hideRelatedCursorPanel() {
  /* inline panel removed — message lives in modal only */
}

function showRelatedCursorPanel() {
  /* inline panel removed — message lives in modal only */
}

function showRelatedInboxModal(cursorMessage) {
  const message = String(cursorMessage || lastRelatedWorkInboxMessage || "").trim();
  lastRelatedWorkCursorMessage = message;
  lastRelatedWorkInboxMessage = message;
  const modal = document.getElementById("rw-related-inbox-modal");
  if (!modal) return;
  const watcherEl = document.getElementById("rw-related-inbox-watcher-status");
  if (watcherEl) {
    watcherEl.classList.remove("is-ok", "is-warn");
    if (!isInboxAgentMode()) {
      watcherEl.textContent = "Режим не Inbox — используйте hooks или API-агента.";
    } else if (isLiteratureInboxOperational()) {
      watcherEl.textContent =
        "Literature Inbox работает — watcher пишет RELATED_WORK_WAKE в .run/logs/related-work-watch.log.";
      watcherEl.classList.add("is-ok");
    } else if (isLiteratureInboxConfigured()) {
      watcherEl.textContent =
        "Inbox отмечен, но watcher не запущен. Выполните ./scripts/koi-serve.sh start и настройте loop в Cursor.";
      watcherEl.classList.add("is-warn");
    } else {
      watcherEl.textContent =
        "Literature Inbox ещё не настроен. Скопируйте bootstrap и вставьте в чат ResearchOS Literature Inbox.";
      watcherEl.classList.add("is-warn");
    }
  }
  activeRelatedInboxModal = modal;
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  void copyRelatedWorkCursorMessage(
    lastRelatedWorkCursorMessage,
    document.getElementById("rw-related-inbox-copy-status")
  );
}

function hideRelatedInboxModal() {
  const modal = activeRelatedInboxModal || document.getElementById("rw-related-inbox-modal");
  if (!modal) return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
  if (activeRelatedInboxModal === modal) activeRelatedInboxModal = null;
  if (
    !activeClusterModal &&
    !activeSettingsModal &&
    !activeContextModal &&
    !activeClusterPromptModal
  ) {
    document.body.classList.remove("modal-open");
  }
}

async function copyRelatedWorkCursorMessage(message, statusEl) {
  const text = String(message || "").trim();
  if (!text) return false;
  try {
    await navigator.clipboard.writeText(text);
    if (statusEl) {
      statusEl.textContent = "Скопировано — вставьте в чат Cursor.";
      setTimeout(() => {
        if (statusEl.textContent.startsWith("Скопировано")) statusEl.textContent = "";
      }, 5000);
    }
    return true;
  } catch {
    if (statusEl) statusEl.textContent = "Не удалось скопировать — скопируйте из блока ниже.";
    return false;
  }
}

function relatedWorkPendingKey(projectId) {
  return `${RW_PENDING_STORAGE_PREFIX}:${projectId || ""}`;
}

function saveRelatedWorkPending(projectId, itemId) {
  if (!projectId || !itemId) return;
  try {
    sessionStorage.setItem(relatedWorkPendingKey(projectId), itemId);
  } catch {
    /* private mode */
  }
}

function loadRelatedWorkPending(projectId) {
  if (!projectId) return null;
  try {
    return sessionStorage.getItem(relatedWorkPendingKey(projectId));
  } catch {
    return null;
  }
}

function clearRelatedWorkPending(projectId) {
  if (!projectId) return;
  try {
    sessionStorage.removeItem(relatedWorkPendingKey(projectId));
  } catch {
    /* ignore */
  }
}

async function restoreRelatedWorkOnLoad() {
  stopRelatedWorkPollTimer();
  relatedWorkSubmitted = false;
  activeRelatedWorkItemId = null;
  activeRelatedWorkPhase = null;
  updateRelatedWorkInboxMessage("");
  hideRelatedInboxModal();

  const projectId = selectedProjectId();
  const savedId = loadRelatedWorkPending(projectId);

  if (!savedId) {
    document.getElementById("rw-related-pane")?.classList.add("hidden");
    document.getElementById("related-works-output")?.classList.remove("has-content");
    const output = document.getElementById("related-works-output");
    if (output) output.textContent = "";
    setRelatedWorksStatus("");
    updateInboxIndicator();
    return;
  }

  try {
    const item = await KoiApi.getRelatedWorkItem(savedId);
    setWorkspaceSplit(true);
    document.getElementById("rw-related-pane")?.classList.remove("hidden");

    if (item.status === "answered" && item.markdown) {
      applyRelatedWorkResult(item.markdown, item);
      clearRelatedWorkPending(projectId);
      updateInboxIndicator();
      return;
    }

    relatedWorkSubmitted = true;
    activeRelatedWorkItemId = savedId;

    if (item.status === "processing") {
      applyRelatedWorkProcessing(item);
    } else {
      setRelatedWorkWaiting(true, "pending");
      const msg = composeRelatedWorkInboxMessage(item);
      if (msg) updateRelatedWorkInboxMessage(msg);
    }
    startRelatedWorkPolling(savedId);
  } catch {
    clearRelatedWorkPending(projectId);
    document.getElementById("rw-related-pane")?.classList.add("hidden");
  }
  updateInboxIndicator();
  updateLiteratureInboxSetupNotice();
}

function stopRelatedWorkPollTimer() {
  if (relatedWorkPollTimer) {
    clearInterval(relatedWorkPollTimer);
    relatedWorkPollTimer = null;
  }
}

function stopRelatedWorkPolling() {
  stopRelatedWorkPollTimer();
  activeRelatedWorkItemId = null;
  activeRelatedWorkPhase = null;
  updateInboxIndicator();
  updateLiteratureInboxSetupNotice();
}

function syncRelatedWorkPolling() {
  if (activeRelatedWorkItemId && !relatedWorkPollTimer) {
    relatedWorkPollTimer = setInterval(() => {
      void pollRelatedWorkItem(activeRelatedWorkItemId);
    }, RELATED_WORK_POLL_MS);
  } else if (!activeRelatedWorkItemId && relatedWorkPollTimer) {
    stopRelatedWorkPolling();
  }
}

async function pollRelatedWorkItem(itemId) {
  if (!itemId || !relatedWorkSubmitted) return;
  try {
    const item = await KoiApi.getRelatedWorkItem(itemId);
    if (item.status === "answered" && item.markdown) {
      applyRelatedWorkResult(item.markdown, item);
      clearRelatedWorkPending(item.project_id || selectedProjectId());
      stopRelatedWorkPolling();
      hideRelatedInboxModal();
      return;
    }
    if (item.status === "processing") {
      applyRelatedWorkProcessing(item);
      return;
    }
    if (item.status === "pending") {
      activeRelatedWorkItemId = itemId;
      setRelatedWorkWaiting(true, "pending");
    }
    syncRelatedWorkPolling();
  } catch (err) {
    setRelatedWorksStatus(`Ожидание ответа: ${err.message}`, true);
  }
}

function startRelatedWorkPolling(itemId) {
  stopRelatedWorkPolling();
  if (!itemId || !relatedWorkSubmitted) return;
  activeRelatedWorkItemId = itemId;
  saveRelatedWorkPending(selectedProjectId(), itemId);
  void pollRelatedWorkItem(itemId);
  syncRelatedWorkPolling();
}

function showRelatedWorkAnswer(markdown, data = {}) {
  const output = document.getElementById("related-works-output");
  const relatedPane = document.getElementById("rw-related-pane");
  setRelatedWorkWaiting(false);
  const text = String(markdown || "").trim();
  if (output) {
    if (text) {
      output.innerHTML = renderMarkdown(text, { collapsibleSections: false });
      output.classList.add("has-content", "markdown-preview");
    } else {
      output.innerHTML = "";
      output.classList.remove("has-content");
    }
  }
  relatedPane?.classList.remove("hidden");
  // Keep reading space for the cluster page; user can expand Related Work.
  setRelatedPaneCollapsed(Boolean(text) && Boolean(latestPaperAnswerRun?.clusters?.length));
  setRelatedWorksStatus("");
  updateRelatedWorksSummary();
}

function applyRelatedWorkResult(markdown, data = {}) {
  showRelatedWorkAnswer(markdown, data);
  hideRelatedInboxModal();
  stopRelatedWorkPolling();
  relatedWorkSubmitted = false;
  clearRelatedWorkPending(data.project_id || selectedProjectId());
  updateInboxIndicator();
  updateLiteratureInboxSetupNotice();
}

async function generateRelatedWorks() {
  const btn = document.getElementById("related-works-generate");
  const relatedPane = document.getElementById("rw-related-pane");
  const problem = defaultRelatedWorksProblem();
  const projectId = selectedProjectId();
  const clusters = selectedClustersFromRun();

  if (!projectId) {
    setRelatedWorksStatus("Выберите проект в настройках.", true);
    return;
  }
  if (!clusters.length) {
    setRelatedWorksStatus("Выберите хотя бы один кластер.", true);
    return;
  }
  if (!problem) {
    setRelatedWorksStatus("Введите вопрос в строке поиска.", true);
    return;
  }

  btn?.setAttribute("disabled", "disabled");
  relatedPane?.classList.remove("hidden");
  setRelatedPaneCollapsed(false);
  showRelatedLoader();
  setRelatedWorksStatus("");
  stopRelatedWorkPolling();
  relatedWorkSubmitted = false;
  hideRelatedInboxModal();

  try {
    await refreshAppSettings();
    const data = await KoiApi.generateRelatedWorks(projectId, {
      problem,
      cluster_keys: clusters.map((c) => c.key),
    });

    if (data.status === "answered" && data.markdown) {
      applyRelatedWorkResult(data.markdown, data);
      return;
    }

    const itemId = data.item_id || data.item?.id;
    const cursorMessage = data.cursor_message || "";
    if (!itemId) {
      throw new Error("Не удалось поставить Related Work в очередь.");
    }

    lastRelatedWorkCursorMessage = cursorMessage;
    const inboxMessage = composeRelatedWorkInboxMessage(data);
    relatedWorkSubmitted = true;
    saveRelatedWorkPending(projectId, itemId);
    setRelatedWorkWaiting(true, "pending");
    startRelatedWorkPolling(itemId);

    if (isInboxAgentMode()) {
      if (!isLiteratureInboxConfigured()) {
        const bootstrap =
          inboxMessage ||
          appSettings.literature_inbox_bootstrap_prompt ||
          "";
        if (bootstrap) lastRelatedWorkInboxMessage = bootstrap;
        showLiteratureInboxSetup();
        showRelatedInboxModal(bootstrap);
        setRelatedWorksStatus(
          "Скопируйте сообщение в ResearchOS Literature Inbox, затем нажмите «Inbox готов».",
          true
        );
      } else if (!isLiteratureInboxOperational()) {
        showLiteratureInboxSetup();
        setRelatedWorksStatus("Запустите watcher: ./scripts/koi-serve.sh start", true);
      } else {
        updateRelatedWorkInboxMessage("");
      }
    } else {
      showRelatedInboxModal(cursorMessage);
    }
  } catch (err) {
    relatedWorkSubmitted = false;
    setRelatedWorksStatus(err.message || "Не удалось отправить Related Work.", true);
    setRelatedWorkWaiting(false);
  } finally {
    hideRelatedLoader();
    btn?.removeAttribute("disabled");
    updateRelatedWorksSummary();
  }
}

function paperBelongsToCluster(paper, cluster) {
  if (!paper || !cluster) return false;
  const key = String(cluster.key || "");
  const paperKey = String(paper.cluster_key || paper.primary_cluster_key || "");
  if (key && paperKey && paperKey === key) return true;
  const keys = paper.cluster_keys;
  if (key && Array.isArray(keys) && keys.map(String).includes(key)) return true;
  const titles = cluster.paper_titles;
  const title = String(paper.title || "").trim();
  if (title && Array.isArray(titles) && titles.some((t) => String(t).trim() === title)) {
    return true;
  }
  return false;
}

function normalizeClusterPaper(paper, clusterKey = "") {
  if (!paper || typeof paper !== "object") return null;
  const title = String(paper.title || "").trim();
  if (!title) return null;
  const quotes = Array.isArray(paper.quotes)
    ? paper.quotes
        .map((q) =>
          typeof q === "string"
            ? { text: q, why: "" }
            : { text: String(q?.text || ""), why: String(q?.why || "") }
        )
        .filter((q) => q.text)
    : (paper.evidence || [])
        .map((text) => ({ text: String(text || ""), why: "" }))
        .filter((q) => q.text);
  const primary = String(
    paper.cluster_key || paper.primary_cluster_key || clusterKey || ""
  ).trim();
  return {
    ...paper,
    title,
    arxiv_url: paper.arxiv_url || paper.url || paper.link || "",
    cluster_key: primary,
    primary_cluster_key: paper.primary_cluster_key || primary,
    cluster_keys: Array.isArray(paper.cluster_keys)
      ? paper.cluster_keys.map(String)
      : primary
        ? [primary]
        : [],
    tldr: paper.tldr || paper.comprehensive_answer || paper.solution_summary || "",
    query_answer: paper.query_answer || paper.short_answer || paper.answer || "",
    short_answer: paper.short_answer || paper.query_answer || paper.answer || "",
    comprehensive_answer:
      paper.comprehensive_answer || paper.tldr || paper.solution_summary || "",
    quotes,
    evidence: quotes.map((q) => q.text),
  };
}

function papersForCluster(run, cluster) {
  if (!cluster) return [];
  const nested = Array.isArray(cluster.papers)
    ? cluster.papers.map((p) => normalizeClusterPaper(p, cluster.key)).filter(Boolean)
    : [];
  if (nested.length) return nested;

  const fromRun = (run?.papers || [])
    .map((p) => normalizeClusterPaper(p))
    .filter((p) => paperBelongsToCluster(p, cluster));
  if (fromRun.length) return fromRun;

  const byTitle = new Map(
    (run?.papers || [])
      .map((p) => normalizeClusterPaper(p))
      .filter(Boolean)
      .map((p) => [p.title, p])
  );
  return (cluster.paper_titles || [])
    .map((title) => {
      const existing = byTitle.get(String(title).trim());
      if (existing) {
        return normalizeClusterPaper({ ...existing, cluster_key: cluster.key }, cluster.key);
      }
      return normalizeClusterPaper({ title, cluster_key: cluster.key }, cluster.key);
    })
    .filter(Boolean);
}

function normalizeLiteratureRun(run) {
  if (!run || typeof run !== "object") return run;
  const clusters = Array.isArray(run.clusters)
    ? run.clusters.map((cluster) => {
        const papers = papersForCluster(run, cluster);
        return {
          ...cluster,
          answer: cluster.answer || cluster.description || "",
          rationale: cluster.rationale || cluster.similarity_basis || "",
          distinguishing_features:
            cluster.distinguishing_features || cluster.similarity_basis || "",
          paper_titles: cluster.paper_titles?.length
            ? cluster.paper_titles
            : papers.map((p) => p.title),
          papers,
        };
      })
    : [];

  const paperMap = new Map();
  for (const paper of run.papers || []) {
    const normalized = normalizeClusterPaper(paper);
    if (normalized) paperMap.set(normalized.title, normalized);
  }
  for (const cluster of clusters) {
    for (const paper of cluster.papers || []) {
      const prev = paperMap.get(paper.title) || {};
      paperMap.set(paper.title, {
        ...prev,
        ...paper,
        tldr: paper.tldr || prev.tldr || "",
        query_answer: paper.query_answer || prev.query_answer || "",
        quotes: paper.quotes?.length ? paper.quotes : prev.quotes || [],
        evidence: paper.evidence?.length ? paper.evidence : prev.evidence || [],
        cluster_key: paper.cluster_key || prev.cluster_key || cluster.key,
      });
    }
  }

  return {
    ...run,
    clusters,
    papers: [...paperMap.values()],
  };
}

function renderClusterPaperCard(paper) {
  const year = paper.year ? String(paper.year) : "";
  const href = paper.arxiv_url || paper.html_path || "#";
  const tldr = paper.tldr || paper.comprehensive_answer || "";
  const queryAnswer = paper.query_answer || paper.short_answer || "";
  const quotes = Array.isArray(paper.quotes)
    ? paper.quotes
    : (paper.evidence || []).map((text) => ({ text, why: "" }));
  const quotesHtml = quotes.length
    ? `<ul class="rw-cluster-paper-quotes">${quotes
        .filter((q) => q && (q.text || typeof q === "string"))
        .map((q) => {
          const text = typeof q === "string" ? q : q.text || "";
          const why = typeof q === "string" ? "" : q.why || "";
          return `<li><blockquote>${escapeHtml(text)}</blockquote>${
            why ? `<p class="rw-cluster-paper-quote-why">${escapeHtml(why)}</p>` : ""
          }</li>`;
        })
        .join("")}</ul>`
    : `<p class="rw-cluster-paper-muted">Цитат нет</p>`;
  return `
    <article class="rw-cluster-paper">
      <p class="rw-cluster-paper-meta">${escapeHtml([year, paper.authors].filter(Boolean).join(" · ") || "—")}</p>
      <a class="rw-cluster-paper-title" href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(paper.title || "Untitled")}</a>
      <p class="rw-cluster-paper-field"><span class="rw-cluster-paper-field-label">TLDR</span> ${escapeHtml(tldr || "—")}</p>
      <p class="rw-cluster-paper-field"><span class="rw-cluster-paper-field-label">Ответ на вопрос</span> ${escapeHtml(queryAnswer || "—")}</p>
      <div class="rw-cluster-paper-field">
        <span class="rw-cluster-paper-field-label">Цитаты</span>
        ${quotesHtml}
      </div>
    </article>`;
}

function renderClusterDetail(cluster, members, run) {
  const detail = document.getElementById("rw-cluster-detail");
  if (!detail) return;
  if (!cluster) {
    detail.innerHTML = `<p class="literature-empty">Выберите кластер слева.</p>`;
    return;
  }

  const papersHtml = members.length
    ? members.map((paper) => renderClusterPaperCard(paper)).join("")
    : `<p class="literature-empty">В этом кластере нет статей.</p>`;

  const description = cluster.answer || cluster.description || "";
  const together = cluster.rationale || cluster.distinguishing_features || "";
  detail.innerHTML = `
    <header class="rw-cluster-detail-header">
      <p class="rw-cluster-detail-kicker">${members.length} ${members.length === 1 ? "статья" : "статей"}</p>
      <h2 class="rw-cluster-detail-title">${escapeHtml(cluster.label || "Кластер")}</h2>
    </header>
    <section class="rw-cluster-section">
      <h3>Описание кластера</h3>
      <p>${escapeHtml(description || "—")}</p>
    </section>
    ${together ? `<section class="rw-cluster-section"><h3>Почему вместе</h3><p>${escapeHtml(together)}</p></section>` : ""}
    <section class="rw-cluster-section">
      <h3>Статьи</h3>
      <div class="rw-cluster-papers">${papersHtml}</div>
    </section>`;
}

function renderClusterResults(run) {
  const nav = document.getElementById("rw-cluster-nav");
  const detail = document.getElementById("rw-cluster-detail");
  const legacy = document.getElementById("literature-agent-results");
  if (legacy) legacy.innerHTML = "";
  updateClustersQuestion(run);
  updateLibrarySplitChrome(isWorkspaceSplit());

  const clusters = run?.clusters || [];
  const hasReport = Boolean(String(run?.report_markdown || "").trim());

  if (!clusters.length && !hasReport) {
    selectedClusterKeys = new Set();
    activeClusterKey = null;
    activeReadingView = READING_VIEW_RESUME;
    updateRelatedWorksSummary();
    if (nav) {
      nav.innerHTML = "";
      nav.classList.toggle("hidden", !isWorkspaceSplit());
    }
    const reportEl = document.getElementById("rw-report-markdown");
    reportEl?.classList.add("hidden");
    syncResumeClusterVenn(null);
    if (detail) {
      detail.classList.remove("hidden");
      detail.innerHTML = `<p class="literature-empty">Отчёт появится после генерации.</p>`;
    }
    return;
  }

  if (!activeClusterKey || !clusters.some((c) => c.key === activeClusterKey)) {
    activeClusterKey = clusters[0]?.key || null;
  }
  if (
    activeReadingView !== READING_VIEW_RESUME &&
    !clusters.some((c) => c.key === activeReadingView)
  ) {
    activeReadingView = hasReport ? READING_VIEW_RESUME : activeClusterKey || READING_VIEW_RESUME;
  } else if (activeReadingView === READING_VIEW_RESUME && !hasReport && activeClusterKey) {
    activeReadingView = activeClusterKey;
  } else if (!activeReadingView) {
    activeReadingView = hasReport ? READING_VIEW_RESUME : activeClusterKey || READING_VIEW_RESUME;
  }

  if (nav) {
    nav.classList.remove("hidden");
    const resumeActive = activeReadingView === READING_VIEW_RESUME ? " is-active" : "";
    const resumeRow = hasReport
      ? `
        <div class="rw-cluster-nav-row rw-cluster-nav-row--resume${resumeActive}">
          <button type="button" class="rw-cluster-nav-item rw-cluster-nav-item--resume${resumeActive}" data-reading-view="${READING_VIEW_RESUME}" aria-current="${activeReadingView === READING_VIEW_RESUME ? "true" : "false"}">
            <span class="rw-cluster-nav-copy">
              <span class="rw-cluster-nav-kicker">Общий отчёт</span>
              <span class="rw-cluster-nav-label">Total Resume</span>
            </span>
          </button>
        </div>`
      : "";

    const clusterRows = clusters
      .map((cluster, index) => {
        const members = papersForCluster(run, cluster);
        const checked = selectedClusterKeys.has(cluster.key) ? "checked" : "";
        const active = cluster.key === activeReadingView ? " is-active" : "";
        return `
          <div class="rw-cluster-nav-row${active}">
            <label class="rw-cluster-nav-check" title="Выбрать для Related Work">
              <input type="checkbox" class="cluster-select-checkbox" data-cluster-key="${escapeHtml(cluster.key)}" ${checked} />
            </label>
            <button type="button" class="rw-cluster-nav-item${active}" data-reading-view="${escapeHtml(cluster.key)}" data-cluster-key="${escapeHtml(cluster.key)}" aria-current="${cluster.key === activeReadingView ? "true" : "false"}">
              <span class="rw-cluster-nav-copy">
                <span class="rw-cluster-nav-kicker">Cluster ${index + 1}</span>
                <span class="rw-cluster-nav-label">${escapeHtml(cluster.label || "Кластер")}</span>
              </span>
              <span class="rw-cluster-nav-count">${members.length}</span>
            </button>
          </div>`;
      })
      .join("");

    nav.innerHTML = resumeRow + clusterRows;

    nav.querySelectorAll(".rw-cluster-nav-item").forEach((button) => {
      button.addEventListener("click", () => {
        showReadingView(button.getAttribute("data-reading-view") || READING_VIEW_RESUME);
      });
    });
    nav.querySelectorAll(".cluster-select-checkbox").forEach((input) => {
      input.addEventListener("change", () => {
        toggleClusterSelection(input.getAttribute("data-cluster-key"));
      });
    });
  }

  showReadingView(activeReadingView, { scrollPage: false });
  // Total Resume mounts the map via renderReportMarkdown; cluster-only views still need the card.
  if (activeReadingView !== READING_VIEW_RESUME) syncResumeClusterVenn(run);
  updateRelatedWorksSummary();
}

function renderLiteratureResults(results = [], _query = "") {
  const root = document.getElementById("literature-results");
  if (!root) return;

  literatureResults = (results || []).map(normalizePaperRecord).filter((p) => p.title && p.arxiv_url);
  updateLibraryPanelChrome();

  if (!literatureResults.length) {
    root.innerHTML = "";
    updateActionButtons();
    return;
  }

  root.innerHTML = literatureResults
    .map((paper) => {
      const checked = selectedPaperUrls.has(paper.arxiv_url);
      const checkedAttr = checked ? "checked" : "";
      const selectedClass = checked ? " is-selected" : "";
      const href = paper.arxiv_url || "#";
      return `
        <article class="rw-library-item${selectedClass}">
          <label class="rw-library-item-check" title="Выбрать">
            <input type="checkbox" class="literature-result-checkbox" data-paper-url="${escapeHtml(paper.arxiv_url)}" ${checkedAttr} />
          </label>
          <div class="rw-library-item-body">
            <p class="rw-library-item-meta">${escapeHtml(paperMetaLine(paper))}</p>
            <a class="rw-library-item-title" href="${escapeHtml(href)}" target="_blank" rel="noreferrer">${escapeHtml(paper.title)}</a>
          </div>
          <button type="button" class="rw-library-item-morph" data-paper-url="${escapeHtml(paper.arxiv_url)}" title="Морфология — разобрать логику статьи" aria-label="Морфология статьи">
            ${MORPH_ICON_SVG}
          </button>
        </article>`;
    })
    .join("");

  root.querySelectorAll(".rw-library-item-morph").forEach((btn) => {
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      openPaperMorphology(event.currentTarget?.dataset?.paperUrl || "");
    });
  });

  root.querySelectorAll(".literature-result-checkbox").forEach((input) => {
    input.addEventListener("change", (event) => {
      const url = event.currentTarget?.dataset?.paperUrl;
      if (!url) return;
      if (event.currentTarget.checked) selectedPaperUrls.add(url);
      else selectedPaperUrls.delete(url);
      const item = event.currentTarget.closest(".rw-library-item");
      item?.classList.toggle("is-selected", event.currentTarget.checked);
      updateActionButtons();
      updateMortalCombatLink();
    });
  });
  updateActionButtons();
  updateMortalCombatLink();
}

async function loadLibraryIntoSidebar({ silent = false } = {}) {
  if (!libraryExists) {
    if (!literatureResults.length) setLibraryPapers([]);
    return;
  }
  try {
    const data = await KoiApi.listLibraryPapers();
    const papers = data.papers || [];
    if (papers.length) {
      setLibraryPapers(papers);
      if (!silent) setLiteratureStatus(`Загружено ${papers.length} статей из базы.`);
    } else if (!literatureResults.length) {
      setLibraryPapers([]);
    }
  } catch (err) {
    if (!silent) setLiteratureStatus(err.message, true);
  }
}

async function findLiteraturePapers() {
  hideLibraryAddMenu();
  const limit = selectedLiteratureLimit();
  let searchQuery = composeProjectSearchQuery();
  if (!searchQuery) {
    setLiteratureStatus(
      "В project.md нет literature_keywords — добавьте ключевые слова для поиска.",
      true
    );
    showSettingsModal();
    return;
  }
  if (!selectedProjectId()) {
    setLiteratureStatus("Выберите проект в настройках.", true);
    showSettingsModal();
    return;
  }

  const findBtn = document.getElementById("rw-library-find");
  findBtn?.setAttribute("disabled", "disabled");
  showLoader("Поиск статей…");
  setLiteratureStatus("");
  try {
    if (shouldAutoTranslateQuestion()) {
      try {
        searchQuery = await translateQueryToEnglish(searchQuery, { silent: true });
      } catch {
        /* keep original keywords */
      }
    }
    const papers = await searchPapers(searchQuery, limit);
    setLibraryPapers(papers);
    if (!papers.length) {
      setLiteratureStatus("Ничего не найдено по ключевым словам проекта.", true);
    } else {
      setLiteratureStatus(`Найдено ${papers.length} статей.`);
    }
  } catch (err) {
    setLiteratureStatus(err.message, true);
  } finally {
    hideLoader();
    findBtn?.removeAttribute("disabled");
  }
}

function openLibrarySourceSettings() {
  hideLibraryAddMenu();
  showSettingsModal();
  requestAnimationFrame(() => {
    const zotero = document.getElementById("rw-settings-zotero");
    if (zotero) zotero.open = true;
    zotero?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  restoreZoteroConnectionUi(loadSettings(), { loadCollections: true });
}

function openZoteroImport() {
  hideLibraryAddMenu();
  const settings = loadSettings();
  if (settings.zoteroApiKey?.trim()) {
    openLibrarySourceSettings();
    setZoteroStatus(
      `Подключено: ${zoteroWhoLabel(settings)}. Выберите папку и нажмите «Импортировать».`
    );
    void refreshZoteroCollections({ quiet: true });
    requestAnimationFrame(() => {
      document.getElementById("rw-zotero-collection")?.focus();
    });
    return;
  }
  openLibrarySourceSettings();
  setZoteroStatus("Вставьте API Key и нажмите «Подключить».");
  requestAnimationFrame(() => {
    document.getElementById("rw-zotero-api-key")?.focus();
  });
}

function setZoteroStatus(msg, isError = false) {
  const el = document.getElementById("rw-zotero-status");
  if (!el) return;
  el.textContent = msg || "";
  el.className = "rw-settings-hint" + (isError ? " error" : msg ? " ok" : "");
}

function resetZoteroStatusDefault() {
  const el = document.getElementById("rw-zotero-status");
  if (!el) return;
  el.className = "rw-settings-hint";
  el.innerHTML =
    'Ключ: <a href="https://www.zotero.org/settings/keys" target="_blank" rel="noreferrer">zotero.org/settings/keys</a>';
}

function readZoteroCredentials() {
  const settings = loadSettings();
  return {
    user_id:
      document.getElementById("rw-zotero-user-id")?.value?.trim() ||
      settings.zoteroUserId ||
      "",
    api_key:
      document.getElementById("rw-zotero-api-key")?.value?.trim() ||
      settings.zoteroApiKey ||
      "",
  };
}

function readZoteroCollectionKey() {
  const select = document.getElementById("rw-zotero-collection");
  if (select && !select.disabled) return select.value || "";
  return loadSettings().zoteroCollectionKey || "";
}

function setZoteroImportEnabled(enabled) {
  const button = document.getElementById("rw-zotero-import");
  if (button) button.disabled = !enabled;
}

function setZoteroDisconnectVisible(visible) {
  const button = document.getElementById("rw-zotero-disconnect");
  if (button) button.hidden = !visible;
}

function setZoteroCollectionVisible(visible) {
  const field = document.getElementById("rw-zotero-collection-field");
  if (field) field.hidden = !visible;
}

function resetZoteroCollectionSelect() {
  const select = document.getElementById("rw-zotero-collection");
  if (!select) return;
  select.innerHTML = '<option value="">Вся библиотека</option>';
  select.value = "";
  select.disabled = true;
  setZoteroCollectionVisible(false);
}

function populateZoteroCollectionSelect(collections, selectedKey = "") {
  const select = document.getElementById("rw-zotero-collection");
  if (!select) return;
  const preferred = selectedKey || loadSettings().zoteroCollectionKey || "";
  select.innerHTML = "";
  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = "Вся библиотека";
  select.appendChild(allOption);
  for (const collection of collections || []) {
    const option = document.createElement("option");
    option.value = String(collection.key || "");
    option.textContent = String(collection.label || collection.name || collection.key || "");
    select.appendChild(option);
  }
  const hasPreferred = [...select.options].some((opt) => opt.value === preferred);
  select.value = hasPreferred ? preferred : "";
  select.disabled = false;
  setZoteroCollectionVisible(true);
}

function persistZoteroCollectionKey() {
  const settings = loadSettings();
  settings.zoteroCollectionKey = readZoteroCollectionKey();
  saveSettingsToStorage(settings);
}

function zoteroWhoLabel(settings = loadSettings()) {
  if (settings.zoteroUsername) return `@${settings.zoteroUsername}`;
  if (settings.zoteroUserId) return `user ${settings.zoteroUserId}`;
  return "сохранено";
}

function zoteroCollectionLabel() {
  const select = document.getElementById("rw-zotero-collection");
  if (!select || select.disabled) return "";
  const key = select.value || "";
  if (!key) return "вся библиотека";
  const option = select.selectedOptions?.[0];
  return (option?.textContent || key).trim();
}

function restoreZoteroConnectionUi(settings = loadSettings(), { loadCollections = false } = {}) {
  const hasKey = Boolean(settings.zoteroApiKey?.trim());
  setZoteroImportEnabled(hasKey);
  setZoteroDisconnectVisible(hasKey);
  updateZoteroEmptyHint();
  if (hasKey) {
    setZoteroCollectionVisible(true);
    setZoteroStatus(
      `Подключено: ${zoteroWhoLabel(settings)}. Выберите папку и нажмите «Импортировать».`
    );
    if (loadCollections) void refreshZoteroCollections({ quiet: true });
  } else {
    setZoteroDisconnectVisible(false);
    resetZoteroCollectionSelect();
  }
}

function disconnectZoteroAccount() {
  const userInput = document.getElementById("rw-zotero-user-id");
  const keyInput = document.getElementById("rw-zotero-api-key");
  if (userInput) userInput.value = "";
  if (keyInput) keyInput.value = "";
  const settings = readSettingsFromDom();
  settings.zoteroUserId = "";
  settings.zoteroApiKey = "";
  settings.zoteroUsername = "";
  settings.zoteroCollectionKey = "";
  saveSettingsToStorage(settings);
  setZoteroImportEnabled(false);
  setZoteroDisconnectVisible(false);
  resetZoteroCollectionSelect();
  updateZoteroEmptyHint();
  resetZoteroStatusDefault();
  setLiteratureStatus("Zotero отключён.");
}

async function refreshZoteroCollections({ quiet = false } = {}) {
  const { user_id, api_key } = readZoteroCredentials();
  if (!api_key) {
    resetZoteroCollectionSelect();
    return;
  }
  const select = document.getElementById("rw-zotero-collection");
  if (select) select.disabled = true;
  setZoteroCollectionVisible(true);
  try {
    const data = await KoiApi.listZoteroCollections({ api_key, user_id });
    const collections = data.collections || [];
    populateZoteroCollectionSelect(collections, loadSettings().zoteroCollectionKey || "");
    persistZoteroCollectionKey();
    if (!quiet) {
      const count = collections.length;
      setZoteroStatus(
        count
          ? `Найдено папок: ${count}. Выберите папку и нажмите «Импортировать».`
          : "Папок нет — можно импортировать всю библиотеку."
      );
    }
  } catch (err) {
    resetZoteroCollectionSelect();
    setZoteroCollectionVisible(Boolean(api_key));
    if (!quiet) setZoteroStatus(err.message, true);
  }
}

async function connectZoteroAccount() {
  const { user_id, api_key } = readZoteroCredentials();
  if (!api_key) {
    setZoteroStatus("Сначала вставьте API Key.", true);
    document.getElementById("rw-zotero-api-key")?.focus();
    return;
  }
  const connectBtn = document.getElementById("rw-zotero-connect");
  connectBtn?.setAttribute("disabled", "disabled");
  setZoteroStatus("Проверяем ключ в Zotero…");
  setZoteroImportEnabled(false);
  setZoteroDisconnectVisible(false);
  try {
    const data = await KoiApi.connectZotero({ api_key, user_id });
    const resolvedId = String(data.user_id || "").trim();
    const username = String(data.username || "").trim();
    const userInput = document.getElementById("rw-zotero-user-id");
    if (resolvedId && userInput) userInput.value = resolvedId;
    const settings = readSettingsFromDom();
    settings.zoteroUserId = resolvedId || user_id;
    settings.zoteroApiKey = api_key;
    settings.zoteroUsername = username;
    saveSettingsToStorage(settings);
    setZoteroImportEnabled(true);
    setZoteroDisconnectVisible(true);
    updateZoteroEmptyHint();
    const who = username ? `@${username}` : `user ${resolvedId}`;
    setZoteroStatus(`Подключено: ${who}. Загружаем список папок…`);
    setLiteratureStatus(`Zotero подключён (${who}).`);
    await refreshZoteroCollections({ quiet: false });
    document.getElementById("rw-zotero-collection")?.focus();
  } catch (err) {
    setZoteroImportEnabled(false);
    setZoteroDisconnectVisible(false);
    resetZoteroCollectionSelect();
    setZoteroStatus(err.message, true);
    setLiteratureStatus(err.message, true);
  } finally {
    connectBtn?.removeAttribute("disabled");
  }
}

async function importZoteroLibrary({ quiet = false } = {}) {
  const { user_id, api_key } = readZoteroCredentials();
  if (!api_key) {
    setZoteroStatus("Сначала подключите Zotero API Key.", true);
    if (!quiet) openLibrarySourceSettings();
    return;
  }
  const collection_key = readZoteroCollectionKey();
  persistZoteroCollectionKey();
  const folderLabel = zoteroCollectionLabel() || (collection_key ? collection_key : "вся библиотека");
  const importBtn = document.getElementById("rw-zotero-import");
  importBtn?.setAttribute("disabled", "disabled");
  if (!quiet) {
    setZoteroStatus(`Импорт из Zotero (${folderLabel})…`);
    showLoader(`Импорт из Zotero: ${folderLabel}`);
  } else {
    setLiteratureStatus(`Загружаем Zotero (${folderLabel})…`);
  }
  try {
    const data = await KoiApi.importZotero({
      api_key,
      user_id,
      limit: Math.max(selectedLiteratureLimit(), 50),
      collection_key,
    });
    const papers = data.papers || [];
    if (!papers.length) {
      setZoteroStatus(`В «${folderLabel}» не найдено подходящих записей.`, true);
      setLiteratureStatus("Zotero: статей не найдено.", true);
      return;
    }
    setLibraryPapers(papers);
    hideSettingsModal();
    const total = data.total_available != null ? ` (из ${data.total_available})` : "";
    setZoteroStatus(`Импортировано ${papers.length}${total} из «${folderLabel}».`);
    setLiteratureStatus(`Импортировано из Zotero (${folderLabel}): ${papers.length} статей.`);
  } catch (err) {
    setZoteroStatus(err.message, true);
    setLiteratureStatus(err.message, true);
  } finally {
    if (!quiet) hideLoader();
    setZoteroImportEnabled(Boolean(api_key));
    importBtn?.removeAttribute("disabled");
  }
}

async function maybeAutoLoadZoteroLibrary() {
  if (literatureResults.length) return;
  const settings = loadSettings();
  if (!settings.zoteroApiKey?.trim()) return;
  await importZoteroLibrary({ quiet: true });
}

function triggerCsvUpload() {
  hideLibraryAddMenu();
  const input = document.getElementById("rw-library-csv-input");
  if (!input) {
    showSettingsModal();
    return;
  }
  input.value = "";
  input.click();
}

async function handleLibraryCsvSelected(file) {
  if (!file) return;
  const settingsInput = document.getElementById("library-upload-input");
  if (settingsInput) {
    try {
      const transfer = new DataTransfer();
      transfer.items.add(file);
      settingsInput.files = transfer.files;
      updateLibraryUploadFilename();
    } catch {
      /* DataTransfer may be unavailable */
    }
  }
  showLoader("Загрузка CSV…");
  setLiteratureStatus("Загрузка CSV…");
  try {
    const data = await KoiApi.uploadLibrary(file);
    libraryExists = true;
    updateLibraryStatusHint();
    setLibraryUploadStatus(`Загружено ${data.count} статей в ${data.csv_path}.`);
    await loadLibraryIntoSidebar({ silent: true });
    setLiteratureStatus(`CSV загружен: ${data.count} статей.`);
  } catch (err) {
    setLiteratureStatus(err.message, true);
    setLibraryUploadStatus(err.message, true);
  } finally {
    hideLoader();
  }
}

let clusterVennCleanup = null;
const CLUSTER_VENN_COLLAPSE_KEY = "koi-rw-cluster-venn-collapsed";

function teardownClusterVennDiagram() {
  if (typeof clusterVennCleanup === "function") {
    try {
      clusterVennCleanup();
    } catch {
      /* ignore */
    }
  }
  clusterVennCleanup = null;
}

function isClusterVennCollapsedPreferred() {
  try {
    return sessionStorage.getItem(CLUSTER_VENN_COLLAPSE_KEY) === "1";
  } catch {
    return false;
  }
}

function setClusterVennCollapsed(host, collapsed) {
  if (!host) return;
  const body = host.querySelector(".rw-cluster-venn-body");
  const toggle = host.querySelector(".rw-cluster-venn-toggle");
  const hint = host.querySelector(".rw-cluster-venn-toggle-hint");
  host.classList.toggle("is-collapsed", Boolean(collapsed));
  if (body) body.hidden = Boolean(collapsed);
  toggle?.setAttribute("aria-expanded", collapsed ? "false" : "true");
  if (hint) hint.textContent = collapsed ? "Развернуть" : "Свернуть";
  try {
    sessionStorage.setItem(CLUSTER_VENN_COLLAPSE_KEY, collapsed ? "1" : "0");
  } catch {
    /* ignore */
  }
  if (!collapsed) {
    host.querySelector("#rw-cluster-venn-chart")?.dispatchEvent(new Event("rw-venn-reveal"));
  }
}

function bindClusterVennCollapse(host) {
  const toggle = host?.querySelector?.(".rw-cluster-venn-toggle");
  if (!toggle || toggle.dataset.bound === "1") return;
  toggle.dataset.bound = "1";
  toggle.addEventListener("click", () => {
    setClusterVennCollapsed(host, !host.classList.contains("is-collapsed"));
  });
}

function vennColorPalette() {
  const root = getComputedStyle(document.documentElement);
  const fromTheme = ["--pink", "--purple", "--cyan", "--orange", "--lime", "--peach"]
    .map((name) => root.getPropertyValue(name).trim())
    .filter(Boolean);
  return fromTheme.length
    ? fromTheme
    : ["#ff6bcb", "#9b5cff", "#3de8ff", "#ff9a5c", "#b8ff5c", "#ffb8a0"];
}

/** title → Set(clusterKey) using nested cluster papers + soft multi-membership. */
function buildPaperClusterMembership(run) {
  const membership = new Map();
  const add = (title, key) => {
    const t = String(title || "").trim();
    const k = String(key || "").trim();
    if (!t || !k) return;
    if (!membership.has(t)) membership.set(t, new Set());
    membership.get(t).add(k);
  };

  for (const cluster of run?.clusters || []) {
    const key = String(cluster?.key || "").trim();
    if (!key) continue;
    for (const paper of papersForCluster(run, cluster)) {
      add(paper.title, key);
      for (const extra of paper.cluster_keys || []) add(paper.title, extra);
    }
  }

  for (const raw of run?.papers || []) {
    const paper = normalizeClusterPaper(raw);
    if (!paper) continue;
    if (paper.primary_cluster_key) add(paper.title, paper.primary_cluster_key);
    for (const key of paper.cluster_keys || []) add(paper.title, key);
  }

  return membership;
}

function buildVennSetOverlaps(run) {
  const clusters = (run?.clusters || []).filter((c) => String(c?.key || "").trim());
  if (!clusters.length) return { areas: [], metaByKey: new Map(), membership: new Map() };

  const membership = buildPaperClusterMembership(run);
  const metaByKey = new Map();
  clusters.forEach((cluster, index) => {
    const key = String(cluster.key);
    const members = [...membership.entries()]
      .filter(([, keys]) => keys.has(key))
      .map(([title]) => title);
    metaByKey.set(key, {
      key,
      index,
      label: cluster.label || `Cluster ${index + 1}`,
      description: String(cluster.answer || cluster.description || "").trim(),
      together: String(
        cluster.rationale || cluster.distinguishing_features || cluster.similarity_basis || ""
      ).trim(),
      paperTitles: members,
      size: members.length,
    });
  });

  const keys = clusters.map((c) => String(c.key));
  const areas = [];

  for (const key of keys) {
    const meta = metaByKey.get(key);
    if (!meta?.size) continue;
    areas.push({ sets: [key], size: meta.size });
  }

  const n = keys.length;
  for (let mask = 1; mask < 1 << n; mask += 1) {
    const combo = [];
    for (let i = 0; i < n; i += 1) {
      if (mask & (1 << i)) combo.push(keys[i]);
    }
    if (combo.length < 2) continue;
    let size = 0;
    for (const [, paperKeys] of membership) {
      if (combo.every((key) => paperKeys.has(key))) size += 1;
    }
    if (size > 0) areas.push({ sets: combo, size });
  }

  return { areas, metaByKey, membership };
}

function formatVennTooltipHtml(datum, metaByKey) {
  const keys = (datum?.sets || []).map(String);
  if (!keys.length) return "";

  if (keys.length === 1) {
    const meta = metaByKey.get(keys[0]);
    if (!meta) return "";
    const desc = shortText(meta.description || meta.together, 220) || "Нет описания";
    const peers = [...metaByKey.values()]
      .filter((other) => other.key !== meta.key)
      .filter((other) =>
        meta.paperTitles.some((title) => other.paperTitles.includes(title))
      )
      .map((other) => other.label);
    const peerLine = peers.length
      ? `<p class="rw-cluster-venn-tip-meta">Пересекается с: ${escapeHtml(peers.join(", "))}</p>`
      : `<p class="rw-cluster-venn-tip-meta">Без пересечений по статьям</p>`;
    return `
      <p class="rw-cluster-venn-tip-kicker">Cluster ${meta.index + 1} · ${meta.size} ${
        meta.size === 1 ? "статья" : "статей"
      }</p>
      <p class="rw-cluster-venn-tip-title">${escapeHtml(meta.label)}</p>
      <p class="rw-cluster-venn-tip-body">${escapeHtml(desc)}</p>
      ${peerLine}`;
  }

  const labels = keys.map((key) => metaByKey.get(key)?.label || key);
  const titleSets = keys.map((key) => new Set(metaByKey.get(key)?.paperTitles || []));
  const titles = titleSets.length
    ? [...titleSets[0]].filter((title) => titleSets.every((set) => set.has(title)))
    : [];
  const list = titles
    .slice(0, 4)
    .map((t) => `<li>${escapeHtml(shortText(t, 72))}</li>`)
    .join("");
  const more =
    titles.length > 4
      ? `<p class="rw-cluster-venn-tip-meta">и ещё ${titles.length - 4}</p>`
      : "";
  return `
    <p class="rw-cluster-venn-tip-kicker">Пересечение · ${datum.size} ${
      datum.size === 1 ? "статья" : "статей"
    }</p>
    <p class="rw-cluster-venn-tip-title">${escapeHtml(labels.join(" ∩ "))}</p>
    ${list ? `<ul class="rw-cluster-venn-tip-list">${list}</ul>${more}` : ""}`;
}

function renderClusterVennLegend(metaByKey, colorByKey) {
  const items = [...metaByKey.values()];
  if (!items.length) return "";
  return `
    <ul class="rw-cluster-venn-legend" aria-label="Легенда кластеров">
      ${items
        .map((meta) => {
          const color = colorByKey.get(meta.key) || "var(--cyan)";
          return `
            <li>
              <button type="button" class="rw-cluster-venn-legend-item" data-cluster-key="${escapeHtml(
                meta.key
              )}" title="Открыть кластер">
                <span class="rw-cluster-venn-legend-swatch" style="--swatch:${escapeHtml(color)}"></span>
                <span class="rw-cluster-venn-legend-copy">
                  <span class="rw-cluster-venn-legend-label">${escapeHtml(meta.label)}</span>
                  <span class="rw-cluster-venn-legend-count">${meta.size}</span>
                </span>
              </button>
            </li>`;
        })
        .join("")}
    </ul>`;
}

function mountClusterVennDiagram(run, rootEl) {
  teardownClusterVennDiagram();
  const chartEl = rootEl?.querySelector?.("#rw-cluster-venn-chart") || rootEl;
  const tipEl = rootEl?.querySelector?.("#rw-cluster-venn-tooltip");
  const legendEl = rootEl?.querySelector?.("#rw-cluster-venn-legend");
  if (!chartEl) return;

  const d3 = globalThis.d3;
  const vennApi = globalThis.venn;
  if (!d3?.select || !vennApi?.VennDiagram) {
    chartEl.innerHTML = `<p class="literature-empty">Не удалось загрузить venn.js</p>`;
    return;
  }

  const { areas, metaByKey } = buildVennSetOverlaps(run);
  if (!areas.length) {
    chartEl.innerHTML = `<p class="literature-empty">Нет данных для диаграммы пересечений.</p>`;
    return;
  }

  const palette = vennColorPalette();
  const colorByKey = new Map(
    [...metaByKey.keys()].map((key, i) => [key, palette[i % palette.length]])
  );

  if (legendEl) {
    legendEl.innerHTML = renderClusterVennLegend(metaByKey, colorByKey);
    legendEl.querySelectorAll(".rw-cluster-venn-legend-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-cluster-key") || "";
        if (key) showReadingView(key, { scrollPage: true, scrollNav: true });
      });
    });
  }

  let drawQueued = false;
  const draw = () => {
    drawQueued = false;
    if (rootEl?.classList.contains("is-collapsed")) return;
    const width = Math.max(280, Math.floor(chartEl.clientWidth || 420));
    const height = Math.min(380, Math.max(240, Math.round(width * 0.62)));
    chartEl.innerHTML = "";

    const textFill =
      getComputedStyle(document.documentElement).getPropertyValue("--text").trim() || "#f4f4ff";
    const chart = vennApi
      .VennDiagram({
        symmetricalTextCentre: true,
        colourScheme: palette,
        textFill,
      })
      .width(width)
      .height(height);
    const selection = d3.select(chartEl).datum(areas).call(chart);

    selection
      .selectAll("path")
      .style("fill-opacity", 0.34)
      .style("stroke-width", 1.75)
      .style("stroke-opacity", 0.9)
      .style("transition", "fill-opacity 160ms ease, stroke-width 160ms ease");

    selection.selectAll("g.venn-circle path").style("fill", (d) => {
      const key = d?.sets?.[0];
      return colorByKey.get(String(key)) || palette[0];
    }).style("stroke", (d) => {
      const key = d?.sets?.[0];
      return colorByKey.get(String(key)) || palette[0];
    });

    selection.selectAll("g.venn-intersection path").style("fill", "var(--text)").style("fill-opacity", 0.08);

    selection
      .selectAll("g.venn-circle text")
      .text((d) => {
        const key = String(d?.sets?.[0] || "");
        const meta = metaByKey.get(key);
        return shortText(meta?.label || key, 22);
      })
      .style("fill", "var(--text)")
      .style("font-size", "11px")
      .style("font-family", "Outfit, sans-serif")
      .style("font-weight", "600")
      .style("pointer-events", "none");

    const hideTip = () => {
      tipEl?.classList.add("hidden");
      tipEl && (tipEl.innerHTML = "");
      rootEl?.querySelectorAll(".rw-cluster-venn-legend-item.is-hot").forEach((el) => {
        el.classList.remove("is-hot");
      });
    };

    const showTip = (event, datum) => {
      if (!tipEl) return;
      const accent =
        datum?.sets?.length === 1
          ? colorByKey.get(String(datum.sets[0])) || palette[0]
          : "var(--cyan)";
      tipEl.style.setProperty("--tip-accent", accent);
      tipEl.innerHTML = formatVennTooltipHtml(datum, metaByKey);
      tipEl.classList.remove("hidden");
      const host = tipEl.parentElement || chartEl;
      const hostRect = host.getBoundingClientRect();
      const tipRect = tipEl.getBoundingClientRect();
      let left = event.clientX - hostRect.left + 14;
      let top = event.clientY - hostRect.top + 14;
      if (left + tipRect.width > hostRect.width - 8) {
        left = Math.max(8, hostRect.width - tipRect.width - 8);
      }
      if (top + tipRect.height > hostRect.height - 8) {
        top = Math.max(8, event.clientY - hostRect.top - tipRect.height - 12);
      }
      tipEl.style.left = `${left}px`;
      tipEl.style.top = `${top}px`;

      rootEl?.querySelectorAll(".rw-cluster-venn-legend-item").forEach((el) => {
        const key = el.getAttribute("data-cluster-key") || "";
        el.classList.toggle("is-hot", (datum?.sets || []).map(String).includes(key));
      });
    };

    selection
      .selectAll("g")
      .style("cursor", (d) => (d?.sets?.length === 1 ? "pointer" : "default"))
      .on("mouseover", function (event, datum) {
        vennApi.sortAreas?.(selection, datum);
        d3.select(this).select("path").style("fill-opacity", 0.62).style("stroke-width", 2.6);
        showTip(event, datum);
      })
      .on("mousemove", (event, datum) => showTip(event, datum))
      .on("mouseleave", function () {
        d3.select(this)
          .select("path")
          .style("fill-opacity", (d) => (d?.sets?.length > 1 ? 0.08 : 0.34))
          .style("stroke-width", 1.75);
        hideTip();
      })
      .on("click", (_event, datum) => {
        if (datum?.sets?.length !== 1) return;
        const key = String(datum.sets[0] || "");
        if (!key) return;
        showReadingView(key, { scrollPage: true, scrollNav: true });
      });
  };

  const queueDraw = () => {
    if (drawQueued) return;
    drawQueued = true;
    window.requestAnimationFrame(draw);
  };

  queueDraw();
  const onReveal = () => queueDraw();
  chartEl.addEventListener("rw-venn-reveal", onReveal);
  const ro =
    typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(() => queueDraw())
      : null;
  ro?.observe(chartEl);
  const onTheme = () => queueDraw();
  window.addEventListener("koi-theme-change", onTheme);

  clusterVennCleanup = () => {
    ro?.disconnect();
    chartEl.removeEventListener("rw-venn-reveal", onReveal);
    window.removeEventListener("koi-theme-change", onTheme);
    tipEl?.classList.add("hidden");
    chartEl.innerHTML = "";
    if (legendEl) legendEl.innerHTML = "";
  };
}

function syncResumeClusterVenn(run = latestPaperAnswerRun) {
  const slot = document.getElementById("rw-cluster-venn-slot");
  if (!slot) return;

  const clusters = run?.clusters || [];
  if (!clusters.length) {
    teardownClusterVennDiagram();
    slot.innerHTML = "";
    slot.classList.add("hidden");
    return;
  }

  const { areas, metaByKey } = buildVennSetOverlaps(run);
  const overlapCount = areas.filter((a) => (a.sets || []).length >= 2).length;
  const paperCount = new Set(
    [...metaByKey.values()].flatMap((meta) => meta.paperTitles || [])
  ).size;
  const collapsed = isClusterVennCollapsedPreferred();

  slot.classList.remove("hidden");
  slot.innerHTML = `
    <section class="rw-cluster-venn rw-resume-card${collapsed ? " is-collapsed" : ""}" aria-label="Пересечения кластеров по статьям">
      <button type="button" class="rw-cluster-venn-toggle" aria-expanded="${
        collapsed ? "false" : "true"
      }" aria-controls="rw-cluster-venn-body">
        <span class="rw-cluster-venn-toggle-main">
          <span class="rw-cluster-venn-toggle-chevron" aria-hidden="true">
            <svg viewBox="0 0 16 16" width="14" height="14"><path fill="currentColor" d="M6 3.2 10.8 8 6 12.8l-.9-.9L9 8 5.1 4.1z"/></svg>
          </span>
          <span class="rw-cluster-venn-toggle-copy">
            <span class="rw-cluster-venn-kicker">Карта кластеров</span>
            <span class="rw-cluster-venn-title">Пересечения по статьям</span>
          </span>
          <span class="rw-cluster-venn-badge" title="Кластеры · статьи · пересечения">
            <span>${clusters.length} кл</span>
            <span class="rw-cluster-venn-badge-sep">·</span>
            <span>${paperCount} ст</span>
            <span class="rw-cluster-venn-badge-sep">·</span>
            <span>${overlapCount} ∩</span>
          </span>
        </span>
        <span class="rw-cluster-venn-toggle-hint">${collapsed ? "Развернуть" : "Свернуть"}</span>
      </button>
      <div class="rw-cluster-venn-body" id="rw-cluster-venn-body"${collapsed ? " hidden" : ""}>
        <p class="rw-cluster-venn-hint">Наведите на круг — краткое описание. Клик по кругу или легенде открывает кластер.</p>
        <div class="rw-cluster-venn-stage">
          <div class="rw-cluster-venn-glow" aria-hidden="true"></div>
          <div class="rw-cluster-venn-chart" id="rw-cluster-venn-chart"></div>
          <div class="rw-cluster-venn-tooltip hidden" id="rw-cluster-venn-tooltip" role="tooltip"></div>
        </div>
        <div id="rw-cluster-venn-legend"></div>
      </div>
    </section>`;

  const host = slot.querySelector(".rw-cluster-venn");
  bindClusterVennCollapse(host);
  requestAnimationFrame(() => mountClusterVennDiagram(run, host));
}

function renderReportMarkdown(run = latestPaperAnswerRun) {
  const el = document.getElementById("rw-report-markdown");
  if (!el) return;
  const md = String(run?.report_markdown || "").trim();
  if (!md) {
    el.innerHTML = "";
    el.classList.remove("markdown-preview");
    el.classList.add("hidden");
    syncResumeClusterVenn(run);
    return;
  }

  el.classList.add("markdown-preview");
  el.innerHTML = `
    <header class="rw-cluster-detail-header">
      <p class="rw-cluster-detail-kicker">Общий отчёт</p>
      <h2 class="rw-cluster-detail-title">Total Resume</h2>
    </header>
    ${renderMarkdown(md, { collapsibleSections: false })}`;
  // Visibility is owned by showReadingView — only reveal when that view is active.
  if (activeReadingView === READING_VIEW_RESUME) el.classList.remove("hidden");
  else el.classList.add("hidden");

  syncResumeClusterVenn(run);
}

function literatureRunId(run) {
  return String(run?.run_id || run?.query_hash || "").trim();
}

function isLiteratureRunStaged(run) {
  const status = String(run?.status || "").trim().toLowerCase();
  if (status === "ready") return false;
  if (Number(run?.n_clusters) > 0) return false;
  if (Array.isArray(run?.clusters) && run.clusters.length > 0) return false;
  // History rows always store a report path placeholder — only real markdown counts.
  const report = String(run?.report_markdown || "").trim();
  if (report && !/^literature\/[^/\s]+\/report\.md$/i.test(report)) return false;
  return status === "staged";
}

function resetCancelledLiteratureRunUi() {
  stopLiteratureClusterPoll();
  hideClusterPromptModal();
  literatureClusterPendingHash = "";
  literatureClusterPrompt = "";
  latestPaperAnswerRun = null;
  selectedClusterKeys = new Set();
  activeClusterKey = null;
  activeReadingView = READING_VIEW_RESUME;
  teardownClusterVennDiagram();
  const clusterRoot = document.getElementById("literature-agent-results");
  if (clusterRoot) clusterRoot.innerHTML = "";
  const reportEl = document.getElementById("rw-report-markdown");
  if (reportEl) {
    reportEl.innerHTML = "";
    reportEl.classList.add("hidden");
  }
  const vennSlot = document.getElementById("rw-cluster-venn-slot");
  if (vennSlot) {
    vennSlot.innerHTML = "";
    vennSlot.classList.add("hidden");
  }
  const detail = document.getElementById("rw-cluster-detail");
  if (detail) {
    detail.innerHTML = "";
    detail.classList.add("hidden");
  }
  document.getElementById("rw-related-pane")?.classList.add("hidden");
  updateClustersQuestion(null);
  setWorkspaceSplit(false);
}

async function cancelLiteratureClusterRun(runId = "") {
  const projectId = selectedProjectId();
  const targetId =
    String(runId || "").trim() ||
    literatureRunId(latestPaperAnswerRun) ||
    String(literatureClusterPendingHash || "").trim();
  if (!projectId || !targetId) {
    setLiteratureStatus("Нет обзора для отмены.", true);
    return;
  }
  if (!confirm("Отменить обзор и удалить подготовленный промпт?")) return;
  try {
    await KoiApi.deleteLiteratureRun(projectId, targetId);
    const wasActive =
      literatureRunId(latestPaperAnswerRun) === targetId ||
      String(literatureClusterPendingHash || "").trim() === targetId;
    if (wasActive) resetCancelledLiteratureRunUi();
    await refreshLiteratureHistory();
    setLiteratureStatus("Обзор отменён.");
  } catch (err) {
    setLiteratureStatus(err.message || "Не удалось отменить обзор.", true);
  }
}

function renderLiteratureHistory(runs = []) {
  const root = document.getElementById("rw-history-list");
  if (!root) return;
  if (!runs.length) {
    root.innerHTML = `<p class="literature-empty">Пока нет сохранённых анализов.</p>`;
    return;
  }
  const activeId = literatureRunId(latestPaperAnswerRun);
  root.innerHTML = runs
    .map((run) => {
      const runId = escapeHtml(literatureRunId(run));
      const question = escapeHtml(shortText(run.question || "Без вопроса", 90));
      const staged = isLiteratureRunStaged(run);
      const metaParts = [
        `${run.count || 0} статей`,
        String(run.created_at || "").replace("T", " ").replace("Z", ""),
      ];
      if (staged) metaParts.unshift("ожидает агента");
      const meta = escapeHtml(metaParts.filter(Boolean).join(" · "));
      const active = literatureRunId(run) === activeId ? " is-active" : "";
      const cancelBtn = staged
        ? `<button type="button" class="btn btn-small btn-danger rw-history-cancel" data-cancel-run-id="${runId}" title="Отменить обзор">✕</button>`
        : "";
      return `
        <div class="rw-history-row">
          <button type="button" class="rw-history-item${active}" data-run-id="${runId}">
            <span class="rw-history-item-title">${question}</span>
            <span class="rw-history-item-meta">${meta}</span>
          </button>
          ${cancelBtn}
        </div>`;
    })
    .join("");
  root.querySelectorAll("[data-run-id]").forEach((button) => {
    button.addEventListener("click", () => {
      void openLiteratureHistoryRun(button.getAttribute("data-run-id"));
    });
  });
  root.querySelectorAll("[data-cancel-run-id]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      void cancelLiteratureClusterRun(button.getAttribute("data-cancel-run-id"));
    });
  });
}

async function refreshLiteratureHistory() {
  const projectId = selectedProjectId();
  if (!projectId) {
    renderLiteratureHistory([]);
    return;
  }
  try {
    const data = await KoiApi.listLiteratureRuns(projectId);
    renderLiteratureHistory(data.runs || []);
  } catch {
    renderLiteratureHistory([]);
  }
}

async function openLiteratureHistoryRun(runId) {
  const projectId = selectedProjectId();
  if (!projectId || !runId) return;
  if (isHistoryView()) setHistoryView(false);
  showLoader("Открываем анализ…");
  try {
    const run = normalizeLiteratureRun(await KoiApi.getLiteratureRun(projectId, runId));
    latestPaperAnswerRun = run;
    selectedClusterKeys = new Set((run.clusters || []).map((c) => c.key));
    activeReadingView = String(run.report_markdown || "").trim() ? READING_VIEW_RESUME : (run.clusters?.[0]?.key || READING_VIEW_RESUME);
    activeClusterKey = run.clusters?.[0]?.key || null;
    setWorkspaceSplit(true);
    renderRunPapersSidebar(run.papers || []);
    if (run.report_markdown || (run.clusters || []).length) {
      setGeneratingMode(false);
      renderClusterResults(run);
      renderReportMarkdown(run);
      if (run.related_work_markdown) {
        document.getElementById("rw-related-pane")?.classList.remove("hidden");
        applyRelatedWorkResult(String(run.related_work_markdown), {
          status: "answered",
          source: "orchestrator",
        });
      }
      setLiteratureStatus(
        run.clusters?.length ? `Готово (${run.clusters.length} кластеров).` : "Готово."
      );
    } else {
      literatureClusterPendingHash = literatureRunId(run) || runId;
      literatureClusterPrompt = String(run.prompt || run.cursor_message || literatureClusterPrompt || "").trim();
      updateClustersQuestion(run);
      setGeneratingMode(true, "Агент работает — ждём report.md…");
      startLiteratureClusterPoll(projectId, literatureClusterPendingHash);
      setLiteratureStatus("Ожидаем отчёт агента…");
    }
    renderLiteratureHistory(
      (await KoiApi.listLiteratureRuns(projectId).catch(() => ({ runs: [] }))).runs || []
    );
  } catch (err) {
    setLiteratureStatus(err.message, true);
  } finally {
    if (!workspaceGenerating) hideLoader();
  }
}

async function onLiteratureSearchSubmit(e) {
  e.preventDefault();
  const button = document.getElementById("literature-search-button");
  const limit = selectedLiteratureLimit();
  const projectId = selectedProjectId();
  let searchQuery = composeProjectSearchQuery();
  let clusterQuestion = composeClusterQuestion();
  let searchCompleted = false;

  if (!clusterQuestion) {
    setLiteratureStatus("Введите исследовательный вопрос — по нему сгруппируем статьи.", true);
    return;
  }
  if (!projectId) {
    setLiteratureStatus("Выберите проект в настройках (иконка шестерёнки).", true);
    showSettingsModal();
    return;
  }

  button?.setAttribute("disabled", "disabled");
  showLoader("Подготовка…");
  setLiteratureStatus("");

  try {
    let papersForAgent = [];
    let searchQueryTranslated = false;
    const selected = getSelectedResults();
    if (literatureResults.length) {
      papersForAgent = (selected.length ? selected : literatureResults).map(normalizePaperRecord);
      searchCompleted = true;
    } else {
      if (!searchQuery) {
        setLiteratureStatus(
          "Нет статей слева и нет literature_keywords. Добавьте литературу или ключевые слова.",
          true
        );
        showSettingsModal();
        return;
      }
      if (shouldAutoTranslateQuestion()) {
        showLoader("Перевод на английский…");
        try {
          searchQuery = await translateQueryToEnglish(searchQuery, { silent: true });
        } catch {
          /* keep original */
        }
        try {
          clusterQuestion = await translateQueryToEnglish(clusterQuestion, { silent: true });
          searchQueryTranslated = true;
        } catch {
          /* keep original */
        }
      }
      showLoader("Поиск релевантных статей по ключевым словам проекта…");
      const papers = await searchPapers(searchQuery, limit);
      searchCompleted = true;
      if (!papers.length) {
        setWorkspaceSplit(false);
        setLibraryPapers([]);
        const mode = getSearchMode();
        setLiteratureStatus(
          mode === "internet" || mode === "both"
            ? "По ключевым словам проекта ничего не найдено на arXiv. Проверьте literature_keywords в project.md."
            : "Статьи не найдены. В настройках выберите режим «Интернет (arXiv)» или загрузите CSV.",
          true
        );
        return;
      }
      setLibraryPapers(papers);
      papersForAgent = literatureResults.slice();
    }

    if (shouldAutoTranslateQuestion() && !searchQueryTranslated) {
      showLoader("Перевод на английский…");
      try {
        clusterQuestion = await translateQueryToEnglish(clusterQuestion, { silent: true });
      } catch {
        /* keep original */
      }
    }

    setLiteratureStatus(`Готовим промпт для ${papersForAgent.length} статей…`);
    showLoader("Ставим выбранные статьи и собираем промпт…");
    const staged = await KoiApi.stageLiteratureCluster(projectId, {
      question: clusterQuestion,
      papers: papersForAgent,
    });
    latestPaperAnswerRun = {
      run_id: staged.run_id || staged.query_hash,
      query_hash: staged.query_hash,
      question: clusterQuestion,
      papers: papersForAgent,
      clusters: [],
      count: staged.count || papersForAgent.length,
      status: "staged",
    };
    hideKoiLoader("rw-search-loader");
    setWorkspaceSplit(true);
    renderRunPapersSidebar(papersForAgent);
    updateClustersQuestion(latestPaperAnswerRun);
    showClusterPromptModal(staged.prompt || staged.cursor_message || "");
    setGeneratingMode(true, "Ждём агента в Cursor…");
    setLiteratureStatus(
      `Промпт готов (${staged.count || papersForAgent.length} статей). Вставьте в чат Cursor — страница дождётся report.md.`
    );
    await refreshLiteratureHistory();
    startLiteratureClusterPoll(projectId, staged.run_id || staged.query_hash);
  } catch (err) {
    if (searchCompleted && literatureResults.length) {
      setWorkspaceSplit(true);
      renderLiteratureResults(literatureResults);
      const clusterRoot = document.getElementById("literature-agent-results");
      if (clusterRoot) {
        clusterRoot.innerHTML = `<p class="literature-empty">Промпт не собран: ${escapeHtml(err.message)}</p>`;
      }
      setLiteratureStatus(
        `Найдено ${literatureResults.length} статей. Не удалось собрать промпт: ${err.message}`,
        true
      );
    } else {
      setWorkspaceSplit(false);
      setLiteratureStatus(err.message, true);
    }
  } finally {
    if (!workspaceGenerating) hideLoader();
    button?.removeAttribute("disabled");
  }
}

function stopLiteratureClusterPoll() {
  if (literatureClusterPollTimer) {
    clearInterval(literatureClusterPollTimer);
    literatureClusterPollTimer = null;
  }
}

function applyLiteratureClusterRun(run) {
  if (!run?.report_markdown && !(run?.clusters || []).length) return false;
  latestPaperAnswerRun = normalizeLiteratureRun(run);
  selectedClusterKeys = new Set((latestPaperAnswerRun.clusters || []).map((c) => c.key));
  activeReadingView = String(latestPaperAnswerRun.report_markdown || "").trim()
    ? READING_VIEW_RESUME
    : latestPaperAnswerRun.clusters?.[0]?.key || READING_VIEW_RESUME;
  activeClusterKey = latestPaperAnswerRun.clusters?.[0]?.key || null;
  setWorkspaceSplit(true);
  setGeneratingMode(false);
  renderRunPapersSidebar(latestPaperAnswerRun.papers || []);
  renderClusterResults(latestPaperAnswerRun);
  renderReportMarkdown(latestPaperAnswerRun);
  if (latestPaperAnswerRun.related_work_markdown) {
    const relatedPane = document.getElementById("rw-related-pane");
    relatedPane?.classList.remove("hidden");
    applyRelatedWorkResult(String(latestPaperAnswerRun.related_work_markdown), {
      status: "answered",
      source: "orchestrator",
    });
  }
  return true;
}

async function pollLiteratureClusterOnce(projectId, runId) {
  if (!projectId || !runId) return;
  try {
    const run = await KoiApi.getLiteratureRun(projectId, runId);
    if (!run?.report_markdown) {
      setGeneratingMode(true, "Агент работает — ждём report.md…");
      return;
    }
    stopLiteratureClusterPoll();
    applyLiteratureClusterRun(run);
    await refreshLiteratureHistory();
    const clusterCount = run.clusters?.length || 0;
    setLiteratureStatus(clusterCount ? `Готово (${clusterCount} кластеров).` : "Готово.");
  } catch {
    /* still staged / not ready */
  }
}

function startLiteratureClusterPoll(projectId, runId) {
  stopLiteratureClusterPoll();
  literatureClusterPendingHash = String(runId || "");
  if (!projectId || !literatureClusterPendingHash) return;
  setWorkspaceSplit(true);
  setGeneratingMode(true, "Ждём агента в Cursor…");
  void pollLiteratureClusterOnce(projectId, literatureClusterPendingHash);
  literatureClusterPollTimer = setInterval(() => {
    void pollLiteratureClusterOnce(projectId, literatureClusterPendingHash);
  }, LITERATURE_CLUSTER_POLL_MS);
}

function showClusterPromptModal(promptText) {
  const message = String(promptText || "").trim();
  literatureClusterPrompt = message;
  showPromptDock(message);
  const modal = document.getElementById("literature-cluster-prompt-modal");
  const pre = document.getElementById("literature-cluster-prompt-text");
  if (pre) pre.textContent = message;
  if (!modal) {
    void copyRelatedWorkCursorMessage(message, null);
    return;
  }
  activeClusterPromptModal = modal;
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
  void copyRelatedWorkCursorMessage(
    message,
    document.getElementById("literature-cluster-prompt-copy-status")
  );
}

function hideClusterPromptModal() {
  const modal = activeClusterPromptModal || document.getElementById("literature-cluster-prompt-modal");
  if (!modal) return;
  modal.classList.add("hidden");
  modal.setAttribute("aria-hidden", "true");
  if (activeClusterPromptModal === modal) activeClusterPromptModal = null;
  if (!activeClusterModal && !activeSettingsModal && !activeContextModal && !activeRelatedInboxModal) {
    document.body.classList.remove("modal-open");
  }
  if (workspaceGenerating) syncPromptDock();
}

function saveSettingsFromModal() {
  const settings = readSettingsFromDom();
  saveSettingsToStorage(settings);
  hideSettingsModal();
  setLiteratureStatus("Настройки сохранены.");
}

function bindLiteratureUiEvents() {
  document.getElementById("btn-rw-settings")?.addEventListener("click", showSettingsModal);
  document.getElementById("rw-settings-save")?.addEventListener("click", saveSettingsFromModal);
  document.querySelectorAll('input[name="rw-search-mode"]').forEach((input) => {
    input.addEventListener("change", () => updateSettingsSourceUi());
  });
  document.getElementById("literature-search-form")?.addEventListener("submit", onLiteratureSearchSubmit);
  document.getElementById("rw-open-history")?.addEventListener("click", (event) => {
    event.preventDefault();
    setHistoryView(true);
  });
  document.getElementById("rw-history-back")?.addEventListener("click", (event) => {
    event.preventDefault();
    setHistoryView(false);
  });
  document.getElementById("rw-back-to-collection")?.addEventListener("click", () => {
    stopLiteratureClusterPoll();
    setWorkspaceSplit(false);
  });
  document.getElementById("rw-prompt-dock-copy")?.addEventListener("click", () => {
    void copyRelatedWorkCursorMessage(
      literatureClusterPrompt || document.getElementById("rw-prompt-dock-text")?.textContent || "",
      document.getElementById("rw-prompt-dock-status")
    );
  });
  document.getElementById("rw-prompt-dock-cancel")?.addEventListener("click", () => {
    void cancelLiteratureClusterRun();
  });
  document.getElementById("literature-cluster-prompt-cancel")?.addEventListener("click", () => {
    void cancelLiteratureClusterRun();
  });
  document.getElementById("rw-library-find")?.addEventListener("click", () => void findLiteraturePapers());
  document.getElementById("rw-library-zotero")?.addEventListener("click", openZoteroImport);
  document.getElementById("rw-library-switch-source")?.addEventListener("click", openLibrarySourceSettings);
  document.getElementById("rw-zotero-connect")?.addEventListener("click", () => void connectZoteroAccount());
  document.getElementById("rw-zotero-import")?.addEventListener("click", () => void importZoteroLibrary());
  document.getElementById("rw-zotero-disconnect")?.addEventListener("click", disconnectZoteroAccount);
  document.getElementById("rw-zotero-collection")?.addEventListener("change", () => {
    persistZoteroCollectionKey();
  });
  document.getElementById("rw-zotero-api-key")?.addEventListener("input", () => {
    const hasKey = Boolean(document.getElementById("rw-zotero-api-key")?.value?.trim());
    setZoteroImportEnabled(false);
    setZoteroDisconnectVisible(hasKey);
    resetZoteroCollectionSelect();
  });
  document.getElementById("rw-library-csv")?.addEventListener("click", triggerCsvUpload);
  document.getElementById("rw-library-csv-input")?.addEventListener("change", (event) => {
    const file = event.target?.files?.[0];
    void handleLibraryCsvSelected(file);
  });
  document.getElementById("rw-library-add")?.addEventListener("click", toggleLibraryAddMenu);
  document.getElementById("rw-library-add-menu")?.addEventListener("click", (event) => {
    const source = event.target?.closest("[data-library-source]")?.getAttribute("data-library-source");
    if (source === "find") void findLiteraturePapers();
    else if (source === "zotero") openZoteroImport();
    else if (source === "csv") triggerCsvUpload();
  });
  document.getElementById("literature-project-select")?.addEventListener("change", (event) => {
    const select = event.target;
    const title = select.selectedOptions?.[0]?.textContent?.trim() || "";
    updateProjectBanner(title, select.value);
    void loadProjectContext(select.value);
    void loadLibraryIntoSidebar({ silent: true }).then(() => maybeAutoLoadZoteroLibrary());
    void refreshLiteratureHistory();
    void restoreRelatedWorkOnLoad();
  });
  document.getElementById("literature-open-context-modal")?.addEventListener("click", showContextModal);
  document.getElementById("literature-clear-context")?.addEventListener("click", clearProjectContextSelection);
  document.getElementById("literature-context-modal-clear")?.addEventListener("click", clearProjectContextSelection);
  document.getElementById("literature-select-all")?.addEventListener("click", selectAllResults);
  document.getElementById("literature-clear-selection")?.addEventListener("click", clearSelectedResults);
  document.getElementById("library-upload-input")?.addEventListener("change", () => {
    updateLibraryUploadFilename();
    const file = document.getElementById("library-upload-input")?.files?.[0];
    setLibraryUploadStatus(file ? "Готово к загрузке." : "");
  });
  document.getElementById("library-upload-submit")?.addEventListener("click", () => void uploadLibraryFile());
  document.getElementById("library-agent-bootstrap-submit")?.addEventListener("click", () => void bootstrapLibraryFromAgent());
  document.getElementById("rw-inbox-indicator")?.addEventListener("click", () => {
    if (!inboxIsReady()) showLiteratureInboxSetup();
  });
  document.getElementById("rw-inbox-indicator")?.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && !inboxIsReady()) {
      e.preventDefault();
      showLiteratureInboxSetup();
    }
  });
  document.getElementById("related-works-generate")?.addEventListener("click", () => void generateRelatedWorks());
  document.getElementById("rw-related-toggle")?.addEventListener("click", () => toggleRelatedPaneCollapsed());
  document.getElementById("rw-related-show-message")?.addEventListener("click", () => {
    const message = lastRelatedWorkInboxMessage || lastRelatedWorkCursorMessage;
    if (message) {
      showRelatedInboxModal(message);
      return;
    }
    const itemId = activeRelatedWorkItemId;
    if (itemId) {
      void KoiApi.getRelatedWorkItem(itemId).then((item) => {
        showRelatedInboxModal(composeRelatedWorkInboxMessage(item));
      });
    }
  });
  document.getElementById("rw-inbox-message-copy")?.addEventListener("click", () => {
    void copyRelatedWorkInboxMessage(document.getElementById("rw-inbox-message-status"));
  });
  document.getElementById("rw-inbox-mark-configured")?.addEventListener("click", () => {
    void markInboxConfigured().then((operational) => {
      updateRelatedWorkInboxMessage("");
      const status = document.getElementById("rw-inbox-message-status");
      if (operational) {
        setRelatedWorksStatus("Literature Inbox готов — watcher запущен.", false);
        if (status) status.textContent = "Готово. Related Work идёт в очередь автоматически.";
      } else {
        setRelatedWorksStatus("Inbox отмечен, но watcher не запущен — см. инструкцию выше.", true);
        if (status) {
          status.textContent =
            "Сохранено. Запустите ./scripts/koi-serve.sh start и loop в Cursor — зелёный индикатор появится сам.";
        }
      }
    });
  });
  document.getElementById("rw-inbox-reset-configured")?.addEventListener("click", () => {
    void restartLiteratureInboxSetup();
  });
  document.getElementById("rw-inbox-restart")?.addEventListener("click", () => {
    void restartLiteratureInboxSetup();
  });
  document.getElementById("rw-related-waiting-copy")?.addEventListener("click", () => {
    const message = lastRelatedWorkInboxMessage || lastRelatedWorkCursorMessage;
    if (message) {
      showRelatedInboxModal(message);
      return;
    }
    void copyRelatedWorkInboxMessage(document.getElementById("rw-inbox-message-status"));
  });
  document.getElementById("rw-related-inbox-copy")?.addEventListener("click", () => {
    void copyRelatedWorkCursorMessage(
      lastRelatedWorkCursorMessage || lastRelatedWorkInboxMessage,
      document.getElementById("rw-related-inbox-copy-status")
    );
  });
  document.querySelectorAll("[data-close='rw-related-inbox-modal']").forEach((el) => {
    el.addEventListener("click", hideRelatedInboxModal);
  });
  document.getElementById("literature-cluster-prompt-copy")?.addEventListener("click", () => {
    void copyRelatedWorkCursorMessage(
      literatureClusterPrompt,
      document.getElementById("literature-cluster-prompt-copy-status")
    );
  });
  document.querySelectorAll("[data-close='literature-cluster-prompt-modal']").forEach((el) => {
    el.addEventListener("click", hideClusterPromptModal);
  });

  document.querySelectorAll("[data-close='cluster-modal']").forEach((el) => {
    el.addEventListener("click", hideClusterModal);
  });
  document.querySelectorAll("[data-close='rw-settings-modal']").forEach((el) => {
    el.addEventListener("click", hideSettingsModal);
  });
  document.querySelectorAll("[data-close='literature-context-modal']").forEach((el) => {
    el.addEventListener("click", hideContextModal);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    hideClusterModal();
    hideSettingsModal();
    hideContextModal();
    hideRelatedInboxModal();
    hideClusterPromptModal();
  });
}

async function init() {
  initTheme();
  initTaglineRotation();
  applySettingsToDom();
  setWorkspaceSplit(false);
  bindLiteratureUiEvents();
  updateLibraryUploadFilename();
  renderProjectContextSummary();
  updateRelatedWorksSummary();

  try {
    await loadProjectOptions();
    await refreshLibraryStatus();
    await refreshAppSettings();
    await loadProjectContext(selectedProjectId());
    await loadLibraryIntoSidebar({ silent: true });
    void maybeAutoLoadZoteroLibrary();
    await refreshLiteratureHistory();
    await restoreRelatedWorkOnLoad();
  } catch (err) {
    setLiteratureStatus(`Ошибка загрузки: ${err.message}`, true);
  }
}

init().catch((err) => {
  console.error(err);
  setLiteratureStatus(`Ошибка: ${err.message}`, true);
});
