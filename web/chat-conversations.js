const ICONS = {
  compose: '<path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L9 17l-4 1 1-4Z"/>',
  folder: '<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/><path d="M3 10h18"/>',
  chat: '<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8Z"/>',
  card: '<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M8 8h8M8 12h6M8 16h4"/>',
};

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = ICONS[name];
  return svg;
}

/* Conversation selection belongs to ResearcherOS, independently of ACP sessions. */
export class ChatConversations {
  constructor({ api, sidebar, controls, scope, input, changed, projectName, main = false, renderNavigation, titleForScope }) {
    Object.assign(this, { api, sidebar, controls, scope, input, changed, projectName, main, renderNavigation, titleForScope });
    this.row = null;
    this.rows = [];
    this.projects = [];
    this.epoch = 0;
    this.currentProjectOnly = false;
    this.drafts = new Map();
    this.collapsedProjects = new Set(main && renderNavigation ? ["global"] : []);
    this.navigationGroups = new Set(["global"]);
    this.contextScope = null; this.contextSelections = new Map();
    this.layout = sidebar.closest(".conversation-layout");
    this.log = this.layout.querySelector('.agent-chat-log');
    try { document.documentElement.dataset.chatBlink = localStorage.getItem('researchos-chat-blink') || 'on'; } catch { /* Private storage. */ }
    this.log?.addEventListener('scroll', () => this.scheduleRead(), {passive: true});
    window.addEventListener('focus', () => this.scheduleRead());
    window.addEventListener('blur', () => this.scheduleRead());
    document.addEventListener('visibilitychange', () => this.scheduleRead());
    if (this.log) new MutationObserver(() => this.scheduleRead()).observe(this.log, {childList: true, subtree: true});
    window.addEventListener('conversation-read', event => {
      const row = event.detail;
      this.rows = this.rows.map(r => r.id === row.id ? row : r);
      if (this.row?.id === row.id) this.row = row;
      this.render(this.live);
    });
    this.sendButton = this.input.form?.querySelector('.agent-chat-send');
    this.sendIcon = this.sendButton?.innerHTML;
    this.sendLabel = this.sendButton?.getAttribute('aria-label');
    this.sendButton?.addEventListener('click', async event => {
      if (!this.live) return;
      event.preventDefault(); event.stopImmediatePropagation();
      const cid = this.row?.id;
      if (!cid || this.live.cancelled) return;
      this.live = {...this.live, cancelled: true}; this.syncSendButton();
      try {
        await this.api.cancelConversation(cid);
        if (this.row?.id === cid) await this.changed();
      } catch (error) {
        if (this.row?.id === cid) {
          this.live = {...this.live, cancelled: false}; this.syncSendButton();
          this.controls.textContent = error.message;
        }
      }
    });
    if (!main) {
      this.layout.classList.add("conversation-left");
      this.layout.prepend(this.layout.querySelector(".conversation-rail"), sidebar);
      this.layout.querySelector(".conversation-nav-toggle svg path").setAttribute("d", "M9 4v16");
    }
    attachConversationListResize(this.layout, sidebar, main ? "main" : "card", api);
    this.navigationTrigger = this.layout.querySelector("[data-chat-navigation]");
    this.navigationTrigger?.addEventListener("click", () => this.showNavigation(this.layout.dataset.navigationOpen !== "true"));
    this.filterTrigger = this.layout.querySelector("[data-current-project]");
    this.filterTrigger?.addEventListener("click", () => {
      this.currentProjectOnly = !this.currentProjectOnly;
      this.filterTrigger.setAttribute("aria-pressed", String(this.currentProjectOnly));
      if (this.renderNavigation && !this.contextScope) { this.renderSidebar(); return; }
      this.epoch++;
      void this.changed({open: false});
    });
    sidebar.addEventListener("toggle", event => {
      const group = event.target;
      if (!group.dataset?.projectGroup) return;
      if (group.open) this.collapsedProjects.delete(group.dataset.projectGroup);
      else this.collapsedProjects.add(group.dataset.projectGroup);
    }, true);
    sidebar.addEventListener("keydown", event => {
      if (event.key === "Escape" && !event.target.closest("[popover]:popover-open")) { event.preventDefault(); this.showNavigation(false, true); }
    });
    document.addEventListener("keydown", event => {
      const menu = sidebar.querySelector('.conversation-actions-popover:popover-open');
      if (event.key !== "Escape" || !menu) return;
      event.preventDefault(); event.stopImmediatePropagation(); menu.hidePopover();
      menu.parentElement.querySelector('[data-chat-menu]').focus();
    }, true);
    sidebar.addEventListener("click", event => {
      const button = event.target.closest("[data-conversation]");
      if (button) void this.select(this.rows.find(r => r.id === button.dataset.conversation));
      if (event.target.closest("[data-new-chat]")) void this.newChat(event.target.closest("[data-global-chat]") && !this.contextScope ? { project_id: null } : undefined);
      if (event.target.closest("[data-move-chat]")) void this.moveChat();
    });
    sidebar.addEventListener("dragstart", event => {
      if (this.main && this.contextScope) { event.preventDefault(); return; }
      const entry = event.target.closest("[data-conversation]");
      const row = this.rows.find(r => r.id === entry?.dataset.conversation);
      if (!row || row.pending || row.kind === "git_sync") { event.preventDefault(); return; }
      this.dragging = true;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("application/x-researcheros-chat", row.id);
      entry.classList.add("is-dragging");
    });
    sidebar.addEventListener("dragover", event => {
      if (!event.dataTransfer.types.includes("application/x-researcheros-chat")) return;
      const target = event.target.closest("[data-chat-drop]");
      if (!target) return;
      event.preventDefault(); event.dataTransfer.dropEffect = "move";
      sidebar.querySelectorAll('.is-drop-target').forEach(el => el.classList.toggle('is-drop-target', el === target));
      target.classList.add("is-drop-target");
      const group = target.closest(".conversation-group");
      if (group) {
        group.open = true;
        group.querySelector(":scope > .unified-project-chats")?.removeAttribute("hidden");
        const toggle = group.querySelector("[data-chat-project-toggle]");
        toggle?.setAttribute("aria-expanded", "true");
        if (toggle) this.collapsedProjects.delete(toggle.dataset.chatProjectToggle);
      }
      if (target.dataset.projectId && !target.dataset.cardId) void this.showDropCards(target, group);
    });
    sidebar.addEventListener("dragleave", event => {
      const target = event.target.closest("[data-chat-drop]");
      if (target && !target.contains(event.relatedTarget)) target.classList.remove("is-drop-target");
    });
    sidebar.addEventListener("dragend", () => this.clearDropTargets());
    sidebar.addEventListener("drop", async event => {
      if (this.main && this.contextScope) { event.preventDefault(); return; }
      const target = event.target.closest("[data-chat-drop]");
      const cid = event.dataTransfer.getData("application/x-researcheros-chat");
      if (!target || !cid) return;
      event.preventDefault();
      const scope = {project_id: target.dataset.projectId || null,
        board_id: target.dataset.boardId || null, card_id: target.dataset.cardId || null};
      this.clearDropTargets();
      try {
        const result = await this.api.moveConversation(cid, scope);
        if (this.row?.id === cid) this.row = result.item;
        await this.changed();
      } catch (error) { this.controls.textContent = error.message; }
    });
    controls.addEventListener("click", async event => {
      const option = event.target.closest("[data-permission-option]");
      if (!this.row || !option) return;
      const cid = this.row.id;
      try {
        await api.decideConversationPermission(cid, option.dataset.permission, option.dataset.permissionOption);
        await this.changed();
      } catch (error) { controls.textContent = error.message; }
    });
  }

