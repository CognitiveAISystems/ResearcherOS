/** API base URL: same port via /api proxy (koi_web_proxy.py), else direct :8010. */
export function apiBase() {
  if (typeof window !== "undefined" && window.__KOI_API_BASE__) {
    return new URL(String(window.__KOI_API_BASE__), window.location.origin)
      .toString()
      .replace(/\/$/, "");
  }
  if (typeof window !== "undefined" && window.__HUB__) {
    return window.location.origin;
  }
  if (typeof window !== "undefined" && window.researchOSDesktop) {
    return `${window.location.origin}/api`;
  }
  if (typeof window === "undefined" || !window.location?.hostname) {
    return "http://127.0.0.1:8010";
  }
  const { protocol, hostname, port } = window.location;
  if (port === "8080" || port === "" || port === "80") {
    return `${protocol}//${hostname}${port ? `:${port}` : ""}/api`;
  }
  return `${protocol}//${hostname}:8010`;
}

export const API_BASE = apiBase();

/** Unlisted Hub share links use ``?token=`` — forward it on every API call. */
function hubShareToken() {
  if (typeof window === "undefined" || !window.__HUB__) return "";
  try {
    return new URLSearchParams(window.location.search).get("token") || "";
  } catch {
    return "";
  }
}

function withHubShareToken(path) {
  const token = hubShareToken();
  if (!token) return path;
  const join = String(path).includes("?") ? "&" : "?";
  return `${path}${join}token=${encodeURIComponent(token)}`;
}

