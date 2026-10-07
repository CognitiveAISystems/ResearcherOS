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

export class ReportEditor {
  constructor(host, { render, onChange, onAgent, onPaste, hookLinks, readOnly = false }) {
    Object.assign(this, { host, render, onChange, onAgent, onPaste, hookLinks, readOnly });
    this.blocks = [];
    host.addEventListener("contextmenu", e => {
      if (this.readOnly) return;
      const selected = this.selection();
      if (!selected) return;
      e.preventDefault();
      this.agentMenu(selected, e.clientX, e.clientY);
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
    const button = document.createElement("button");
    button.type = "button";
    button.className = "report-agent-menu btn";
    button.textContent = "Сформулировать постановку с агентом";
    button.style.left = `${Math.min(x, window.innerWidth - 340)}px`;
    button.style.top = `${Math.min(y, window.innerHeight - 70)}px`;
    button.onclick = () => { button.remove(); this.onAgent(selected); };
    document.body.append(button);
    setTimeout(() => document.addEventListener("pointerdown", e => { if (e.target !== button) button.remove(); }, { once: true }), 0);
  }
  setValue(source) { this.blocks = reportBlocks(source); this.paint(); }
  getValue() { return this.blocks.map(b => b.raw).join(""); }
  changed() { this.onChange(this.getValue()); }
  renderBlock(raw) {
    const links = marked.lexer(this.getValue()).links || {};
    const definitions = Object.entries(links).map(([name, link]) => `[${name}]: <${link.href}>${link.title ? ` ${JSON.stringify(link.title)}` : ""}`).join("\n");
    return this.render(raw + (definitions ? "\n\n" + definitions : ""));
  }
  paint(focusIndex = null) {
    this.host.replaceChildren();
    this.blocks.forEach((block, index) => {
      const el = document.createElement("div");
      el.className = "report-block";
      el.tabIndex = this.readOnly ? -1 : 0;
      el.setAttribute("aria-label", "Редактировать блок");
      el.innerHTML = this.renderBlock(block.raw);
      el.addEventListener("click", e => {
        if (this.readOnly || window.getSelection()?.toString() || e.target.closest("a, button, input, video")) return;
        this.edit(el, index);
      });
      el.addEventListener("keydown", e => { if (!this.readOnly && e.key === "Enter" && e.target === el) { e.preventDefault(); this.edit(el, index); } });
      this.host.append(el);
      if (!this.readOnly && block.type === "heading" && (!this.blocks[index + 1] || this.blocks[index + 1].type === "heading")) {
        const add = document.createElement("button");
        add.className = "report-block-placeholder";
        add.textContent = "Напишите или введите /agent…";
        add.onclick = () => { this.blocks[index].raw = this.blocks[index].raw.trimEnd() + "\n\n"; this.blocks.splice(index + 1, 0, { raw: "", type: "paragraph" }); this.paint(index + 1); };
        this.host.append(add);
      }
      if (index === focusIndex) this.edit(el, index);
    });
    const add = document.createElement("button");
    add.className = "report-block-placeholder";
    add.textContent = "+ Добавить блок";
    add.onclick = () => {
      if (this.blocks.length) this.blocks.at(-1).raw = this.blocks.at(-1).raw.trimEnd() + "\n\n";
      this.blocks.push({ raw: "", type: "paragraph" }); this.paint(this.blocks.length - 1);
    };
    if (!this.readOnly) this.host.append(add);
    this.hookLinks(this.host);
  }
  edit(el, index) {
    if (el.querySelector("textarea")) return;
    const block = this.blocks[index];
    const input = document.createElement("textarea");
    input.className = "report-block-input";
    input.setAttribute("aria-label", "Текст блока");
    input.value = block.raw.trimEnd();
    const resize = () => { input.style.height = "auto"; input.style.height = `${input.scrollHeight + 4}px`; };
    let lastValue = input.value;
    const commit = () => {
      if (input.value === lastValue) return;
      lastValue = input.value;
      block.raw = input.value + "\n\n"; this.changed();
    };
    input.oninput = () => {
      commit(); resize();
      if (/(?:^|\s)[\\/]agent$/.test(input.value)) {
        input.value = input.value.replace(/[\\/]agent$/, ""); commit();
        this.onAgent("");
      }
    };
    input.onblur = () => {
      if (!input.isConnected) return;
      commit();
      // Update only this block so clicking another block keeps its focus.
      el.innerHTML = this.renderBlock(block.raw);
      this.hookLinks(el);
    };
    input.onkeydown = e => {
      if (e.key === "Escape" || (e.key === "Enter" && (e.metaKey || e.ctrlKey))) {
        e.preventDefault(); e.stopPropagation(); input.blur(); el.focus(); return;
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
    el.replaceChildren(input); input.focus(); resize();
  }
}