  clearDropTargets() {
    this.dragging = false;
    this.sidebar.querySelectorAll('.is-drop-target,.is-dragging').forEach(el => el.classList.remove('is-drop-target', 'is-dragging'));
    this.sidebar.querySelectorAll('.conversation-drop-cards').forEach(el => el.remove());
  }

  async showDropCards(target, group) {
    if (!group || !this.api.getProject || group.querySelector('.conversation-drop-cards')) return;
    const cards = document.createElement('div');
    cards.className = 'conversation-drop-cards'; cards.setAttribute('popover', 'manual'); group.append(cards);
    try {
      const project = await this.api.getProject(target.dataset.projectId);
      if (!cards.isConnected) return;
      for (const board of Object.values(project.boards || {})) for (const card of board.cards || []) {
        const item = document.createElement('div');
        item.className = 'conversation-drop-card'; item.dataset.chatDrop = '';
        item.dataset.projectId = project.id; item.dataset.boardId = board.id; item.dataset.cardId = card.id;
        item.append(icon('card'), document.createTextNode(card.title)); cards.append(item);
      }
      if (cards.childElementCount) {
        const rect = target.getBoundingClientRect();
        cards.style.left = `${Math.max(16, rect.left - 260)}px`;
        cards.style.top = `${Math.min(rect.top, window.innerHeight - 320)}px`;
        cards.showPopover();
      }
    } catch (error) { this.controls.textContent = error.message; }
  }

