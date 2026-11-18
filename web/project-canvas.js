import { KoiApi } from "./api.js";

export function openProjectCanvas(projectId, title) {
  if (document.querySelector(".project-canvas")) return;
  const dialog = document.createElement("dialog");
  dialog.className = "project-canvas";
  dialog.setAttribute("aria-labelledby", "project-canvas-title");
  dialog.innerHTML = `
    <header class="project-canvas__toolbar">
      <h2 id="project-canvas-title"></h2>
      <span role="status">Загрузка холста…</span>
      <button type="button" class="btn btn-primary" data-save disabled>Сохранить</button>
      <button type="button" class="btn" data-close>Закрыть</button>
    </header>
    <iframe title="Редактор Excalidraw" aria-label="Редактор Excalidraw" sandbox="allow-scripts allow-downloads"></iframe>
  `;
  dialog.querySelector("h2").textContent = `Холст · ${title}`;
  const status = dialog.querySelector('[role="status"]');
  const save = dialog.querySelector("[data-save]");
  const close = dialog.querySelector("[data-close]");
  const frame = dialog.querySelector("iframe");
  let loaded = false;
  let dirty = false;
  let saving = false;
  let revision;
  let timeout;

  const beforeUnload = (event) => {
    event.preventDefault();
    event.returnValue = true;
  };

  function setDirty(value) {
    dirty = value;
    if (value) window.addEventListener("beforeunload", beforeUnload);
    else window.removeEventListener("beforeunload", beforeUnload);
  }

  function mayClose() {
    return !saving && (!dirty || window.confirm("Закрыть холст без сохранения?"));
  }

  const receive = async (event) => {
    if (event.source !== frame.contentWindow || event.origin !== "null") return;
    const message = event.data;
    if (message?.type === "canvas-load" && !loaded) {
      loaded = true;
      try {
        const stored = await KoiApi.getCanvas(projectId);
        revision = stored.revision;
        const scene = stored.scene === null ? null : JSON.parse(stored.scene);
        frame.contentWindow?.postMessage({
          type: "canvas-init",
          scene,
          theme: document.documentElement.dataset.theme,
        }, "*");
      } catch (error) {
        clearTimeout(timeout);
        status.textContent = `Не удалось открыть холст. ${error.message}`;
      }
    } else if (message?.type === "canvas-ready" && revision !== undefined) {
      clearTimeout(timeout);
      save.disabled = false;
      status.textContent = "";
    } else if (message?.type === "canvas-dirty") {
      setDirty(Boolean(message.dirty));
      if (dirty && !saving) status.textContent = "Есть несохранённые изменения";
    } else if (message?.type === "canvas-snapshot" && saving && typeof message.scene === "string") {
      clearTimeout(timeout);
      try {
        const result = await KoiApi.saveCanvas(projectId, revision, message.scene);
        revision = result.revision;
        frame.contentWindow?.postMessage({ type: "canvas-saved", version: message.version }, "*");
        status.textContent = "Сохранено";
      } catch (error) {
        status.textContent = error.message;
      } finally {
        saving = false;
        save.disabled = false;
      }
    } else if (message?.type === "canvas-error") {
      clearTimeout(timeout);
      status.textContent = "Не удалось загрузить редактор Excalidraw";
    }
  };

  window.addEventListener("message", receive);
  dialog.addEventListener("cancel", (event) => {
    if (!mayClose()) event.preventDefault();
  });
  dialog.addEventListener("close", () => {
    clearTimeout(timeout);
    window.removeEventListener("message", receive);
    setDirty(false);
    dialog.remove();
  });
  close.addEventListener("click", () => {
    if (mayClose()) dialog.close();
  });
  save.addEventListener("click", () => {
    saving = true;
    save.disabled = true;
    status.textContent = "Сохранение…";
    frame.contentWindow.postMessage({ type: "canvas-save" }, "*");
    timeout = setTimeout(() => {
      saving = false;
      save.disabled = false;
      status.textContent = "Редактор не ответил. Попробуйте сохранить ещё раз.";
    }, 5000);
  });
  frame.src = "./excalidraw-frame.html";
  timeout = setTimeout(() => {
    status.textContent = "Редактор загружается дольше обычного";
  }, 12000);
  document.body.append(dialog);
  dialog.showModal();
}
