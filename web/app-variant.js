const DRAFTS_KEY = "researchos-variant-drafts";

function mountVariantSettings() {
  if (document.getElementById("app-variant-dialog")) return;
  const template = document.createElement("template");
  template.innerHTML = `
    <button type="button" id="btn-app-variant" class="btn conversation-icon-button" aria-label="Настроить интерфейс" title="Настроить интерфейс" aria-haspopup="dialog" aria-controls="app-variant-dialog" hidden>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m10 3-.5 2-2 1-2-.5-2 3.5L5 10.5v3L3.5 15l2 3.5 2-.5 2 1 .5 2h4l.5-2 2-1 2 .5 2-3.5-1.5-1.5v-3L20.5 9l-2-3.5-2 .5-2-1L14 3Z"/><circle cx="12" cy="12" r="3"/></svg>
    </button>
    <dialog id="app-variant-dialog" class="tag-settings-dialog app-variant-dialog" aria-labelledby="app-variant-title" aria-describedby="app-variant-description">
      <form>
        <h2 id="app-variant-title">Режим интерфейса</h2>
        <p id="app-variant-description">Данные исследований сохраняются при переключении режима.</p>
        <fieldset>
          <legend class="sr-only">Выберите режим</legend>
          <label><input type="radio" name="ui_variant" value="chats" checked /> <span><strong>Чаты</strong><small>Разговоры и программы всегда под рукой в боковой панели.</small></span></label>
          <label><input type="radio" name="ui_variant" value="light" /> <span><strong>Light</strong><small>Классический интерфейс: карта, канбан и отчёты.</small></span></label>
        </fieldset>
        <p role="status" aria-live="polite"></p>
        <div class="form-actions">
          <button type="button" class="btn" data-cancel>Отмена</button>
          <button type="submit" class="btn btn-primary">Применить</button>
        </div>
      </form>
    </dialog>`;
  document.querySelector(".toolbar").append(template.content.querySelector("button"));
  document.body.append(template.content.querySelector("dialog"));
}

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
  mountVariantSettings();
  const stylesheet = document.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.href = new URL("./app-variant.css", import.meta.url).href;
  document.head.append(stylesheet);
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