  showNavigation(open, restoreFocus = false) {
    if (this.main && this.renderNavigation) return;
    this.layout.dataset.navigationOpen = String(open);
    this.navigationTrigger?.setAttribute("aria-expanded", String(open));
    this.navigationTrigger?.setAttribute("aria-label", open ? "Вернуться к разговору" : "Открыть список чатов");
    this.navigationTrigger?.setAttribute("title", open ? "Вернуться к разговору" : "Открыть список чатов");
    if (open) this.sidebar.querySelector("[data-new-chat]")?.focus();
    else if (restoreFocus) this.navigationTrigger?.focus();
  }

  draftKey() { return this.main ? "new:" + JSON.stringify(this.contextScope || {}) : "new"; }

  setContext(scope) {
    if (JSON.stringify(scope) === JSON.stringify(this.contextScope)) return false;
    this.rememberDraft();
    this.contextSelections.set(JSON.stringify(this.contextScope), this.row);
    this.contextScope = scope;
    this.currentProjectOnly = Boolean(scope);
    this.filterTrigger?.setAttribute("aria-pressed", String(this.currentProjectOnly));
    this.row = this.contextSelections.get(JSON.stringify(scope)) || null;
    if (!this.acceptsScope(this.row)) this.row = null;
    this.live = null; this.epoch++; this.sidebarSignature = null;
    this.input.value = this.drafts.get(this.row?.id || this.draftKey()) || "";
    this.syncSendButton();
    return true;
  }

  rememberDraft() {
    this.drafts.set(this.row?.id || this.draftKey(), this.input.value);
  }

  acceptsScope(scope) {
    const context = this.main && this.contextScope;
    return !context || ['project_id', 'board_id', 'card_id'].every(key => !context[key] || scope?.[key] === context[key]);
  }

  async select(row) {
    if (!row || !this.acceptsScope(row)) return;
    this.showNavigation(false);
    if (this.row?.id === row.id) { if (this.main) await this.changed(); this.input.focus(); return; }
    this.rememberDraft();
    this.row = row;
    this.live = null; this.syncSendButton();
    this.epoch++;
    this.input.value = this.drafts.get(row.id) || "";
    await this.changed();
    this.input.focus();
  }

  async newChat(scopeOverride) {
    try {
      if (scopeOverride && !this.acceptsScope(scopeOverride)) return;
      if (this.main && scopeOverride && (scopeOverride.project_id === null || scopeOverride.project_id !== this.scope().project_id)) {
        this.currentProjectOnly = false; this.filterTrigger?.setAttribute("aria-pressed", "false");
        this.epoch++;
      }
      const scope = scopeOverride || this.creationScope();
      const epoch = this.epoch;
      this.collapsedProjects.delete(scope.project_id || "global");
      const data = await this.api.createConversation(scope);
      if (epoch !== this.epoch) return;
      await this.select(data.item);
    } catch (error) { this.controls.textContent = error.message; }
  }

  creationScope() {
    if (this.main && this.contextScope) return this.contextScope;
    return this.main && !this.currentProjectOnly ? { project_id: null } : this.scope();
  }

  async ensure() {
    if (this.row && !this.acceptsScope(this.row)) throw new Error('Этот чат не относится к открытой карточке или методу.');
    if (!this.row) {
      const data = await this.api.createConversation(this.creationScope());
      if (!this.acceptsScope(data.item)) throw new Error('Контекст изменился. Повторите отправку в открытой карточке.');
      this.row = data.item;
      this.epoch++;
    }
    return this.row;
  }

  reset() {
    this.rememberDraft();
    this.row = null;
    this.live = null; this.syncSendButton();
    this.rows = [];
    this.epoch++;
    this.input.value = "";
    this.controls.replaceChildren();
    this.sidebarSignature = null;
    this.controlsSignature = null;
    this.showNavigation(false);
  }