/** GET, возвращающий сырой текст (markdown базы знаний). */
async function apiText(path, options = {}) {
  const res = await fetch(`${apiBase()}${withHubShareToken(path)}`, {
    cache: "no-store",
    credentials: "same-origin",
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.text();
}

async function api(path, options = {}) {
  const res = await fetch(`${apiBase()}${withHubShareToken(path)}`, {
    cache: "no-store",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = err.detail || res.statusText;
    if (res.status === 404 && String(path).includes("/review-agent")) {
      throw new Error(
        "Review Agent API route was not found. Restart KOI so the backend picks up the new endpoint."
      );
    }
    if (res.status === 405 && String(path).includes("/literature/")) {
      throw new Error(
        "Cancel API is missing. Restart KOI (./scripts/koi-serve.sh restart) and hard-refresh the page."
      );
    }
    throw new Error(typeof detail === "string" ? detail : res.statusText);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const KoiApi = {
  health: () => api("/health"),
  translateToEnglish: (text) =>
    api("/agent/translate-to-english", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),
  libraryStatus: () => api("/library/status"),
  listLibraryPapers: (limit) =>
    api(limit ? `/library/papers?limit=${encodeURIComponent(limit)}` : "/library/papers"),
  connectZotero: ({ api_key, user_id = "" } = {}) =>
    api("/library/zotero/connect", {
      method: "POST",
      body: JSON.stringify({ api_key, user_id: user_id || null }),
    }),
  listZoteroCollections: ({ api_key, user_id = "" } = {}) =>
    api("/library/zotero/collections", {
      method: "POST",
      body: JSON.stringify({ api_key, user_id: user_id || null }),
    }),
  importZotero: ({ api_key, user_id = "", limit = 50, collection_key = "" } = {}) =>
    api("/library/zotero/import", {
      method: "POST",
      body: JSON.stringify({
        api_key,
        user_id: user_id || null,
        limit,
        collection_key: collection_key || null,
      }),
    }),
  searchLibrary: (query, limit = 10) =>
    api("/library/search", {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    }),
  searchInternet: (query, limit = 10) =>
    api("/library/search-internet", {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    }),
  discoverLibrary: (query, limit = 10) =>
    api("/library/discover", {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    }),
  uploadLibrary: async (file) => {
    const fd = new FormData();
    fd.append("file", file, file.name || "library.csv");
    const res = await fetch(`${apiBase()}${withHubShareToken("/library/upload")}`, {
      method: "POST",
      credentials: "same-origin",
      body: fd,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = err.detail;
      const msg = Array.isArray(detail)
        ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
        : detail || res.statusText;
      throw new Error(msg || "Upload failed");
    }
    return res.json();
  },
  addPaperReviewToProject: (projectId, query, limit = 10, papers = []) =>
    api(`/projects/${projectId}/paper-reviews`, {
      method: "POST",
      body: JSON.stringify({ query, limit, papers }),
    }),
  runReviewAgent: (
    projectId,
    { query = "", limit = 10, refresh = false, download_pdfs = true, papers = [] } = {}
  ) =>
    api(`/projects/${projectId}/review-agent`, {
      method: "POST",
      body: JSON.stringify({ query, limit, refresh, download_pdfs, papers }),
    }),
  runPaperQuestionAgent: (
    projectId,
    { question = "", limit = 10, refresh = false, download_pdfs = true, papers = [] } = {}
  ) =>
    api(`/projects/${projectId}/paper-question-agent`, {
      method: "POST",
      body: JSON.stringify({ question, limit, refresh, download_pdfs, papers }),
    }),
  runLiteratureCluster: (
    projectId,
    { question = "", refresh = false, download_pdfs = true, papers = [] } = {}
  ) =>
    api(`/projects/${projectId}/literature/cluster`, {
      method: "POST",
      body: JSON.stringify({ question, refresh, download_pdfs, papers }),
    }),
  stageLiteratureCluster: (
    projectId,
    { question = "", papers = [] } = {}
  ) =>
    api(`/projects/${projectId}/literature/cluster/stage`, {
      method: "POST",
      body: JSON.stringify({ question, papers }),
    }),
  listLiteratureRuns: (projectId) =>
    api(`/projects/${encodeURIComponent(projectId)}/literature`),
  getLiteratureRun: (projectId, runId) =>
    api(`/projects/${encodeURIComponent(projectId)}/literature/${encodeURIComponent(runId)}`),
  deleteLiteratureRun: (projectId, runId) =>
    api(`/projects/${encodeURIComponent(projectId)}/literature/${encodeURIComponent(runId)}`, {
      method: "DELETE",
    }),
  stagePaperMorphology: (projectId, paper) =>
    api(`/projects/${encodeURIComponent(projectId)}/morphology/stage`, {
      method: "POST",
      body: JSON.stringify({ paper }),
    }),
  explainMorphologyInTerminal: (projectId, prompt, { runId, nodeId } = {}) =>
    api(`/projects/${encodeURIComponent(projectId)}/morphology/explain-terminal`, {
      method: "POST",
      body: JSON.stringify({ prompt, run_id: runId, node_id: nodeId }),
    }),
  getMorphologyExplainNote: (projectId, runId, nodeId) =>
    api(
      `/projects/${encodeURIComponent(projectId)}/morphology/${encodeURIComponent(
        runId
      )}/explain-note?node_id=${encodeURIComponent(nodeId)}`
  ),
  stageMortalCombat: (projectId, primary, reviewer, question = "") =>
    api(`/projects/${encodeURIComponent(projectId)}/mortal-combat/stage`, {
      method: "POST",
      body: JSON.stringify({ primary, reviewer, question }),
    }),
  getMortalCombat: (projectId, runId) =>
    api(`/projects/${encodeURIComponent(projectId)}/mortal-combat/${encodeURIComponent(runId)}`),
  listMorphologyRuns: (projectId, paperKey = "") =>
    api(
      `/projects/${encodeURIComponent(projectId)}/morphology${
        paperKey ? `?paper_key=${encodeURIComponent(paperKey)}` : ""
      }`
    ),
  getMorphologyRun: (projectId, runId) =>
    api(`/projects/${encodeURIComponent(projectId)}/morphology/${encodeURIComponent(runId)}`),
  getMorphologyArticle: (projectId, runId) =>
    api(
      `/projects/${encodeURIComponent(projectId)}/morphology/${encodeURIComponent(runId)}/article`
    ),
  deleteMorphologyRun: (projectId, runId) =>
    api(`/projects/${encodeURIComponent(projectId)}/morphology/${encodeURIComponent(runId)}`, {
      method: "DELETE",
    }),
  stageMorphologyPresentation: (projectId, runId) =>
    api(
      `/projects/${encodeURIComponent(projectId)}/morphology/${encodeURIComponent(
        runId
      )}/presentations/stage`,
      { method: "POST" }
    ),
  listMorphologyPresentations: (projectId, runId) =>
    api(
      `/projects/${encodeURIComponent(projectId)}/morphology/${encodeURIComponent(
        runId
      )}/presentations`
    ),
  getMorphologyPresentation: (projectId, runId, presentationId) =>
    api(
      `/projects/${encodeURIComponent(projectId)}/morphology/${encodeURIComponent(
        runId
      )}/presentations/${encodeURIComponent(presentationId)}`
    ),
  generateRelatedWorks: (projectId, { problem = "", cluster_keys = [] } = {}) =>
    api(`/projects/${projectId}/paper-question-agent/related-works`, {
      method: "POST",
      body: JSON.stringify({ problem, cluster_keys }),
    }),
  getRelatedWorkItem: (itemId) => api(`/related-works/${encodeURIComponent(itemId)}`),
  claimRelatedWorkItem: (itemId) =>
    api(`/related-works/${encodeURIComponent(itemId)}/claim`, { method: "POST" }),
  listRelatedWorks: (projectId) =>
    api(`/projects/${encodeURIComponent(projectId)}/related-works`),
  getLatestPaperQuestionAgentRun: (projectId) =>
    api(`/projects/${projectId}/paper-question-agent/latest`),
  createReviewSet: (query, limit = 10, papers = []) =>
    api("/library/review-set", {
      method: "POST",
      body: JSON.stringify({ query, limit, papers }),
    }),
  listProjects: () => api("/projects"),
  listProjectsGrouped: () => api("/projects/grouped"),
  listComposites: () => api("/composites"),
  getComposite: (id) => api(`/composites/${encodeURIComponent(id)}`),
  listPrograms: () => api("/programs"),
  createProgram: (title, description = "") =>
    api("/programs", {
      method: "POST",
      body: JSON.stringify({ title, description }),
    }),
  getProgram: (id) => api(`/programs/${id}`),
  getLaboratory: () => api("/laboratory"),
  getProject: (id) => api(`/projects/${encodeURIComponent(id)}`),
  getKanbanRunningActivity: (id) =>
    api(`/projects/${encodeURIComponent(id)}/kanban/running-activity`),
  getKanbanLiveMonitor: (id) =>
    api(`/projects/${encodeURIComponent(id)}/kanban/live-monitor`),
  getCardLive: (projectId, boardId, cardId, tailLines = 100) =>
    api(
      `/projects/${encodeURIComponent(projectId)}/boards/${encodeURIComponent(boardId)}/cards/${encodeURIComponent(cardId)}/live?tail_lines=${tailLines}`
    ),
  liveFileUrl: (projectId, path) => {
    const q = encodeURIComponent(String(path || ""));
    return `${apiBase()}/projects/${encodeURIComponent(projectId)}/live/file?path=${q}`;
  },
  createProject: ({ title, description, tag, programId, programTitle }) =>
    api("/projects", {
      method: "POST",
      body: JSON.stringify({
        title,
        description: description || "",
        tag,
        program_id: programId || undefined,
        program_title: programTitle || undefined,
      }),
    }),
  saveProject: (id, project) =>
    api(`/projects/${id}`, { method: "PUT", body: JSON.stringify(project) }),
  addNode: (projectId, body) =>
    api(`/projects/${projectId}/nodes`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  patchNode: (projectId, nodeId, body) =>
    api(`/projects/${projectId}/nodes/${nodeId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteNode: (projectId, nodeId) =>
    api(`/projects/${projectId}/nodes/${nodeId}`, { method: "DELETE" }),
  addCard: (projectId, boardId, body) =>
    api(`/projects/${projectId}/boards/${boardId}/cards`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  deleteCardTag: (projectId, tag) =>
    api(`/projects/${encodeURIComponent(projectId)}/card-tags/${encodeURIComponent(tag)}`, { method: "DELETE" }),
  updateCardTag: (projectId, tag, body) =>
    api(`/projects/${encodeURIComponent(projectId)}/card-tags/${encodeURIComponent(tag)}`, {
      method: "PATCH", body: JSON.stringify(body),
    }),
  patchCard: (projectId, boardId, cardId, body) =>
    api(`/projects/${projectId}/boards/${boardId}/cards/${cardId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteCard: (projectId, boardId, cardId) =>
    api(`/projects/${projectId}/boards/${boardId}/cards/${cardId}`, {
      method: "DELETE",
    }),
  getCardReport: (projectId, boardId, cardId) =>
    api(`/projects/${projectId}/boards/${boardId}/cards/${cardId}/report`),
  getCardReportPath: (projectId, boardId, cardId) =>
    api(`/projects/${projectId}/boards/${boardId}/cards/${cardId}/report-path`),
  saveCardReport: (projectId, boardId, cardId, content) =>
    api(`/projects/${projectId}/boards/${boardId}/cards/${cardId}/report`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  uploadReportAsset: async (projectId, boardId, cardId, file) => {
    const fd = new FormData();
    fd.append("file", file, file.name || "paste.png");
    const res = await fetch(
      `${apiBase()}/projects/${projectId}/boards/${boardId}/cards/${cardId}/report/assets`,
      { method: "POST", body: fd }
    );
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = err.detail;
      const msg = Array.isArray(detail)
        ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ")
        : detail || res.statusText;
      throw new Error(msg || "Upload failed");
    }
    return res.json();
  },
  reportAssetUrl: (projectId, boardId, cardId, markdownPath) => {
    // Keep path separators: nested HTML lives at assets/reports/<scene>/index.html
    const name = String(markdownPath || "")
      .replace(/^assets\//, "")
      .replace(/^\/+/, "")
      .split("/")
      .map((seg) => encodeURIComponent(seg))
      .join("/");
    return `${apiBase()}/projects/${projectId}/boards/${boardId}/cards/${cardId}/report/assets/${name}`;
  },
  listProjectPapers: (projectId) => api(`/projects/${projectId}/papers`),
  generatePaper: (projectId, slug = "default") =>
    api(`/projects/${projectId}/paper?slug=${encodeURIComponent(slug)}`, { method: "POST" }),
  getPaperStatus: (projectId, slug = "default") =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/status`),
  paperPdfUrl: (projectId, slug = "default") =>
    `${apiBase()}/projects/${projectId}/papers/${encodeURIComponent(slug)}/pdf`,
  paperTexUrl: (projectId, slug = "default") =>
    `${apiBase()}/projects/${projectId}/papers/${encodeURIComponent(slug)}/tex`,
  getPaperTex: (projectId, slug = "default", at = "") =>
    apiText(
      `/projects/${projectId}/papers/${encodeURIComponent(slug)}/tex${
        at ? `?at=${encodeURIComponent(at)}` : ""
      }`
    ),
  getPaperVersions: (projectId, slug = "default") =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/versions`),
  pullPaperVersions: (projectId, slug = "default") =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/versions/pull`, {
      method: "POST",
    }),
  pushPaperVersions: (projectId, slug = "default") =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/versions/push`, {
      method: "POST",
    }),
  getPaperTexMeta: (projectId, slug = "default") =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/tex/meta`),
  savePaperTex: (projectId, slug, content) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/tex`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  getPaperCollab: (projectId, slug = "default") =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/collab`),
  flushPaperCollab: (projectId, slug = "default") =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/collab/flush`, {
      method: "POST",
    }),
  getPaperCollabNetwork: (projectId, slug = "default", peer = "") =>
    api(
      `/projects/${projectId}/papers/${encodeURIComponent(slug)}/collab/network?peer=${encodeURIComponent(peer)}`
    ),
  getPaperCollabProposal: (projectId, slug = "default") =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/collab/proposal`),
  acceptPaperCollabProposal: (projectId, slug, proposalId) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/collab/proposal/accept`, {
      method: "POST",
      body: JSON.stringify({ proposal_id: proposalId }),
    }),
  rejectPaperCollabProposal: (projectId, slug, proposalId) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/collab/proposal/reject`, {
      method: "POST",
      body: JSON.stringify({ proposal_id: proposalId }),
    }),
  acceptPaperCollabProposalHunk: (projectId, slug, proposalId, hunkId) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/collab/proposal/hunk/accept`, {
      method: "POST",
      body: JSON.stringify({ proposal_id: proposalId, hunk_id: hunkId }),
    }),
  rejectPaperCollabProposalHunk: (projectId, slug, proposalId, hunkId) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/collab/proposal/hunk/reject`, {
      method: "POST",
      body: JSON.stringify({ proposal_id: proposalId, hunk_id: hunkId }),
    }),
  registerPaperCollabAgentTask: (projectId, slug = "default", taskId = null) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/collab/agent-task`, {
      method: "POST",
      body: JSON.stringify(taskId ? { task_id: taskId } : {}),
    }),
  paperCollabWsUrl: (projectId, slug = "default", params = {}) => {
    const httpBase = apiBase();
    const wsBase = httpBase.replace(/^http/i, "ws");
    const query = new URLSearchParams(
      Object.fromEntries(
        Object.entries(params).filter(([, value]) => value != null && value !== "")
      )
    ).toString();
    return `${wsBase}/projects/${encodeURIComponent(projectId)}/papers/${encodeURIComponent(slug)}/collab${
      query ? `?${query}` : ""
    }`;
  },
  paperCollabWsFallbackUrl: (projectId, slug = "default", params = {}) => {
    if (typeof window === "undefined" || !window.location?.hostname) {
      return "";
    }
    if (window.researchOSDesktop) {
      const query = new URLSearchParams(
        Object.fromEntries(
          Object.entries(params).filter(([, value]) => value != null && value !== "")
        )
      ).toString();
      const wsBase = apiBase().replace(/^http/i, "ws");
      return `${wsBase}/projects/${encodeURIComponent(projectId)}/papers/${encodeURIComponent(slug)}/collab${
        query ? `?${query}` : ""
      }`;
    }
    const { protocol, hostname } = window.location;
    const wsProto = protocol === "https:" ? "wss:" : "ws:";
    const query = new URLSearchParams(
      Object.fromEntries(
        Object.entries(params).filter(([, value]) => value != null && value !== "")
      )
    ).toString();
    return `${wsProto}//${hostname}:8010/projects/${encodeURIComponent(projectId)}/papers/${encodeURIComponent(slug)}/collab${
      query ? `?${query}` : ""
    }`;
  },
  compilePaper: (projectId, slug = "default") =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/compile`, {
      method: "POST",
    }),
  updatePaperProgress: (projectId, slug, payload) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/meta`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  getPaperComments: (projectId, slug = "default") =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/comments`),
  mergePaperComments: (projectId, slug, payload) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/comments`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  createPaperComment: (projectId, slug, payload) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/comments`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  replyPaperComment: (projectId, slug, commentId, payload) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/comments/${encodeURIComponent(commentId)}/replies`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  resolvePaperComment: (projectId, slug, commentId, resolved = true) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/comments/${encodeURIComponent(commentId)}`, {
      method: "PATCH",
      body: JSON.stringify({ resolved }),
    }),
  deletePaperComment: (projectId, slug, commentId) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/comments/${encodeURIComponent(commentId)}`, {
      method: "DELETE",
    }),
  askPaperCommentAgent: (projectId, slug, commentId, payload) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/comments/${encodeURIComponent(commentId)}/agent`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  paperCommentAgentStatus: (projectId, slug, commentId) =>
    api(`/projects/${projectId}/papers/${encodeURIComponent(slug)}/comments/${encodeURIComponent(commentId)}/agent`),
  getKnowledge: (projectId) => apiText(`/projects/${projectId}/knowledge`),
  getKnowledgeSummary: (projectId) => api(`/projects/${projectId}/knowledge/summary`),
  getKnowledgeLog: (projectId) => apiText(`/projects/${projectId}/knowledge/log`),
  getKnowledgeFile: (projectId, path) =>
    apiText(`/projects/${projectId}/knowledge/file?path=${encodeURIComponent(path)}`),
  knowledgeAssetUrl: (projectId, path) =>
    `${apiBase()}/projects/${projectId}/knowledge/asset?path=${encodeURIComponent(path)}`,
  listPages: (projectId) => api(`/projects/${projectId}/pages`),
  createPage: (projectId, title) =>
    api(`/projects/${projectId}/pages`, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  deletePage: (projectId, pageId) =>
    api(`/projects/${projectId}/pages/${encodeURIComponent(pageId)}`, {
      method: "DELETE",
    }),
  pageFileUrl: (projectId, pageId, filePath = "index.html") => {
    const parts = String(filePath || "index.html")
      .replace(/^\/+/, "")
      .split("/")
      .map((seg) => encodeURIComponent(seg))
      .join("/");
    return `${apiBase()}/projects/${projectId}/pages/${encodeURIComponent(pageId)}/file/${parts}`;
  },
  listNodePages: (projectId, nodeId) =>
    api(`/projects/${projectId}/nodes/${encodeURIComponent(nodeId)}/pages`),
  attachNodePage: (projectId, nodeId, body) =>
    api(`/projects/${projectId}/nodes/${encodeURIComponent(nodeId)}/pages`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  setNodePageVisible: (projectId, nodeId, pageId, visible) =>
    api(
      `/projects/${projectId}/nodes/${encodeURIComponent(nodeId)}/pages/${encodeURIComponent(pageId)}`,
      {
        method: "PATCH",
        body: JSON.stringify({ visible }),
      }
    ),
  detachNodePage: (projectId, nodeId, pageId) =>
    api(
      `/projects/${projectId}/nodes/${encodeURIComponent(nodeId)}/pages/${encodeURIComponent(pageId)}`,
      { method: "DELETE" }
    ),
  sendAgentQuestion: (body) =>
    api("/agent-chat", { method: "POST", body: JSON.stringify(body) }),
  listAgentChat: (projectId, boardId = null, cardId = null) =>
    api(`/agent-chat?project_id=${encodeURIComponent(projectId)}${cardId ? `&board_id=${encodeURIComponent(boardId)}&card_id=${encodeURIComponent(cardId)}` : ""}`),
  listAgentChatActivity: (projectId, boardId = null, cardId = null) =>
    api(`/agent-chat/activity?project_id=${encodeURIComponent(projectId)}${cardId ? `&board_id=${encodeURIComponent(boardId)}&card_id=${encodeURIComponent(cardId)}` : ""}`),
  listAgentChatPending: () => api("/agent-chat/pending"),
  deleteAgentChatItem: (itemId) =>
    api(`/agent-chat/${encodeURIComponent(itemId)}`, { method: "DELETE" }),
  getSyncStatus: (fetch = true) =>
    api(`/sync/status?fetch=${fetch ? "true" : "false"}`),
  pullSync: (projectId) => {
    const q = projectId
      ? `?project_id=${encodeURIComponent(projectId)}`
      : "";
    return api(`/sync/pull${q}`, { method: "POST" });
  },
  getProjectDiscovery: (since = 0) =>
    api(`/sync/project-discovery?since=${encodeURIComponent(since)}`),
  getRqDiscoveries: () => api("/sync/rq-discoveries"),
  getRqDiscoveriesFeed: (limit = 50) =>
    api(`/sync/rq-discoveries/feed?limit=${encodeURIComponent(limit)}`),
  ackRqDiscoveries: () => api("/sync/rq-discoveries/ack", { method: "POST" }),
  getSettings: () => api("/settings"),
  setInboxConfigured: (configured = true, inboxKind = "chat") =>
    api("/settings/inbox-configured", {
      method: "PUT",
      body: JSON.stringify({ configured, inbox_kind: inboxKind }),
    }),
  saveCursorApiKey: (cursor_api_key) =>
    api("/settings/cursor-api-key", {
      method: "PUT",
      body: JSON.stringify({ cursor_api_key }),
    }),
  saveAgentChatSettings: (body) =>
    api("/settings/agent-chat", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  getCursorUsage: () => api("/cursor/usage"),
  listWidgets: () => api("/widgets"),
  getWidgetData: (projectId, widgetId) =>
    api(`/widgets/${encodeURIComponent(projectId)}/${encodeURIComponent(widgetId)}/data`),
  postWidgetData: (projectId, widgetId, body) =>
    api(`/widgets/${encodeURIComponent(projectId)}/${encodeURIComponent(widgetId)}/data`, {
      method: "POST",
      body: JSON.stringify(body || {}),
    }),
  setWidgetEnabled: (projectId, widgetId, enabled) =>
    api(`/widgets/${encodeURIComponent(projectId)}/${encodeURIComponent(widgetId)}`, {
      method: "PUT",
      body: JSON.stringify({ enabled: Boolean(enabled) }),
    }),
  baseUrl: apiBase,
  meta: () => api("/meta/node-types"),
};
