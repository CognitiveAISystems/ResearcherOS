import { marked } from "./vendor-marked.mjs";

export const EMPTY_REPORT = "## Цель\n\n## Постановка эксперимента\n\n## Задачи\n\n## Эксперименты\n\n## Результаты\n";

// Preserve raw Markdown, including code fences, tables and unknown legacy blocks.
export function reportBlocks(source) {
  const blocks = [];
  let offset = 0;
  for (const token of marked.lexer(source)) {
    const start = source.indexOf(token.raw, offset);
    // A lexer may normalize CRLF; retain the original as one editable block.
    if (start < 0) return [{ raw: source, type: "raw" }];
    if (start > offset) blocks.push({ raw: source.slice(offset, start), type: "raw" });
    if (token.type === "space" && blocks.length) blocks[blocks.length - 1].raw += token.raw;
    else blocks.push({ raw: token.raw, type: token.type });
    offset = start + token.raw.length;
  }
  if (offset < source.length) blocks.push({ raw: source.slice(offset), type: "raw" });
  return blocks;
}

export function applySetup(source, proposal) {
  const names = { "Цель": proposal.goal, "Постановка эксперимента": proposal.setup, "Задачи": proposal.tasks };
  const blocks = reportBlocks(source);
  const sections = [];
  let section = { title: null, raw: "" };
  for (const block of blocks) {
    const heading = block.type === "heading" && block.raw.match(/^##\s+(.+?)\s*\n/);
    if (heading) { sections.push(section); section = { title: heading[1], raw: block.raw }; }
    else section.raw += block.raw;
  }
  sections.push(section);
  for (const [title, text] of Object.entries(names)) {
    const found = sections.find(s => s.title === title);
    const raw = `## ${title}\n\n${text.trim()}\n\n`;
    if (found) found.raw = raw;
    else sections.push({ title, raw });
  }
  return sections.map(s => s.raw).join("");
}

export function setupWouldShrink(source, proposal) {
  let inSetup = false;
  let existing = "";
  for (const block of reportBlocks(source)) {
    const heading = block.type === "heading" && block.raw.match(/^##\s+(.+?)\s*\n/);
    if (heading) {
      inSetup = heading[1] === "Постановка эксперимента";
    } else if (inSetup) {
      existing += block.raw;
    }
  }
  const length = value => value.replace(/\s+/g, " ").trim().length;
  return length(existing) > 200 && length(proposal.setup) < length(existing) * 0.75;
}

const BLOCK_TYPES = [
  ["Текст", "text paragraph", "T", "", "paragraph"],
  ...[1, 2, 3, 4].map(n => [`Заголовок ${n}`, `heading h${n}`, `H${n}`, "#".repeat(n) + " ", "heading"]),
  ["Маркированный список", "bulleted list", "•", "- ", "list"],
  ["Нумерованный список", "numbered list", "1.", "1. ", "list"],
  ["Список задач", "todo checklist", "☑", "- [ ] ", "list"],
  ["Цитата", "quote", "❝", "> ", "blockquote"],
  ["Код", "code", "</>", "```\n\n```", "code", 4],
  ["Формула", "math equation latex формулы", "∑", "$$\nx = \\frac{a}{b}\n$$", "blockMath"],
  ["Таблица", "table", "▦", "| Столбец 1 | Столбец 2 |\n| --- | --- |\n|  |  |", "table"],
  ["Разделитель", "divider", "—", "---", "hr"],
];

export class ReportEditor {
  constructor(host, { render, onChange, onAgent, onGlossary, onPaste, hookLinks, readOnly = false, toc = null }) {
    Object.assign(this, { host, render, onChange, onAgent, onGlossary, onPaste, hookLinks, readOnly, toc });
    if (toc) {
      this.tocMedia = window.matchMedia('(min-width: 1101px)');
      const resize = () => { toc.open = this.tocMedia.matches; };
      this.tocMedia.addEventListener('change', resize);
      resize();
    }
    this.blocks = [];
    host.addEventListener("contextmenu", e => {
      if (this.readOnly) return;
      const selected = this.selection();
      if (!selected) return;
      e.preventDefault();
      this.agentMenu(selected, e.clientX, e.clientY);
    });
    host.addEventListener("keyup", e => {
      if (this.readOnly || !this.onGlossary || !(e.shiftKey || e.key === "ContextMenu")) return;
      const selected = this.selection();
      if (selected) {
        const bounds = e.target.getBoundingClientRect();
        this.agentMenu(selected, bounds.left, bounds.top);
        document.querySelector(".report-agent-menu button:last-child")?.focus();
      }
    });
    host.addEventListener("mouseup", e => {
      if (this.readOnly) return;
      const selected = this.selection();
      if (selected) this.agentMenu(selected, e.clientX, e.clientY + 12);
    });
  }
  selection() {
    const input = this.host.querySelector("textarea:focus");
    return input ? input.value.slice(input.selectionStart, input.selectionEnd) : window.getSelection()?.toString() || "";
  }
  agentMenu(selected, x, y) {
    document.querySelector(".report-agent-menu")?.remove();
    const menu = document.createElement("div");
    menu.className = "report-agent-menu";
    menu.setAttribute("role", "group");
    menu.setAttribute("aria-label", "Действия с выделенным текстом");
    menu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - 340))}px`;
    menu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - 120))}px`;
    const actions = [["Сформулировать постановку с агентом", this.onAgent]];
    if (this.onGlossary) actions.push(["В словарь…", this.onGlossary]);
    for (const [label, action] of actions) {
      const button = document.createElement("button");
      button.type = "button"; button.className = "btn"; button.textContent = label;
      button.onclick = () => { menu.remove(); action(selected); };
      menu.append(button);
    }
    document.body.append(menu);
    const dismiss = e => { if (!menu.contains(e.target)) menu.remove(); };
    setTimeout(() => document.addEventListener("pointerdown", dismiss, { once: true }), 0);
    menu.addEventListener("keydown", e => { if (e.key === "Escape") { e.stopPropagation(); menu.remove(); this.host.focus(); } });
  }

  setValue(source) { this.blocks = reportBlocks(source); this.paint(); }
  getValue() { return this.blocks.map(b => b.raw).join(""); }
  changed() { this.onChange(this.getValue()); this.updateToc(); }
  updateToc() {
    if (!this.toc) return;
    const nav = this.toc.querySelector('nav');
    nav.replaceChildren();
    this.blocks.forEach((block, index) => {
      if (block.type !== 'heading' && !/^#{1,3}\s/.test(block.raw)) return;
      const fragment = document.createElement('div');
      fragment.innerHTML = this.renderBlock(block.raw);
      const heading = fragment.querySelector('h1, h2, h3');
      if (!heading) return;
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = heading.textContent;
      button.dataset.level = heading.tagName.slice(1);
      button.onclick = () => {
        if (!this.tocMedia.matches) this.toc.open = false;
        const target = this.host.querySelector(`[data-block-index="${index}"]`);
        target?.scrollIntoView({ block: 'start' });
        target?.focus({ preventScroll: true });
      };
      nav.append(button);
    });
    this.toc.hidden = !nav.childElementCount;
  }
  renderBlock(raw) {
    const links = marked.lexer(this.getValue()).links || {};
    const definitions = Object.entries(links).map(([name, link]) => `[${name}]: <${link.href}>${link.title ? ` ${JSON.stringify(link.title)}` : ""}`).join("\n");
    return this.render(raw + (definitions ? "\n\n" + definitions : ""));
  }
  visualBlock(el, index, focus = false) {
    if (this.readOnly) return false;
    const block = this.blocks[index];
    const token = marked.lexer(block.raw)[0];
    const taskLines = block.raw.trimEnd().split("\n");
    const tasks = taskLines.map(line => line.match(/^([-*+] )\[([ xX])\] ?(.*)$/));
    const save = raw => { block.raw = raw + "\n\n"; this.changed(); };
    const finish = () => {
      this.blocks.splice(index + 1, 0, { raw: "", type: "paragraph" });
      this.changed(); this.paint(index + 1);
    };
    const math = block.raw.trim().match(/^(?:\$\$([\s\S]*?)\$\$|\\\[([\s\S]*?)\\\])$/);
    if (math) {
      el.replaceChildren(); el.classList.add("report-formula");
      const preview = document.createElement("div");
      preview.className = "report-formula-preview";
      preview.setAttribute("aria-label", "Предпросмотр формулы");
      const details = document.createElement("details"); details.open = focus;
      const summary = document.createElement("summary"); summary.textContent = "Редактировать формулу · LaTeX";
      const label = document.createElement("label"); label.textContent = "Формула LaTeX";
      const field = document.createElement("textarea");
      field.className = "report-formula-input";
      field.value = (math[1] ?? math[2]).trim();
      field.rows = 3; field.placeholder = "Например: E = mc^2";
      label.append(field);
      const update = () => { preview.innerHTML = this.render(`$$\n${field.value || "\\phantom{x}"}\n$$`); };
      field.oninput = () => { save(`$$\n${field.value}\n$$`); update(); };
      field.onkeydown = e => {
        if (e.isComposing) return;
        if (e.key === "Escape" || (e.key === "Enter" && (e.ctrlKey || e.metaKey))) {
          e.preventDefault(); e.stopPropagation(); details.open = false; summary.focus();
        }
      };
      const next = document.createElement("button");
      next.type = "button"; next.className = "btn btn-small";
      next.textContent = "Продолжить под формулой"; next.onclick = finish;
      details.append(summary, label, next); el.append(preview, details); update();
      if (focus) field.focus();
      return true;
    }
    if (tasks.length && tasks.every(Boolean)) {
      el.replaceChildren();
      el.classList.add("report-tasks");
      const persist = () => save(tasks.map(t => `${t[1]}[${t[2]}] ${t[3]}`).join("\n"));
      tasks.forEach((task, row) => {
        const line = document.createElement("div"); line.className = "report-task-row";
        const check = document.createElement("input");
        check.type = "checkbox"; check.checked = task[2] !== " ";
        check.setAttribute("aria-label", `Выполнено: ${task[3] || "задача"}`);
        check.onchange = () => { task[2] = check.checked ? "x" : " "; persist(); };
        const field = document.createElement("textarea");
        field.rows = 1; field.className = "report-task-text";
        field.setAttribute("aria-label", `Текст задачи ${row + 1}`);
        field.placeholder = "Задача"; field.value = task[3];
        const resize = () => { field.style.height = "auto"; field.style.height = `${field.scrollHeight}px`; };
        field.oninput = () => { task[3] = field.value.replace(/\n/g, " "); persist(); resize(); };
        field.onkeydown = e => {
          if (e.isComposing) return;
          if (e.key === "Backspace" && field.selectionStart === 0 && field.selectionEnd === 0) {
            e.preventDefault(); e.stopPropagation();
            if (row > 0) {
              const previous = tasks[row - 1];
              const caret = previous[3].length;
              previous[3] += task[3];
              tasks.splice(row, 1); persist(); this.visualBlock(el, index);
              const target = el.querySelectorAll("textarea")[row - 1];
              target.focus(); target.setSelectionRange(caret, caret);
            } else if (!field.value) {
              tasks.splice(row, 1);
              if (tasks.length) { persist(); this.visualBlock(el, index, true); }
              else {
                block.raw = ""; block.type = "paragraph";
                this.changed(); this.paint(index);
              }
            } else {
              // The first item has no previous task; keep its text as a paragraph.
              block.raw = task[3] + "\n\n"; block.type = "paragraph";
              if (tasks.length > 1) this.blocks.splice(index + 1, 0, { raw: tasks.slice(1).map(t => `${t[1]}[${t[2]}] ${t[3]}`).join("\n") + "\n\n", type: "list" });
              this.changed(); this.paint(index);
              const target = this.host.querySelector(".report-block-input");
              target?.setSelectionRange(0, 0);
            }
            return;
          }
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault(); e.stopPropagation();
            if (!field.value.trim()) {
              tasks.splice(row, 1); persist(); finish(); return;
            }
            const after = field.value.slice(field.selectionEnd);
            task[3] = field.value.slice(0, field.selectionStart);
            tasks.splice(row + 1, 0, ["", task[1], " ", after]);
            persist(); this.visualBlock(el, index);
            el.querySelectorAll("textarea")[row + 1].focus();
          } else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); field.blur(); el.focus(); }
        };
        line.append(check, field); el.append(line);
        requestAnimationFrame(resize);
      });
      if (focus) el.querySelector("textarea")?.focus();
      return true;
    }
    if (token?.type !== "table") return false;
    el.replaceChildren(); el.classList.add("report-table-block");
    // Keep cell Markdown and alignment; only serialize after a real edit.
    const rows = [token.header.map(c => c.text), ...token.rows.map(row => row.map(c => c.text))];
    const align = token.align;
    const persist = () => {
      const encode = value => value.replace(/(?<!\\)\|/g, "\\|").replace(/\n/g, "<br>");
      const line = row => `| ${row.map(encode).join(" | ")} |`;
      save([line(rows[0]), line(rows[0].map((_, i) => align[i] === "center" ? ":---:" : align[i] === "right" ? "---:" : align[i] === "left" ? ":---" : "---")), ...rows.slice(1).map(line)].join("\n"));
    };
    this.closeTableMenu?.();
    let selected = null;
    const focusCell = (r, c) => el.querySelector(`tbody [data-row="${r}"][data-column="${c}"] textarea`)?.focus();
    const select = (axis, at) => {
      selected = { axis, at };
      el.querySelectorAll("[data-row], [data-column]").forEach(cell => {
        const active = axis === "table" || (axis === "row" ? cell.dataset.row === String(at) : cell.dataset.column === String(at));
        cell.classList.toggle("report-table-target", active);
        if (cell.matches("button")) cell.setAttribute("aria-pressed", String(active));
      });
    };
    const repaint = (r = 1, c = 0) => { persist(); this.visualBlock(el, index); focusCell(Math.min(r, rows.length - 1), Math.min(c, rows[0].length - 1)); };
    const move = (axis, from, to) => {
      if (from === to || to < 0 || (axis === "row" && (from === 0 || to === 0))) return;
      if (axis === "column") {
        if (from === 0 || to === 0 || to >= rows[0].length) return;
        rows.forEach(row => row.splice(to, 0, row.splice(from, 1)[0]));
        align.splice(to, 0, align.splice(from, 1)[0]);
      } else {
        if (to >= rows.length) return;
        rows.splice(to, 0, rows.splice(from, 1)[0]);
      }
      repaint(axis === "row" ? to : 1, axis === "column" ? to : 0);
    };
    const showMenu = (axis, at, trigger, point = null) => {
      this.closeTableMenu?.(); select(axis, at);
      const menu = document.createElement("div"); menu.className = "report-table-context";
      menu.tabIndex = -1; menu.setAttribute("popover", "manual");
      menu.setAttribute("role", "group"); menu.setAttribute("aria-label", "Действия с выделением таблицы");
      const close = () => { menu.remove(); document.removeEventListener("pointerdown", outside); this.closeTableMenu = null; };
      const outside = e => { if (!menu.contains(e.target) && !trigger.contains(e.target)) close(); };
      this.closeTableMenu = close;
      const action = (label, run, disabled = false, danger = false) => {
        const button = document.createElement("button"); button.type = "button"; button.className = `btn btn-small${danger ? " btn-danger" : ""}`;
        button.textContent = label; button.disabled = disabled;
        button.onclick = () => { close(); run(); }; menu.append(button);
      };
      if (axis !== "table") {
        const column = axis === "column";
        if (!column) action("Вставить строку снизу", () => { rows.splice(at + 1, 0, rows[0].map(() => "")); repaint(at + 1, 0); });
        action(column ? "Переместить влево" : "Переместить вверх", () => move(axis, at, at - 1), at <= 1);
        action(column ? "Переместить вправо" : "Переместить вниз", () => move(axis, at, at + 1), at >= (column ? rows[0].length : rows.length) - 1 || at === 0);
      }
      const requestDelete = (whole = false) => {
        const panel = document.createElement("div"); panel.className = "report-table-confirm";
        panel.setAttribute("role", "group"); panel.setAttribute("aria-label", "Подтверждение удаления");
        const text = document.createElement("p");
        whole ||= axis === "column" && rows[0].length === 1;
        text.textContent = whole ? "Удалить таблицу целиком вместе с содержимым?" : `Удалить ${axis === "column" ? "колонку" : "строку"} ${at + (axis === "column" ? 1 : 0)} вместе с содержимым?`;
        const cancel = document.createElement("button"); cancel.type = "button"; cancel.className = "btn btn-small"; cancel.textContent = "Отмена";
        const remove = document.createElement("button"); remove.type = "button"; remove.className = "btn btn-small btn-danger"; remove.textContent = "Удалить";
        const unblock = () => { el.querySelector(".report-table-scroll").inert = false; panel.remove(); };
        cancel.onclick = () => { unblock(); trigger.focus(); };
        remove.onclick = () => {
          unblock();
          if (whole) { block.raw = ""; block.type = "paragraph"; this.changed(); this.paint(index); }
          else if (axis === "column") { rows.forEach(row => row.splice(at, 1)); align.splice(at, 1); repaint(1, at); }
          else { rows.splice(at, 1); repaint(at, 0); }
        };
        panel.append(text, cancel, remove); el.prepend(panel);
        el.querySelector(".report-table-scroll").inert = true; cancel.focus();
        panel.onkeydown = e => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancel.click(); } };
      };
      action(axis === "column" ? "Удалить колонку" : "Удалить строку", () => requestDelete(), at === 0, true);
      action("Удалить таблицу", () => requestDelete(true), false, true);
      (this.host.closest(".modal-panel") || el).append(menu);
      menu.showPopover();
      const rect = trigger.getBoundingClientRect();
      const x = point?.x ?? rect.left, y = point?.y ?? rect.bottom;
      menu.style.left = `${Math.max(8, Math.min(x + 4, window.innerWidth - menu.offsetWidth - 8))}px`;
      menu.style.top = `${Math.max(8, Math.min(y + 4, window.innerHeight - menu.offsetHeight - 8))}px`;
      document.addEventListener("pointerdown", outside);
      menu.onkeydown = e => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); trigger.focus(); } };
      (menu.querySelector("button:not(:disabled)") || menu).focus();
    };
    const table = document.createElement("table");
    // ponytail: character counts estimate readable widths; measure fonts if exact fitting is needed.
    const widths = rows[0].map((_, c) => Math.min(320, Math.max(96, ...rows.map(row => row[c].length * 7 + 24))));
    const columns = document.createElement("colgroup");
    widths.forEach(width => { const col = document.createElement("col"); col.style.width = `${width}px`; columns.append(col); });
    table.append(columns);
    const body = document.createElement("tbody");
    rows.forEach((row, r) => {
      const tr = document.createElement("tr");
      row.forEach((value, c) => {
        const cell = document.createElement(r === 0 || c === 0 ? "th" : "td");
        const axis = r === 0 ? "column" : c === 0 ? "row" : null;
        const at = axis === "column" ? c : r;
        cell.ondblclick = e => { if (axis) { e.preventDefault(); select(axis, at); } };
        cell.dataset.row = r; cell.dataset.column = c;
        cell.oncontextmenu = e => {
          const choice = axis ? {axis, at} : selected || { axis: "row", at: r };
          if (!choice) return;
          e.preventDefault(); e.stopPropagation(); showMenu(choice.axis, choice.at, cell, { x: e.clientX, y: e.clientY });
        };
        const field = document.createElement("textarea");
        field.rows = 1; field.value = value.replace(/\\\|/g, "|");
        field.setAttribute("aria-label", `${r === 0 ? "Заголовок" : `Строка ${r}`}, столбец ${c + 1}`);
        field.oninput = () => { rows[r][c] = field.value; persist(); };
        field.onkeydown = e => {
          if (e.isComposing) return;
          if (axis && (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10"))) { e.preventDefault(); e.stopPropagation(); showMenu(axis, at, field); return; }
          if (axis && axis !== "table" && e.altKey && ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)) { e.preventDefault(); move(axis, at, at + (["ArrowLeft", "ArrowUp"].includes(e.key) ? -1 : 1)); return; }
          if (e.key === "Tab" && !e.shiftKey && r === rows.length - 1 && c === row.length - 1) {
            e.preventDefault(); rows.push(row.map(() => "")); repaint(r + 1, 0);
          } else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.closeTableMenu?.(); selected = null; el.querySelectorAll(".report-table-target").forEach(x => x.classList.remove("report-table-target")); field.blur(); el.focus(); }
        };
        cell.append(field); tr.append(cell);
      });
      body.append(tr);
    });
    table.append(body);
    // Holding a cell starts axis-constrained dragging; ordinary text selection stays native.
    table.onpointerdown = e => {
      if (e.button !== 0) return;
      const target = e.target.closest("[data-row], [data-column]");
      if (!target) return;
      const isHandle = target.matches("th");
      const fromRow = Number(target.dataset.row), fromColumn = Number(target.dataset.column);
      const startX = e.clientX, startY = e.clientY;
      let armed = isHandle, dragging = false, axis = isHandle ? (fromRow === 0 ? "column" : "row") : null;
      let destination = null;
      const timer = setTimeout(() => { armed = true; }, 350);
      const cleanup = () => {
        clearTimeout(timer); window.removeEventListener("pointermove", track); window.removeEventListener("pointerup", end); window.removeEventListener("pointercancel", cancel);
        table.classList.remove("report-table-dragging"); el.querySelectorAll(".report-table-drop").forEach(x => x.classList.remove("report-table-drop"));
      };
      const track = event => {
        const dx = event.clientX - startX, dy = event.clientY - startY;
        if (Math.hypot(dx, dy) < 6) return;
        if (!armed) { cleanup(); return; }
        axis ||= Math.abs(dx) > Math.abs(dy) ? "column" : "row";
        if (axis === "row" && fromRow === 0) { cleanup(); return; }
        dragging = true; event.preventDefault(); window.getSelection()?.removeAllRanges();
        table.classList.add("report-table-dragging");
        const over = document.elementFromPoint(event.clientX, event.clientY)?.closest("[data-row], [data-column]");
        destination = over && table.contains(over) && over.dataset[axis] !== undefined ? Number(over.dataset[axis]) : null;
        el.querySelectorAll(".report-table-drop").forEach(x => x.classList.remove("report-table-drop"));
        if (destination !== null && !(axis === "row" && destination === 0)) {
          select(axis, axis === "row" ? fromRow : fromColumn);
          el.querySelectorAll(`[data-${axis}="${destination}"]`).forEach(x => x.classList.add("report-table-drop"));
        }
      };
      const end = () => { cleanup(); if (dragging && destination !== null) move(axis, axis === "row" ? fromRow : fromColumn, destination); };
      const cancel = () => cleanup();
      window.addEventListener("pointermove", track, { passive: false }); window.addEventListener("pointerup", end, { once: true }); window.addEventListener("pointercancel", cancel, { once: true });
    };
    const scroll = document.createElement("div"); scroll.className = "report-table-scroll";
    const grid = document.createElement("div"); grid.className = "report-table-grid";
    table.style.minWidth = `${widths.reduce((sum, width) => sum + width, 0)}px`;
    const addColumn = document.createElement("button");
    addColumn.type = "button"; addColumn.className = "report-table-add-column";
    addColumn.textContent = "+";
    addColumn.setAttribute("aria-label", "Добавить колонку");
    const hint = document.createElement("span");
    hint.className = "report-table-hint"; hint.textContent = "Добавить колонку";
    hint.setAttribute("aria-hidden", "true"); addColumn.append(hint);
    addColumn.onclick = () => {
      rows.forEach(row => row.push("")); persist(); this.visualBlock(el, index);
      el.querySelectorAll("tbody > tr")[0].querySelectorAll("textarea")[rows[0].length - 1].focus();
    };
    const addRow = document.createElement("button");
    addRow.type = "button"; addRow.className = "report-table-add-column report-table-add-row";
    addRow.setAttribute("aria-label", "Добавить строку"); addRow.textContent = "+";
    const rowHint = hint.cloneNode(true); rowHint.textContent = "Добавить строку";
    addRow.append(rowHint);
    addRow.onclick = () => {
      rows.push(rows[0].map(() => "")); persist(); this.visualBlock(el, index);
      el.querySelectorAll("tbody > tr")[rows.length - 1].querySelector("textarea").focus();
    };
    grid.append(table, addColumn, addRow); scroll.append(grid); el.append(scroll);
    const next = document.createElement("button");
    next.type = "button"; next.className = "report-block-placeholder report-table-next";
    next.textContent = "Напишите или введите / для выбора блока…";
    next.setAttribute("aria-label", "Продолжить под таблицей"); next.onclick = finish;
    el.append(next);
    if (focus) el.querySelector("textarea")?.focus();
    return true;
  }
  paint(focusIndex = null) {
    this.closeBlockMenu?.();
    this.closeTableMenu?.();
    this.host.replaceChildren();
    this.blocks.forEach((block, index) => {
      const el = document.createElement("div");
      el.className = "report-block";
      el.dataset.blockIndex = index;
      el.tabIndex = this.readOnly ? -1 : 0;
      el.setAttribute("aria-label", "Редактировать блок");
      el.innerHTML = this.renderBlock(block.raw);
      this.visualBlock(el, index);
      el.addEventListener("click", e => {
        if (this.readOnly || window.getSelection()?.toString() || e.target.closest("a, button, input, textarea, video, details, .report-formula-preview")) return;
        this.edit(el, index);
      });
      el.addEventListener("keydown", e => { if (!this.readOnly && e.key === "Enter" && e.target === el) { e.preventDefault(); this.edit(el, index); } });
      this.host.append(el);
      if (!this.readOnly && block.type === "heading" && (!this.blocks[index + 1] || this.blocks[index + 1].type === "heading")) {
        const add = document.createElement("button");
        add.className = "report-block-placeholder";
        add.type = "button";
        add.textContent = "Напишите или введите / для выбора блока…";
        add.onclick = () => { this.blocks[index].raw = this.blocks[index].raw.trimEnd() + "\n\n"; this.blocks.splice(index + 1, 0, { raw: "", type: "paragraph" }); this.paint(index + 1); };
        this.host.append(add);
      }
      if (index === focusIndex) this.edit(el, index);
    });
    const add = document.createElement("button");
    add.className = "report-block-placeholder";
    add.type = "button";
    add.textContent = "Добавить блок";
    add.onclick = () => {
      if (this.blocks.length) this.blocks.at(-1).raw = this.blocks.at(-1).raw.trimEnd() + "\n\n";
      this.blocks.push({ raw: "", type: "paragraph" }); this.paint(this.blocks.length - 1);
      this.host.querySelector(".report-block-plus")?.click();
    };
    if (!this.readOnly && !this.host.lastElementChild?.classList.contains("report-table-block")) this.host.append(add);
    this.hookLinks(this.host);
    this.updateToc();
  }
  edit(el, index) {
    if (el.classList.contains("report-formula")) el.querySelector("details").open = true;
    if (el.querySelector("textarea")) { el.querySelector("textarea").focus(); return; }
    if (this.visualBlock(el, index, true)) return;
    const block = this.blocks[index];
    const input = document.createElement("textarea");
    input.className = "report-block-input";
    input.setAttribute("aria-label", "Текст блока");
    input.placeholder = "Напишите или введите / для выбора блока…";
    input.value = block.raw.trimEnd();
    const resize = () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight + 4}px`; };
    let lastValue = input.value;
    const commit = () => {
      if (input.value === lastValue) return;
      lastValue = input.value;
      block.raw = input.value + "\n\n";
      block.type = reportBlocks(block.raw)[0]?.type || "paragraph"; this.changed();
    };
    input.oninput = event => {
      commit(); resize();
      if (!event.isComposing && /^\/[^\n]*$/.test(input.value)) openMenu(input.value.slice(1));
      else this.closeBlockMenu?.();
      if (/(?:^|\s)[\\/]agent$/.test(input.value)) {
        input.value = input.value.replace(/[\\/]agent$/, ""); commit();
        this.onAgent("");
      }
    };
    input.onblur = () => {
      if (!input.isConnected) return;
      this.closeBlockMenu?.();
      commit();
      // Update only this block so clicking another block keeps its focus.
      el.innerHTML = this.renderBlock(block.raw);
      this.visualBlock(el, index);
      this.hookLinks(el);
    };
    input.onkeydown = e => {
      if (e.isComposing) return;
      if (this.blockMenuKey && this.blockMenuKey(e)) return;
      if (e.key === "Escape" || (e.key === "Enter" && (e.metaKey || e.ctrlKey))) {
        e.preventDefault(); e.stopPropagation(); input.blur(); el.focus(); return;
      }
      if (e.key === "Enter" && !e.shiftKey && block.type === "list") {
        const start = input.value.lastIndexOf("\n", input.selectionStart - 1) + 1;
        const line = input.value.slice(start, input.selectionStart);
        const match = line.match(/^(\s*)([-*+]|\d+\.) (?:\[[ xX]\] )?/);
        if (match) {
          e.preventDefault();
          if (line === match[0]) input.setRangeText("", start, input.selectionEnd, "end");
          else {
            const marker = /\d/.test(match[2]) ? `${parseInt(match[2]) + 1}.` : match[2];
            input.setRangeText(`\n${match[1]}${marker} ${match[0].includes("[") ? "[ ] " : ""}`, input.selectionStart, input.selectionEnd, "end");
          }
          commit(); resize(); return;
        }
      }
      if (e.key !== "Enter" || e.shiftKey || ["code", "table", "html", "list"].includes(block.type)) return;
      e.preventDefault();
      const before = input.value.slice(0, input.selectionStart);
      const after = input.value.slice(input.selectionEnd);
      input.onblur = null;
      block.raw = before + "\n\n";
      this.blocks.splice(index + 1, 0, { raw: after, type: "paragraph" });
      this.changed(); this.paint(index + 1);
    };
    input.onpaste = e => this.onPaste(e, input, () => { commit(); resize(); });
    const plus = document.createElement("button");
    plus.type = "button";
    plus.className = "report-block-plus";
    plus.textContent = "+";
    plus.setAttribute("aria-label", "Выбрать тип блока");
    plus.onmousedown = e => e.preventDefault();
    plus.onclick = () => { input.focus(); openMenu(""); };
    const openMenu = query => {
      this.closeBlockMenu?.();
      const menu = document.createElement("div");
      menu.className = "report-block-menu";
      menu.setAttribute("role", "listbox");
      menu.setAttribute("aria-label", "Тип блока");
      menu.id = "report-block-types";
      const title = document.createElement("div");
      title.className = "report-block-menu-title";
      title.textContent = "Тип блока · ↑ ↓ выбрать · Enter вставить · Esc закрыть";
      menu.append(title);
      const matches = BLOCK_TYPES.filter(([label, aliases]) => `${label} ${aliases}`.toLowerCase().includes(query.toLowerCase()));
      let active = 0;
      const select = item => {
        this.closeBlockMenu();
        const [, , , raw, type, cursor = raw.length] = item;
        // A slash query is replaced; opening with + preserves existing content.
        const content = input.value.startsWith("/") ? "" : input.value;
        input.value = raw + content;
        block.type = type;
        commit();
        block.type = type;
        if (type === "table" || type === "blockMath" || (type === "list" && raw === "- [ ] ")) {
          input.onblur = null; this.visualBlock(el, index, true); return;
        }
        input.focus(); input.setSelectionRange(cursor, cursor); resize();
      };
      const buttons = matches.map((item, i) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "report-block-menu-item";
        button.id = `report-block-type-${i}`;
        button.setAttribute("role", "option");
        button.tabIndex = -1;
        const icon = document.createElement("span");
        icon.setAttribute("aria-hidden", "true"); icon.textContent = item[2];
        const label = document.createElement("span"); label.textContent = item[0];
        button.append(icon, label);
        button.onmousedown = e => e.preventDefault();
        button.onclick = () => select(item);
        menu.append(button);
        return button;
      });
      if (!matches.length) {
        const empty = document.createElement("p");
        empty.textContent = "Блоки не найдены"; menu.append(empty);
      }
      const highlight = () => {
        buttons.forEach((button, i) => button.setAttribute("aria-selected", String(i === active)));
        if (buttons[active]) {
          input.setAttribute("aria-activedescendant", buttons[active].id);
          buttons[active].scrollIntoView({ block: "nearest" });
        }
      };
      const panel = this.host.closest(".modal-panel") || this.host;
      panel.append(menu);
      const position = () => {
        const bounds = input.getBoundingClientRect();
        menu.style.width = `${Math.min(360, window.innerWidth - 24)}px`;
        menu.style.left = `${Math.max(12, Math.min(bounds.left, window.innerWidth - menu.offsetWidth - 12))}px`;
        const below = window.innerHeight - bounds.bottom - 12;
        const above = bounds.top - 12;
        const height = Math.min(320, Math.max(below, above));
        menu.style.maxHeight = `${height}px`;
        menu.style.top = `${below >= Math.min(320, menu.scrollHeight) ? bounds.bottom + 4 : Math.max(12, bounds.top - Math.min(height, menu.scrollHeight) - 4)}px`;
      };
      position();
      document.addEventListener("scroll", position, true);
      window.addEventListener("resize", position);
      input.setAttribute("aria-controls", menu.id);
      input.setAttribute("aria-expanded", "true");
      input.setAttribute("aria-haspopup", "listbox");
      const dismiss = e => { if (!el.contains(e.target) && !menu.contains(e.target)) this.closeBlockMenu?.(); };
      document.addEventListener("pointerdown", dismiss);
      this.closeBlockMenu = () => {
        menu.remove();
        document.removeEventListener("scroll", position, true);
        window.removeEventListener("resize", position);
        document.removeEventListener("pointerdown", dismiss);
        for (const name of ["aria-controls", "aria-expanded", "aria-activedescendant", "aria-haspopup"]) input.removeAttribute(name);
        this.blockMenuKey = null; this.closeBlockMenu = null;
      };
      this.blockMenuKey = e => {
        if (!["ArrowDown", "ArrowUp", "Enter", "Escape", "Tab"].includes(e.key)) return false;
        if (e.key === "Tab") { this.closeBlockMenu(); return false; }
        e.preventDefault(); e.stopPropagation();
        if (e.key === "Escape") this.closeBlockMenu();
        else if (e.key === "Enter") { if (matches[active]) select(matches[active]); }
        else if (matches.length) { active = (active + (e.key === "ArrowDown" ? 1 : -1) + matches.length) % matches.length; highlight(); }
        return true;
      };
      highlight();
    };
    el.replaceChildren(plus, input); input.focus(); resize();
  }
}