  async refresh() {
    const epoch = this.epoch;
    const scope = this.scope();
    const scopeKey = JSON.stringify(scope);
    if (this.main && !this.renderNavigation && this.api.listProjects && (!this.projectsLoadedAt || Date.now() - this.projectsLoadedAt > 30000)) {
      this.projects = await this.api.listProjects();
      this.projectsLoadedAt = Date.now();
    }
    const data = await this.api.listConversations(this.main
      ? this.contextScope || (this.currentProjectOnly && !this.renderNavigation ? { project_id: scope.project_id } : {}) : scope);
    if (epoch !== this.epoch || scopeKey !== JSON.stringify(this.scope())) return null;
    this.rows = data.items || [];
    this.rows = this.rows.filter(row => this.acceptsScope(row));
    if (this.row && !this.rows.some(r => r.id === this.row.id)) {
      this.rememberDraft(); this.row = null; this.input.value = "";
    }
    if (!this.row) {
      this.row = this.rows[0] || null;
      this.input.value = this.drafts.get(this.row?.id || this.draftKey()) || this.input.value;
    }
    if (this.row) {
      this.row = this.rows.find(r => r.id === this.row.id) || this.row;
      const detail = await this.api.getConversation(this.row.id);
      if (epoch !== this.epoch || scopeKey !== JSON.stringify(this.scope()) || detail.conversation.id !== this.row?.id || !this.acceptsScope(detail.conversation)) return null;
      this.render(detail.live);
      return detail;
    }
    this.render(null);
    return { items: [] };
  }

  syncSendButton() {
    const button = this.sendButton;
    if (!button) return;
    const stopping = Boolean(this.live?.cancelled);
    const active = Boolean(this.live);
    const label = active ? (stopping ? "Останавливаем…" : "Остановить") : this.sendLabel;
    button.type = active ? "button" : "submit";
    button.disabled = stopping || (!active && Boolean(this.row?.pending));
    button.setAttribute('aria-label', label); button.title = label;
    const state = active ? 'stop' : 'send';
    if (button.dataset.action !== state) {
      button.dataset.action = state;
      button.innerHTML = active
        ? '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="1" fill="currentColor" stroke="none"/></svg>'
        : this.sendIcon;
    }
  }

  status(row) {
    return [row.unread ? 'Новый ответ' : '', row.agent_active ? 'Агент отвечает…' : row.pending ? 'Ожидает агента' : ''].filter(Boolean).join(' · ');
  }

  visibleReply() {
    if (!this.row?.unread || !this.log || document.hidden || !document.hasFocus() || getComputedStyle(this.log).visibility !== 'visible') return null;
    const reply = this.log.querySelector(`[data-id="${CSS.escape(this.row.latest_answer_id || '')}"] .agent-chat-reply`);
    if (!reply) return null;
    const area = this.log.getBoundingClientRect(), rect = reply.getBoundingClientRect();
    const exposed = document.elementFromPoint((area.left + area.right) / 2, Math.min(rect.bottom, area.bottom) - 2);
    return area.height > 0 && rect.bottom <= area.bottom + 2 && rect.bottom > area.top && this.log.contains(exposed) ? this.row.latest_answer_id : null;
  }

  scheduleRead() {
    const id = this.visibleReply(), cid = this.row?.id;
    const previous = this.controls.querySelector('.conversation-new-reply');
    const offscreen = this.row?.unread && !id && this.log && getComputedStyle(this.log).visibility === 'visible' && this.log.getBoundingClientRect().height > 0;
    if (offscreen && !previous) {
      const jump = document.createElement('button'); jump.type = 'button'; jump.className = 'btn conversation-new-reply';
      jump.textContent = 'Новый ответ ↓';
      jump.onclick = () => { this.log.scrollTop = this.log.scrollHeight; this.scheduleRead(); };
      this.controls.append(jump);
    } else if (!offscreen) previous?.remove();
    const candidate = id ? `${cid}/${id}` : null;
    if (candidate && candidate === this.readCandidate && this.readTimer) return;
    clearTimeout(this.readTimer);
    this.readCandidate = candidate;
    if (!id || !this.api.markConversationRead) return;
    this.readTimer = setTimeout(async () => {
      this.readTimer = null;
      if (this.row?.id !== cid || this.visibleReply() !== id || this.readRequest) return;
      this.readRequest = true;
      try {
        const result = await this.api.markConversationRead(cid, id);
        window.dispatchEvent(new CustomEvent('conversation-read', {detail: result.item}));
      } catch { /* Keep unread until the next successful acknowledgement. */ }
      finally { this.readRequest = false; }
    }, 800);
  }

