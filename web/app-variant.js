const DRAFTS_KEY = "researchos-variant-drafts";

function mountVariantSettings() {
  if (document.getElementById("app-variant-dialog")) return;
  const template = document.createElement("template");
  template.innerHTML = `
    <button type="button" id="btn-app-variant" class="btn conversation-icon-button" aria-label="Настроить интерфейс" title="Настроить интерфейс" aria-haspopup="dialog" aria-controls="app-variant-dialog" hidden>
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m10 3-.5 2-2 1-2-.5-2 3.5L5 10.5v3L3.5 15l2 3.5 2-.5 2 1 .5 2h4l.5-2 2-1 2 .5 2-3.5-1.5-1.5v-3L20.5 9l-2-3.5-2 .5-2-1L14 3Z"/><circle cx="12" cy="12" r="3"/></svg>
    </button>
    <dialog id="app-variant-dialog" class="tag-settings-dialog app-variant-dialog" aria-labelledby="app-variant-title">
      <form>
        <h2 id="app-variant-title">Настройки</h2>
        <button type="button" class="modal-close" data-cancel aria-label="Закрыть настройки">×</button>
        <div class="settings-content">
        <fieldset>
          <legend>Интерфейс</legend>
          <div class="view-control settings-interface-control"><div class="view-control__segmented settings-interface-options">
          <label class="view-control__seg"><input type="radio" name="ui_variant" value="chats" /> <span><strong>Чаты</strong></span></label>
          <label class="view-control__seg"><input type="radio" name="ui_variant" value="quick" checked /> <span><strong>Quick navigation</strong></span></label>
          <label class="view-control__seg"><input type="radio" name="ui_variant" value="light" /> <span><strong>Light</strong></span></label>
          </div></div>
        </fieldset>
        <section class="settings-trees" aria-labelledby="settings-trees-title">
          <h3 id="settings-trees-title">Управление деревьями</h3>
          <div class="view-control view-control__segmented settings-archive-switch" aria-label="Показать деревья">
            <button type="button" class="view-control__seg" data-show-archive="false" aria-pressed="true">Текущие</button>
            <button type="button" class="view-control__seg" data-show-archive="true" aria-pressed="false">Архивированные</button>
          </div>
          <div class="settings-tree-columns" data-archive="false"></div>
        </section>
        </div>
        <p role="status" aria-live="polite"></p>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary">Применить режим</button>
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

export async function initAppVariant(api, prepareSwitch, trees) {
  mountVariantSettings();
  const stylesheet = document.createElement("link");
  stylesheet.rel = "stylesheet";
  stylesheet.href = new URL("./app-variant.css", import.meta.url).href;
  document.head.append(stylesheet);
  let variant = "quick";
  try {
    const saved = (await api.getSettings()).ui_variant;
    if (["chats", "quick", "light"].includes(saved)) variant = saved;
  }
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
  trigger.title = `Режим интерфейса: ${{light: "Light", quick: "Quick navigation", chats: "Чаты"}[variant]}`;
  trigger.onclick = async () => {
    form.elements.ui_variant.value = variant;
    status.textContent = "";
    columns.replaceChildren();
    dialog.showModal();
    status.textContent = "Загружаем деревья…";
    try {
      await trees.refresh();
      renderTrees();
      status.textContent = "";
    } catch (error) {
      status.textContent = `Не удалось загрузить деревья. ${error.message}`;
    }
  };
  const columns = dialog.querySelector('.settings-tree-columns');
  const archiveSwitch = dialog.querySelector('.settings-archive-switch');
  let moving = false;
  archiveSwitch.onclick = event => {
    const button = event.target.closest('[data-show-archive]');
    if (!button) return;
    columns.dataset.archive = button.dataset.showArchive;
    for (const item of archiveSwitch.children) item.setAttribute('aria-pressed', String(item === button));
  };
  function renderTrees() {
    columns.replaceChildren();
    for (const archived of [false, true]) {
      const column = document.createElement('section');
      column.dataset.archived = String(archived);
      const heading = document.createElement('h4');
      heading.textContent = archived ? 'Архивированные' : 'Текущие';
      column.append(heading);
      const scroll = document.createElement('div');
      scroll.className = 'settings-program-scroll';
      scroll.tabIndex = 0;
      scroll.setAttribute('role', 'region');
      scroll.setAttribute('aria-label', archived ? 'Архивированные программы и деревья' : 'Текущие программы и деревья');
      column.append(scroll);
      let count = 0;
      for (const group of trees.groups()) {
        const items = group.trees.filter(tree => tree.archived === archived);
        if (!items.length) continue;
        count += items.length;
        const block = document.createElement('section');
        block.className = 'settings-program';
        const title = document.createElement('h5');
        title.textContent = group.title;
        block.append(title);
        const list = document.createElement('ul');
        for (const tree of items) {
          const row = document.createElement('li');
          const name = document.createElement('span');
          name.textContent = tree.title;
          const action = document.createElement('button');
          action.type = 'button';
          action.className = 'conversation-icon-button';
          action.title = archived ? 'Восстановить' : 'В архив';
          action.setAttribute('aria-label', `${action.title}: ${tree.title}`);
          action.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${archived ? 'm14 6-6 6 6 6' : 'm10 6 6 6-6 6'}"/></svg>`;
          action.onclick = async () => {
            if (moving || saving) return;
            moving = true;
            for (const button of columns.querySelectorAll('button')) button.disabled = true;
            apply.disabled = true;
            status.textContent = 'Сохраняем…';
            try {
              await trees.archive(tree.id, !archived);
              status.textContent = trees.groups().some(group => group.trees.some(item => item.id === tree.id && item.archived === !archived))
                ? (archived ? 'Дерево восстановлено.' : 'Дерево перенесено в архив.')
                : 'Не удалось изменить архив. Повторите попытку.';
            } catch (error) {
              status.textContent = `Не удалось изменить архив. ${error.message}`;
            } finally {
              moving = false;
              apply.disabled = false;
              renderTrees();
              const target = [...columns.querySelectorAll('button')].find(button => button.dataset.treeId === tree.id && button.closest('section[data-archived]').dataset.archived === columns.dataset.archive);
              (target || columns.querySelector(`section[data-archived="${columns.dataset.archive}"] button`) || cancel).focus();
            }
          };
          action.dataset.treeId = tree.id;
          row.append(name, action);
          list.append(row);
        }
        block.append(list);
        scroll.append(block);
      }
      const counter = document.createElement('span');
      counter.className = 'settings-tree-count';
      counter.textContent = count;
      heading.append(counter);
      if (!count) {
        const empty = document.createElement('p');
        empty.textContent = archived ? 'В архиве пока нет деревьев.' : 'Нет текущих деревьев.';
        scroll.append(empty);
      }
      columns.append(column);
    }
  }
  cancel.onclick = () => dialog.close();
  dialog.addEventListener("cancel", event => { if (saving) event.preventDefault(); });
  dialog.addEventListener("close", () => trigger.focus());
  form.onsubmit = async event => {
    event.preventDefault();
    if (moving || saving) return;
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
