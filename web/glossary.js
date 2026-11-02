import { KoiApi } from "./api.js?v=20261021paper-edits";

// A native dialog supplies focus trapping, Escape and focus restoration.
export async function openGlossary(projectId = null, selected = "") {
  if (document.getElementById("glossary-dialog")) return;
  const dialog = document.createElement("dialog");
  dialog.id = "glossary-dialog";
  dialog.className = "tag-settings-dialog glossary-dialog";
  dialog.setAttribute("aria-labelledby", "glossary-title");
  dialog.innerHTML = `
    <header class="tag-settings-header"><h2 id="glossary-title">${selected ? "Добавить в словарь" : "Словарь"}</h2>
      <button type="button" class="btn" data-close aria-label="Закрыть словарь">×</button></header>
    <form>
      <label for="glossary-scope">Область действия</label>
      <select id="glossary-scope"><option value="tree">Только это дерево</option><option value="global">Все деревья</option></select>
      <p id="glossary-help">Одна запись на строку: «термин» или «термин &gt; замена». Можно добавить « — значение».</p>
      <div data-quick hidden>
        <label for="glossary-term">Термин</label><input id="glossary-term" maxlength="500" />
        <label for="glossary-replacement">Замена</label><input id="glossary-replacement" maxlength="500" aria-describedby="glossary-replacement-help" />
        <p id="glossary-replacement-help">Оставьте пустым, чтобы сохранить термин как предпочтительный.</p>
      </div>
      <label for="glossary-text" data-editor-label>Термины и замены</label>
      <textarea id="glossary-text" rows="10" maxlength="100000" spellcheck="false" aria-describedby="glossary-help"></textarea>
      <details data-inherited hidden><summary>Общие правила для всех деревьев</summary><pre></pre></details>
      <p>Правила дерева имеют приоритет над общими. Существующие отчёты автоматически не меняются.</p>
      <p data-status role="status" aria-live="polite">Загружаю словарь…</p>
      <footer class="glossary-actions"><button type="button" class="btn" data-close>Отмена</button>
        <button type="submit" class="btn btn-primary" disabled>Сохранить</button></footer>
    </form>`;
  document.body.append(dialog);
  const scope = dialog.querySelector("select");
  const editor = dialog.querySelector("textarea");
  const term = dialog.querySelector("#glossary-term");
  const replacement = dialog.querySelector("#glossary-replacement");
  const save = dialog.querySelector('[type="submit"]');
  const status = dialog.querySelector("[data-status]");
  [editor, term, replacement].forEach(input => { input.disabled = true; });
  scope.value = projectId ? "tree" : "global";
  scope.disabled = true;
  scope.querySelector('[value="tree"]').disabled = !projectId;
  dialog.querySelector("[data-quick]").hidden = !selected;
  dialog.querySelector("#glossary-help").hidden = !!selected;
  editor.hidden = !!selected;
  dialog.querySelector("[data-editor-label]").hidden = !!selected;
  term.value = selected.trim();
  let documents = null, drafts = {}, active = scope.value, busy = false;
  const dirty = () => documents && (selected
    ? replacement.value !== "" || term.value !== selected.trim()
    : Object.keys(drafts).some(key => documents[key] && (key === active ? editor.value : drafts[key]) !== documents[key].text));
  function close() {
    if (busy) return;
    if (dirty() && !window.confirm("Закрыть словарь без сохранения изменений?")) return;
    dialog.close();
  }
  dialog.querySelectorAll("[data-close]").forEach(button => { button.onclick = close; });
  dialog.addEventListener("cancel", event => { event.preventDefault(); close(); });
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal();
  function showScope() {
    active = scope.value;
    editor.value = drafts[active];
    const inherited = dialog.querySelector("[data-inherited]");
    inherited.hidden = active !== "tree" || !documents.global.text.trim();
    inherited.querySelector("pre").textContent = documents.global.text;
    status.textContent = "";
  }
  scope.onchange = () => {
    if (!documents) return;
    if (!selected && editor.value !== documents[active].text
      && !window.confirm("Сменить область без сохранения изменений?")) {
      scope.value = active; return;
    }
    drafts[active] = documents[active].text;
    showScope();
  };
  try {
    const data = await KoiApi.getGlossary(projectId);
    if (!dialog.isConnected) return;
    documents = { global: data.global, tree: data.tree };
    drafts = { global: data.global.text, tree: data.tree?.text || "" };
    showScope();
    status.textContent = (data.errors || []).join("\n");
    scope.disabled = false;
    [editor, term, replacement].forEach(input => { input.disabled = false; });
    save.disabled = false;
    (selected ? replacement : editor).focus();
  } catch (error) { status.textContent = error.message; }
  dialog.querySelector("form").onsubmit = async event => {
    event.preventDefault();
    if (busy || !documents) return;
    let text = editor.value;
    if (selected) {
      const source = term.value.trim(), target = replacement.value.trim();
      if (!source || /[>\r\n]/.test(source + target) || source.includes(" — ") || target.includes(" — ")) {
        status.textContent = "Введите термин и замену без переноса строки, знака > и разделителя « — ».";
        term.focus(); return;
      }
      const rule = target ? `${source} > ${target}` : source;
      const lines = documents[active].text.split("\n");
      const index = lines.findIndex(line => !line.trim().startsWith("#") && line.split(" — ")[0].split(">")[0].trim().toLocaleLowerCase() === source.toLocaleLowerCase());
      if (index >= 0) {
        const meaning = lines[index].split(" — ").slice(1).join(" — ");
        lines[index] = rule + (meaning ? ` — ${meaning}` : "");
      }
      else lines.push(rule);
      text = lines.join("\n").replace(/^\n/, "");
    }
    busy = true; save.disabled = true; scope.disabled = true;
    try {
      await KoiApi.saveGlossary(active === "tree" ? projectId : null, text, documents[active].revision);
      dialog.close();
    } catch (error) {
      status.textContent = error.message;
    } finally { busy = false; save.disabled = false; scope.disabled = false; }
  };
}