  render(live) {
    this.live = live;
    this.syncSendButton();
    if (this.log) this.log.dataset.conversation = this.row?.id || '';
    const heading = this.layout.querySelector("[data-conversation-title]");
    const subtitle = this.layout.querySelector("[data-conversation-context]");
    const scope = this.row || this.contextScope;
    if (heading) heading.textContent = this.titleForScope ? this.titleForScope(scope) : this.row?.title || "Новый чат";
    if (subtitle) subtitle.textContent = this.main
      ? [scope?.project_id ? this.projectName(scope.project_id) : "Без проекта", scope?.card_id ? "Карточка" : scope?.board_id ? "Метод" : ""].filter(Boolean).join(" · ")
      : "Чат карточки";
    const signature = JSON.stringify([this.rows, this.row?.id, this.currentProjectOnly, this.projects, this.main ? new Date().toDateString() : null]);
    if (signature !== this.sidebarSignature && !this.dragging) {
      this.sidebarSignature = signature;
      this.renderSidebar();
    }
    const controlsSignature = JSON.stringify([live ? [live.cancelled, live.permission] : null,
      this.row?.id, this.row?.kind, this.row?.pending, this.row?.git_snapshot, this.row?.unread, this.row?.latest_answer_id]);
    if (controlsSignature === this.controlsSignature) return;
    this.controlsSignature = controlsSignature;
    const focusedOption = this.controls.contains(document.activeElement) ? document.activeElement.dataset.permissionOption : null;
    this.controls.replaceChildren();
    if (live) {
      if (live.permission) {
        const title = document.createElement("p"); title.textContent = live.permission.title;
        this.controls.append(title);
        const call = live.permission.tool_call;
        if (call?.rawInput) {
          const details = document.createElement("details");
          const summary = document.createElement("summary"); summary.textContent = "Подробности действия";
          const pre = document.createElement("pre"); pre.textContent = JSON.stringify(call.rawInput, null, 2);
          details.append(summary, pre); this.controls.append(details);
        }
        for (const option of live.permission.options) {
          const button = document.createElement("button");
          button.type = "button"; button.className = "btn btn-small";
          button.dataset.permissionOption = option.optionId;
          button.dataset.permission = live.permission.id;
          button.textContent = option.name; this.controls.append(button);
          if (focusedOption === option.optionId) button.focus({ preventScroll: true });
        }
      }
    }
    if (this.log) requestAnimationFrame(() => this.scheduleRead());
  }

  renderSidebar() {
    if (this.renderNavigation) { this.renderNavigation(this); return; }
    const active = this.sidebar.contains(document.activeElement) ? document.activeElement : null;
    const focusKey = active?.dataset.focusKey;
    const scroll = this.sidebar.scrollTop;
    this.sidebar.replaceChildren();
    const create = document.createElement("button");
    create.type = "button"; create.className = "btn conversation-create";
    create.dataset.newChat = ""; create.dataset.focusKey = "new";
    create.append(icon("compose"), this.main && !this.currentProjectOnly ? "Новый общий чат" : "Новый чат");
    this.sidebar.append(create);
    if (this.row && this.row.kind !== "git_sync") {
      const move = document.createElement("button");
      move.type = "button"; move.className = "btn conversation-create conversation-move-accessible";
      move.dataset.moveChat = ""; move.dataset.focusKey = "move";
      move.append(icon("folder"), "Перенести чат");
      move.disabled = Boolean(this.row.pending);
      if (move.disabled) move.title = "Дождитесь завершения ответа перед переносом чата";
      this.sidebar.append(move);
    }
    if (this.main) {
      const caption = document.createElement("p"); caption.className = "conversation-section-label";
      caption.textContent = "Проекты"; this.sidebar.append(caption);
    }
    if (this.main) {
      const projects = new Map([[null, []]]);
      for (const project of this.projects || []) projects.set(project.id, []);
      for (const row of this.rows) {
        if (!projects.has(row.project_id)) projects.set(row.project_id, []);
        projects.get(row.project_id).push(row);
      }
      for (const [pid, rows] of projects) {
        const group = document.createElement("details");
        group.className = "conversation-group"; group.dataset.projectGroup = pid || "global";
        group.open = !this.collapsedProjects.has(pid || "global");
        const summary = document.createElement("summary"); summary.dataset.focusKey = "project-" + pid;
        summary.dataset.chatDrop = ""; summary.dataset.projectId = pid || "";
        const name = document.createElement("span"); name.textContent = pid ? ((this.projects || []).find(p => p.id === pid)?.title || this.projectName(pid)) : "Без проекта";
        summary.append(icon("folder"), name); group.append(summary);
        const items = document.createElement("div"); items.className = "conversation-group-items";
        for (const row of rows) items.append(this.entry(row));
        group.append(items); this.sidebar.append(group);
      }
    } else {
      for (const row of this.rows) this.sidebar.append(this.entry(row));
    }
    if (!this.rows.length) {
      const empty = document.createElement("p"); empty.className = "conversation-list-empty";
      empty.textContent = this.currentProjectOnly
        ? "Создайте чат или отключите фильтр проекта." : "Начните новый разговор";
      this.sidebar.append(empty);
    }
    this.sidebar.scrollTop = scroll;
    if (focusKey) [...this.sidebar.querySelectorAll("[data-focus-key]")].find(el => el.dataset.focusKey === focusKey)?.focus({ preventScroll: true });
  }

