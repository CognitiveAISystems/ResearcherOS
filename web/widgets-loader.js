/** Shared widget runtime and visibility settings for web and Electron. */
export async function initWidgets({ api, skip = false } = {}) {
  if (skip) return;
  const root = document.getElementById("koi-widgets-root");
  const button = document.getElementById("btn-widgets");
  const dialog = document.getElementById("widgets-dialog");
  if (!root || !button || !dialog) return;

  const list = dialog.querySelector(".widgets-list");
  const search = dialog.querySelector("input[type=search]");
  const status = dialog.querySelector(".widgets-status");
  const reload = dialog.querySelector(".widgets-reload");
  const hideAll = dialog.querySelector(".widgets-hide-all");
  const mounted = new Map();
  const errors = new Map();
  const retryTargets = new Map();
  let items = [];
  let busy = false;

  async function unmount(item) {
    const instance = mounted.get(item.key);
    if (!instance) return;
    mounted.delete(item.key);
    try {
      await instance.cleanup?.();
    } catch (error) {
      console.warn(`[widgets] cleanup failed: ${item.key}`, error);
    } finally {
      instance.host.remove();
    }
  }

  async function mount(item) {
    if (mounted.has(item.key)) return;
    const host = document.createElement("div");
    host.className = "koi-widget-host";
    host.dataset.widgetKey = item.key;
    host.dataset.widgetId = item.id;
    root.appendChild(host);
    try {
      const mod = await import(/* webpackIgnore: true */ item.web_url);
      if (typeof mod.mount !== "function") throw new Error("Missing mount export");
      const cleanup = await mod.mount(host, {
        api, widgetId: item.id, widgetKey: item.key,
        assetBase: item.web_url.replace(/\/[^/]+$/, ""), manifest: item,
      });
      mounted.set(item.key, { host, cleanup: typeof cleanup === "function" ? cleanup : null });
      errors.delete(item.key);
      retryTargets.delete(item.key);
    } catch (error) {
      host.remove();
      errors.set(item.key, "Не удалось загрузить виджет.");
      retryTargets.set(item.key, true);
      console.warn(`[widgets] failed to mount ${item.key}`, error);
    }
  }

  function render() {
    list.replaceChildren();
    const query = search.value.trim().toLocaleLowerCase();
    const visible = items.filter((item) =>
      `${item.title} ${item.summary} ${item.project_id}`.toLocaleLowerCase().includes(query));
    if (!visible.length) {
      const empty = document.createElement("p");
      empty.className = "widgets-empty";
      empty.textContent = query ? "Ничего не найдено." : "В подключённых проектах пока нет виджетов.";
      list.appendChild(empty);
    }
    for (const item of visible) {
      const row = document.createElement("div");
      row.className = "widgets-row";
      const label = document.createElement("label");
      label.className = "widgets-choice";
      const info = document.createElement("span");
      info.className = "widgets-info";
      const title = document.createElement("strong");
      title.textContent = item.title || item.id;
      const project = document.createElement("span");
      project.className = "widgets-project";
      project.textContent = item.project_id || "";
      const summary = document.createElement("span");
      summary.className = "widgets-summary";
      summary.textContent = item.summary || "";
      info.append(title, project, summary);
      const toggle = document.createElement("input");
      toggle.type = "checkbox";
      toggle.setAttribute("role", "switch");
      toggle.setAttribute("aria-label", `Показывать ${item.title || item.id} (${item.project_id})`);
      toggle.checked = item.enabled;
      toggle.disabled = busy;
      toggle.addEventListener("change", () => void change(item, toggle.checked));
      label.append(info, toggle);
      row.appendChild(label);
      if (errors.has(item.key)) {
        const error = document.createElement("div");
        error.className = "widgets-error";
        error.setAttribute("role", "status");
        error.append(document.createTextNode(errors.get(item.key) + " "));
        const retry = document.createElement("button");
        retry.type = "button";
        retry.className = "btn btn-small";
        retry.textContent = "Повторить";
        retry.disabled = busy;
        retry.addEventListener("click", () => void change(item, retryTargets.get(item.key) ?? item.enabled));
        error.appendChild(retry);
        row.appendChild(error);
      }
      list.appendChild(row);
    }
    reload.disabled = busy;
    hideAll.disabled = busy || !items.some((item) => item.enabled);
    button.title = `Виджеты: включено ${items.filter((item) => item.enabled).length}`;
  }

  async function update(item, enabled) {
    try {
      const saved = await api.setWidgetEnabled(item.project_id, item.id, enabled);
      item.enabled = saved.enabled;
      errors.delete(item.key);
      retryTargets.delete(item.key);
      if (item.enabled) await mount(item);
      else await unmount(item);
    } catch (error) {
      errors.set(item.key, "Не удалось сохранить выбор. Попробуйте ещё раз.");
      retryTargets.set(item.key, enabled);
      console.warn(`[widgets] update failed: ${item.key}`, error);
    }
  }

  async function change(item, enabled) {
    if (busy) return;
    busy = true;
    render();
    await update(item, enabled);
    busy = false;
    render();
    // Rendering replaces the controls; retain keyboard focus on the changed row.
    const index = items.filter((entry) =>
      `${entry.title} ${entry.summary} ${entry.project_id}`.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())).indexOf(item);
    list.querySelectorAll('input[type="checkbox"]')[index]?.focus();
  }

  async function refresh() {
    if (busy) return;
    busy = true;
    status.textContent = "Загружаем виджеты…";
    render();
    try {
      const catalog = await api.listWidgets();
      const next = (Array.isArray(catalog?.widgets) ? catalog.widgets : []).filter((item) => item.web_url);
      for (const item of items) {
        if (!next.some((entry) => entry.key === item.key && entry.enabled)) await unmount(item);
      }
      items = next;
      for (const item of items) if (item.enabled) await mount(item);
      status.textContent = "Изменения сохраняются автоматически.";
    } catch (error) {
      status.textContent = "Не удалось получить список виджетов. Нажмите «Обновить».";
      console.warn("[widgets] catalog unavailable", error);
    } finally {
      busy = false;
      render();
    }
  }

  button.addEventListener("click", () => {
    if (!dialog.open) dialog.showModal();
    search.focus();
    void refresh();
  });
  dialog.querySelectorAll("[data-widgets-close]").forEach((el) =>
    el.addEventListener("click", () => dialog.close()));
  dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  });
  dialog.addEventListener("keydown", (event) => {
    if (event.key === "Escape") event.stopPropagation();
  });
  dialog.addEventListener("close", () => button.focus());
  search.addEventListener("input", render);
  reload.addEventListener("click", () => void refresh());
  hideAll.addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    render();
    // The server stores one state file: serialize writes to avoid lost updates.
    for (const item of items) if (item.enabled) await update(item, false);
    busy = false;
    render();
  });
  await refresh();
}
