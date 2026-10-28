import { KoiApi } from "./api.js?v=20261021paper-edits";
import { initAppVariant } from "./app-variant.js";

const DRAFT_KEY = "researchos-light-draft";
await initAppVariant(KoiApi, async () => {
  if (document.querySelector(".agent-chat-mic.is-recording")) {
    throw new Error("Завершите запись голоса и повторите попытку.");
  }
  if (document.querySelector('.modal:not(.hidden)')) {
    throw new Error("Закройте открытое окно и повторите попытку.");
  }
  const input = document.getElementById("agent-chat-input");
  const project = document.querySelector('.lab-project-frame[aria-pressed="true"]')?.dataset.projectId;
  sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ project, text: input.value }));
});

// ponytail: keep main's UI intact while it differs substantially from Chats.
// Only these view files are pinned; backend, onboarding and other modules share
// their existing implementation. Extract common UI features as they change.
await import("./app.js?v=20261021paper-edits");
document.getElementById("agent-chat-input").addEventListener("focus", event => {
  let draft;
  try { draft = JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "null"); } catch { return; }
  const project = document.querySelector('.lab-project-frame[aria-pressed="true"]')?.dataset.projectId;
  if (draft?.project !== project || !draft?.text || event.target.value) return;
  event.target.value = draft.text;
  sessionStorage.removeItem(DRAFT_KEY);
});