  async moveChat() {
    if (this.main && this.contextScope) return;
    const row = this.row;
    if (!row || row.pending) return;
    const trigger = this.sidebar.querySelector("[data-move-chat]");
    const dialog = document.createElement("dialog");
    dialog.className = "conversation-move-dialog";
    dialog.setAttribute("aria-labelledby", "conversation-move-title");
    dialog.innerHTML = `<form><h2 id="conversation-move-title">Перенести чат</h2>
      <label>Проект<select name="project"><option value="">Без проекта</option></select></label>
      <label>Карточка<select name="card"><option value="">Весь проект</option></select></label>
      <p role="status" hidden></p><div class="conversation-move-actions">
      <button type="button" class="btn" data-dismiss>Отмена</button><button type="submit" class="btn btn-primary">Перенести</button></div></form>`;
    const project = dialog.querySelector('[name="project"]');
    const card = dialog.querySelector('[name="card"]');
    const submit = dialog.querySelector('[type="submit"]');
    const status = dialog.querySelector('[role="status"]');
    let version = 0;
    const showError = error => { status.textContent = error.message; status.hidden = false; };
    const loadCards = async () => {
      const current = ++version;
      const pid = project.value;
      card.replaceChildren(new Option("Весь проект", ""));
      card.disabled = !pid; card.parentElement.hidden = !pid; submit.disabled = true;
      status.hidden = true;
      try {
        if (pid) {
          const data = await this.api.getProject(pid);
          if (current !== version) return;
          for (const board of Object.values(data.boards || {})) for (const item of board.cards || []) {
            card.add(new Option(item.title, JSON.stringify([board.id, item.id])));
          }
          card.value = pid === row.project_id && row.card_id ? JSON.stringify([row.board_id, row.card_id]) : "";
        }
        if (current === version) submit.disabled = false;
      } catch (error) { if (current === version) showError(error); }
    };
    project.addEventListener("change", () => void loadCards());
    dialog.querySelector('[data-dismiss]').onclick = () => dialog.close();
    dialog.addEventListener("close", () => { version++; dialog.remove(); (trigger?.isConnected ? trigger : this.input).focus(); });
    dialog.querySelector('form').onsubmit = async event => {
      event.preventDefault(); submit.disabled = true; project.disabled = true; card.disabled = true;
      try {
        const [board_id, card_id] = card.value ? JSON.parse(card.value) : [null, null];
        const result = await this.api.moveConversation(row.id, { project_id: project.value || null, board_id, card_id });
        if (this.row?.id === row.id) this.row = result.item;
        dialog.close();
        await this.changed();
      } catch (error) { showError(error); submit.disabled = false; project.disabled = false; card.disabled = !project.value; }
    };
    project.disabled = true; card.disabled = true; card.parentElement.hidden = true;
    document.body.append(dialog); dialog.showModal(); submit.disabled = true;
    try {
      const projects = await this.api.listProjects();
      if (!dialog.isConnected) return;
      for (const item of projects) project.add(new Option(item.title, item.id));
      project.value = row.project_id || "";
      project.disabled = false;
      await loadCards();
      if (dialog.isConnected) project.focus();
    } catch (error) { showError(error); }
  }

