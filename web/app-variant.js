const DRAFTS_KEY = "researchos-variant-drafts";

export const usesChatNavigation = () => document.documentElement.dataset.appVariant !== "light";

export function preserveVariantDrafts(controllers) {
  const saved = {};
  for (const [name, controller] of Object.entries(controllers)) {
    controller.rememberDraft();
    saved[name] = { drafts: [...controller.drafts], row: controller.row };
  }
  // Session storage spans this UI reload; the setting itself lives on the server
  // because the desktop origin changes its port on the next application launch.
  sessionStorage.setItem(DRAFTS_KEY, JSON.stringify(saved));
}

export function restoreVariantDrafts(controllers) {
  let saved;
  try {
    saved = JSON.parse(sessionStorage.getItem(DRAFTS_KEY) || "null");
    sessionStorage.removeItem(DRAFTS_KEY);
  } catch { return; }
  for (const [name, controller] of Object.entries(controllers)) {
    if (!saved?.[name]) continue;
    controller.drafts = new Map(saved[name].drafts);
    if (name === "main") controller.row = saved[name].row;
    controller.input.value = controller.drafts.get(controller.row?.id || controller.draftKey()) || "";
  }
}

export async function initAppVariant(api, prepareSwitch) {
  let variant = "chats";
  try { variant = (await api.getSettings()).ui_variant === "light" ? "light" : "chats"; }
  catch { /* Keep the existing interface available when settings are offline. */ }
  document.documentElement.dataset.appVariant = variant;
  const trigger = document.getElementById("btn-app-variant");
  const dialog = document.getElementById("app-variant-dialog");
  const form = dialog.querySelector("form");
  const status = dialog.querySelector('[role="status"]');
  const apply = form.querySelector('[type="submit"]');
  const cancel = dialog.querySelector('[data-cancel]');
  let saving = false;
  trigger.hidden = false;
  trigger.title = `Режим интерфейса: ${variant === "light" ? "Light" : "Чаты"}`;
  trigger.onclick = () => {
    form.elements.ui_variant.value = variant;
    status.textContent = "";
    dialog.showModal();
  };
  cancel.onclick = () => dialog.close();
  dialog.addEventListener("cancel", event => { if (saving) event.preventDefault(); });
  dialog.addEventListener("close", () => trigger.focus());
  form.onsubmit = async event => {
    event.preventDefault();
    const next = form.elements.ui_variant.value;
    if (next === variant) { dialog.close(); return; }
    saving = true;
    apply.disabled = cancel.disabled = form.querySelector("fieldset").disabled = true;
    status.textContent = "Сохраняем выбор…";
    try {
      await prepareSwitch();
      await api.saveAgentChatSettings({ ui_variant: next });
      location.reload();
    } catch (error) {
      try { sessionStorage.removeItem(DRAFTS_KEY); } catch { /* Storage unavailable. */ }
      status.textContent = `Не удалось переключить режим. ${error.message}`;
      saving = false;
      apply.disabled = cancel.disabled = form.querySelector("fieldset").disabled = false;
    }
  };
}