  confirmDelete(row, trigger) {
    const dialog = document.createElement("dialog"); dialog.className = "conversation-delete-dialog";
    const titleId = "delete-chat-" + crypto.randomUUID();
    dialog.setAttribute("aria-labelledby", titleId);
    dialog.setAttribute("aria-describedby", titleId + "-name " + titleId + "-description");
    dialog.innerHTML = `<form><h2 id="${titleId}">Удалить чат?</h2><p id="${titleId}-name" class="conversation-delete-name"></p><p id="${titleId}-description">Вся переписка будет удалена без возможности восстановления.</p><p class="conversation-delete-error" role="alert" hidden></p><div class="form-actions"><button type="button" class="btn" data-dismiss>Отмена</button><button type="submit" class="btn btn-danger">Удалить</button></div></form>`;
    dialog.querySelector('.conversation-delete-name').textContent = row.title;
    const cancel = dialog.querySelector('[data-dismiss]'), submit = dialog.querySelector('[type=submit]');
    cancel.onclick = () => dialog.close();
    dialog.addEventListener('close', () => {
      dialog.remove();
      (trigger?.isConnected ? trigger : this.sidebar.querySelector('[data-new-chat]'))?.focus();
    });
    dialog.querySelector('form').onsubmit = async event => {
      event.preventDefault(); submit.disabled = true;
      try {
        await this.api.deleteConversation(row.id);
        this.drafts.delete(row.id);
        for (const [key, selected] of this.contextSelections) if (selected?.id === row.id) this.contextSelections.delete(key);
        if (this.row?.id === row.id) { this.row = null; this.live = null; this.input.value = ''; }
        this.epoch++; this.sidebarSignature = null;
        dialog.close();
        await this.changed({open: false});
        (this.sidebar.querySelector('[data-conversation][aria-pressed="true"]') || this.sidebar.querySelector('[data-new-chat]'))?.focus({preventScroll: true});
      } catch (error) {
        const status = dialog.querySelector('.conversation-delete-error');
        status.hidden = false; status.textContent = error.message; submit.disabled = false;
      }
    };
    document.body.append(dialog); dialog.showModal(); cancel.focus();
  }

  entry(row) {
    const button = document.createElement("button");
    button.type = "button"; button.className = "conversation-entry";
    button.dataset.conversation = row.id; button.dataset.focusKey = row.id;
    button.draggable = !row.pending && row.kind !== "git_sync";
    button.setAttribute("aria-pressed", String(row.id === this.row?.id));
    button.classList.toggle('has-unread', Boolean(row.unread));
    button.classList.toggle('has-activity', Boolean(row.agent_active));
    button.title = [row.title, this.status(row)].filter(Boolean).join(' · ');
    button.setAttribute('aria-label', button.title);
    const title = document.createElement("span"); title.className = "conversation-entry-title";
    title.textContent = row.title;
    const text = document.createElement("span"); text.className = "conversation-entry-text";
    text.append(title);
    if (this.status(row) && !this.renderNavigation) {
      const status = document.createElement("small"); status.className = "conversation-entry-status";
      status.textContent = this.status(row); text.append(status);
    }
    button.append(icon(row.card_id ? "card" : "chat"), text);
    const dot = document.createElement('span'); dot.className = 'chat-status-dot'; dot.setAttribute('aria-hidden', 'true'); button.append(dot);
    if (!this.api.deleteConversation) return button;
    const wrapper = document.createElement('div'); wrapper.className = 'conversation-entry-row';
    const trigger = document.createElement('button'); trigger.type = 'button';
    trigger.className = 'conversation-entry-menu'; trigger.dataset.chatMenu = row.id;
    trigger.setAttribute('aria-label', 'Действия с чатом'); trigger.title = 'Действия с чатом';
    trigger.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg>';
    const menu = document.createElement('div'); menu.className = 'conversation-actions-popover';
    menu.id = 'chat-actions-' + crypto.randomUUID(); menu.setAttribute('popover', 'auto');
    trigger.setAttribute('popovertarget', menu.id);
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'conversation-delete-action';
    remove.textContent = 'Удалить чат'; remove.disabled = Boolean(row.pending);
    if (row.pending) remove.title = 'Дождитесь завершения ответа перед удалением чата';
    remove.onclick = () => { menu.hidePopover(); this.confirmDelete(row, trigger); };
    menu.append(remove);
    const blink = document.createElement('button'); blink.type = 'button'; blink.className = 'conversation-delete-action';
    blink.onclick = () => {
      const value = document.documentElement.dataset.chatBlink === 'off' ? 'on' : 'off';
      document.documentElement.dataset.chatBlink = value;
      try { localStorage.setItem('researchos-chat-blink', value); } catch { /* Private storage. */ }
      menu.hidePopover(); trigger.focus();
    };
    menu.append(blink);
    menu.addEventListener('beforetoggle', event => {
      if (event.newState !== 'open') return;
      blink.textContent = document.documentElement.dataset.chatBlink === 'off' ? 'Включить мигание' : 'Отключить мигание';
      const rect = trigger.getBoundingClientRect();
      menu.style.left = `${Math.max(8, Math.min(innerWidth - 208, rect.right - 200))}px`;
      menu.style.top = `${Math.max(8, Math.min(innerHeight - 64, rect.bottom + 4))}px`;
    });
    menu.addEventListener('toggle', event => {
      if (event.newState !== 'open') return;
      menu.style.top = `${Math.max(8, Math.min(parseFloat(menu.style.top), innerHeight - menu.getBoundingClientRect().height - 8))}px`;
      (remove.disabled ? blink : remove).focus();
    });
    wrapper.append(button, trigger, menu);
    return wrapper;
  }

}


function attachConversationListResize(layout, sidebar, scope, api) {
  let edited = false;
  const field = `chat_list_${scope}_width`;
  const key = `koi-chat-list-width-${scope}`;
  const unified = scope === "main" && layout.closest(".workspace")?.classList.contains("unified-navigation");
  const left = unified || layout.classList.contains("conversation-left");
  const minimum = unified ? 240 : 160;
  const defaultWidth = unified ? 300 : 200;
  let preferred = defaultWidth;
  try { preferred = Number(localStorage.getItem(key)) || defaultWidth; } catch { /* private mode */ }
  const handle = document.createElement("div");
  handle.className = "conversation-list-resize";
  handle.tabIndex = 0;
  handle.setAttribute("role", "separator");
  handle.setAttribute("aria-label", "Ширина списка чатов");
  handle.setAttribute("title", "Потяните границу, чтобы изменить ширину списка");
  handle.setAttribute("aria-orientation", "vertical");
  handle.setAttribute("aria-controls", sidebar.id);
  handle.setAttribute("aria-valuemin", String(minimum));
  layout.append(handle);
  let drag;
  const maximum = () => {
    const workspace = layout.closest(".workspace");
    const navigationOnly = workspace?.classList.contains("unified-navigation") && !workspace.classList.contains("is-chat-open");
    return Math.max(minimum, Math.min(440, navigationOnly ? window.innerWidth - 64 : layout.clientWidth - 324));
  };
  const width = () => Math.round(Math.max(minimum, Math.min(maximum(), preferred)));
  const render = () => {
    layout.style.setProperty("--conversation-list-width", `${width()}px`);
    layout.closest(".agent-chat-panel")?.style.setProperty("--conversation-list-width", `${width()}px`);
    handle.setAttribute("aria-valuenow", width());
    handle.setAttribute("aria-valuemax", maximum());
  };
  const save = () => {
    preferred = width();
    edited = true;
    try { localStorage.setItem(key, String(preferred)); } catch { /* private mode */ }
    api.saveAgentChatSettings?.({ [field]: preferred }).catch(() => { /* local cache remains available */ });
  };
  handle.addEventListener("pointerdown", event => {
    if (event.button !== 0) return;
    event.preventDefault();
    handle.focus();
    drag = { x: event.clientX, width: width(), direction: (getComputedStyle(layout).direction === "rtl" ? -1 : 1) * (left ? -1 : 1) };
    layout.classList.add("is-resizing-list");
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener("pointermove", event => {
    if (!drag) return;
    preferred = Math.max(minimum, Math.min(maximum(), drag.width + (drag.x - event.clientX) * drag.direction));
    render();
  });
  handle.addEventListener("lostpointercapture", () => {
    drag = null;
    layout.classList.remove("is-resizing-list");
    save();
  });
  handle.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const direction = (getComputedStyle(layout).direction === "rtl" ? -1 : 1) * (left ? -1 : 1);
    preferred = event.key === "Home" ? minimum : event.key === "End" ? maximum()
      : Math.max(minimum, Math.min(maximum(), width() + (event.key === "ArrowLeft" ? 16 : -16) * direction));
    render(); save();
  });
  handle.addEventListener("dblclick", () => { preferred = defaultWidth; render(); save(); });
  new ResizeObserver(render).observe(layout);
  render();
  // The desktop server uses a new port on each launch; localStorage alone is insufficient.
  api.getSettings?.().then(settings => {
    if (edited || drag || !Number.isFinite(settings[field])) return;
    preferred = settings[field]; render();
  }).catch(() => { /* use the local cache when offline */ });
}
