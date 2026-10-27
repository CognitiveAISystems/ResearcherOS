const navIcon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${{
  compose: '<path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L9 17l-4 1 1-4Z"/>',
  left: '<path d="m14 6-6 6 6 6"/>',
  tree: '<rect x="9" y="2" width="6" height="5" rx="1.5"/><rect x="2" y="17" width="6" height="5" rx="1.5"/><rect x="16" y="17" width="6" height="5" rx="1.5"/><path d="M12 7v5M5 17v-5h14v5"/>',
  chat: '<path d="M21 11.5a8.5 8.5 0 0 1-12.3 7.6L3 21l1.9-5.7A8.5 8.5 0 1 1 21 11.5Z"/>',
  all: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>'
}[name]}</svg>`;

/* Programs own navigation; tree membership stays in conversation scope. */
export class ResearchChatNavigation {
  constructor({ sidebar, rail, groups, activeTree, chooseTree, openList, collapse }) {
    Object.assign(this, { sidebar, rail, groups, activeTree, chooseTree, openList, collapse });
    this.followActive = true;
    this.sectionStates = new Map();
    this.query = '';
    this.host = document.createElement('section');
    this.host.className = 'research-chat-browser';
    this.host.innerHTML = `<header class="research-chat-heading"><h2></h2><button type="button" class="conversation-icon-button" data-research-collapse aria-label="Свернуть панель" title="Свернуть панель">${navIcon("left")}</button></header>
      <div class="research-chat-search-row"><label class="research-chat-search"><span class="sr-only">Поиск по чатам</span>${navIcon("search")}<input type="search" placeholder="Поиск по чатам" aria-label="Поиск по чатам"></label><button type="button" class="btn research-create" data-research-create aria-label="Новый чат" title="Новый чат">${navIcon("compose")}</button></div>
      <div class="research-chat-entries"></div>`;
    sidebar.prepend(this.host);
    this.programs = document.createElement('nav');
    this.programs.className = 'research-programs';
    this.programs.setAttribute('aria-label', 'Научные программы');
    rail.insertBefore(this.programs, rail.querySelector('#btn-theme'));
    const compose = document.createElement('button');
    compose.type = 'button'; compose.className = 'btn btn-primary research-global-compose';
    compose.innerHTML = navIcon('compose');
    compose.title = 'Написать в общий чат'; compose.setAttribute('aria-label', compose.title);
    rail.append(compose);
    compose.onclick = async () => {
      if (this.controller.contextScope) return;
      compose.disabled = true;
      try {
        this.controller.setContext(null);
        await this.selectGroup(this.groups().find(g => g.id === 'global'));
        await this.controller.newChat({project_id: null});
      } finally { compose.disabled = Boolean(this.controller.contextScope); }
    };
    this.host.querySelector('[data-research-create]').onclick = () => void this.create();
    this.host.querySelector('[data-research-collapse]').onclick = collapse;
    this.host.querySelector('input').oninput = event => { this.query = event.target.value; this.renderEntries(); };
    this.host.querySelector('.research-chat-entries').addEventListener('scroll', () => this.scheduleIndicators(), {passive: true});
    new ResizeObserver(() => this.scheduleIndicators()).observe(this.host);
  }

  async selectGroup(group) {
    if (!group || !this.allowsGroup(group)) return;
    this.followActive = false;
    this.groupId = group.id;
    this.keepAllPrograms = group.id === 'all';
    this.query = ''; this.host.querySelector('input').value = '';
    this.openList();
    this.render(this.controller);
    const tree = group.trees.find(t => t.id === this.activeTree()) || group.trees[0];
    if (!this.controller.contextScope && tree && tree.id !== this.activeTree() && !['global', 'all'].includes(group.id)) await this.chooseTree(tree.id);
    this.render(this.controller);
  }

  async focusConversation(row) {
    if (this.controller.contextScope) return;
    if (!row?.project_id) return;
    const groups = this.groups().filter(g => !['global', 'all'].includes(g.id) && g.trees.some(t => t.projectIds.includes(row.project_id)));
    const group = groups.find(g => g.id === row.program_id) || groups.find(g => g.id === this.groupId) || groups[0];
    if (!group) return;
    this.groupId = group.id;
    this.keepAllPrograms = false;
    this.followActive = false;
    const tree = group.trees.find(t => t.projectIds.includes(row.project_id));
    if (tree.id !== this.activeTree()) await this.chooseTree(tree.id);
    this.render(this.controller);
  }

  create() {
    if (this.controller.contextScope) return this.controller.newChat(this.controller.contextScope);
    const scope = {project_id: null};
    if (!['global', 'all'].includes(this.groupId)) {
      scope.program_id = this.groupId;
      // This remembers where an unassigned draft is listed; it grants no project scope.
      scope.focus_project_id = this.tree?.projectIds[0] || null;
    }
    return this.controller.newChat(scope);
  }

  visibleRows(rows) {
    rows = rows.filter(row => this.controller.acceptsScope(row));
    if (this.controller.contextScope) return rows;
    const group = this.groups().find(g => g.id === this.groupId);
    if (this.groupId === 'all') return rows;
    if (!group || this.groupId === 'global') return rows.filter(r => !r.project_id);
    const ids = group.trees.flatMap(t => t.projectIds);
    return rows.filter(row => row.program_id ? row.program_id === group.id : ids.includes(row.project_id));
  }

  allowsGroup(group) {
    const scope = this.controller?.contextScope;
    return !scope || !['all', 'global'].includes(group.id) && group.trees.some(tree => tree.projectIds.includes(scope.project_id));
  }

  render(controller) {
    if (!controller) return;
    this.controller = controller;
    const groups = this.groups();
    const scope = controller.contextScope;
    if (scope && !this.savedNavigation) {
      this.savedNavigation = {groupId: this.groupId, keepAllPrograms: this.keepAllPrograms, followActive: this.followActive, query: this.query};
      this.query = ''; this.host.querySelector('input').value = '';
    } else if (!scope && this.savedNavigation) {
      Object.assign(this, this.savedNavigation); this.savedNavigation = null;
      this.host.querySelector('input').value = this.query;
    }
    if (scope && !groups.some(group => group.id === this.groupId && this.allowsGroup(group))) {
      this.groupId = groups.find(group => this.allowsGroup(group))?.id;
    }
    this.rail.querySelectorAll('.research-global-compose, .research-manage').forEach(button => button.disabled = Boolean(scope));
    this.sidebar.querySelectorAll('#btn-new-project, #projects-archive-bar button').forEach(button => button.disabled = Boolean(scope));
    const create = this.host.querySelector('[data-research-create]');
    create.title = scope?.card_id ? 'Новый чат карточки' : scope ? 'Новый чат метода' : 'Новый чат';
    create.setAttribute('aria-label', create.title);
    const active = this.activeTree();
    const readingChat = this.sidebar.closest('.workspace').classList.contains('is-chat-open');
    const activeGroup = groups.find(g => g.trees.some(t => t.id === active));
    if (!scope && (!this.groupId || this.followActive && !readingChat && !this.keepAllPrograms)) {
      if (activeGroup && activeGroup.id !== this.groupId) {
        this.query = ''; this.host.querySelector('input').value = '';
      }
      this.groupId = activeGroup?.id || this.groupId;
    }
    const group = groups.find(g => g.id === this.groupId) || activeGroup || groups[0];
    this.groupId = group?.id;
    this.tree = group?.trees.find(t => scope ? t.projectIds.includes(scope.project_id) : t.id === active) || null;
    const signature = JSON.stringify([groups, this.groupId, scope, controller.rows.map(r => [r.id, r.pending, r.agent_active, r.unread, r.program_id, r.project_id])]);
    if (signature !== this.signature) {
      this.signature = signature;
      const key = this.programs.contains(document.activeElement) ? document.activeElement.dataset.focusKey : null;
      this.programs.replaceChildren(...groups.map(g => {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'research-program';
        button.disabled = !this.allowsGroup(g);
        button.dataset.focusKey = 'program-' + g.id;
        button.dataset.programId = g.id;
        button.title = g.title; button.setAttribute('aria-label', g.title);
        button.setAttribute('aria-pressed', String(g.id === this.groupId));
        const initial = document.createElement('span'); initial.className = 'research-program-initial';
        if (g.icon) initial.innerHTML = navIcon(g.icon);
        else initial.textContent = g.title.split(/\s+/).slice(0, 2).map(s => s[0]).join('').toUpperCase();
        const label = document.createElement('span'); label.textContent = g.title;
        button.append(initial, label);
        button.onclick = () => void this.selectGroup(g);
        return button;
      }));
      this.host.querySelector('h2').textContent = group?.title || 'Чаты';
      this.host.querySelector('h2').title = group?.title || 'Чаты';
      if (key) [...this.programs.children].find(n => n.dataset.focusKey === key)?.focus({preventScroll: true});
    }
    this.renderEntries();
    this.scheduleIndicators();
  }

  scheduleIndicators() {
    cancelAnimationFrame(this.indicatorFrame);
    this.indicatorFrame = requestAnimationFrame(() => this.paintIndicators());
  }

  paintIndicators() {
    if (!this.controller) return;
    const visible = node => {
      if (getComputedStyle(node).visibility !== 'visible') return false;
      const rect = node.getBoundingClientRect();
      const area = (node.closest('.research-chat-entries, .conversation-sidebar') || node).getBoundingClientRect();
      const height = Math.min(rect.bottom, area.bottom, innerHeight) - Math.max(rect.top, area.top, 0);
      return rect.width > 0 && rect.height > 0 && height >= Math.min(24, rect.height / 2);
    };
    const shown = new Set([...document.querySelectorAll('.conversation-entry[data-conversation], .agent-chat-log[data-conversation]')]
      .filter(visible).map(node => node.dataset.conversation));
    for (const group of this.groups()) {
      const button = [...this.programs.children].find(b => b.dataset.programId === group.id);
      if (!button) continue;
      const hidden = this.controller.rows.filter(row => !shown.has(row.id) && (group.id === 'all' ||
        (group.id === 'global' ? !row.project_id : row.program_id ? row.program_id === group.id : group.trees.some(t => t.projectIds.includes(row.project_id)))));
      const unread = hidden.some(row => row.unread), working = hidden.some(row => row.agent_active);
      button.classList.toggle('has-unread', unread);
      button.classList.toggle('has-activity', working);
      button.title = [group.title, unread ? 'Непрочитанные ответы' : '', working ? 'Агент отвечает…' : ''].filter(Boolean).join(' · ');
      button.setAttribute('aria-label', button.title);
    }
  }

  renderEntries() {
    this.scheduleIndicators();
    const controller = this.controller;
    if (!controller || controller.dragging) return;
    const group = this.groups().find(g => g.id === this.groupId);
    const rows = this.visibleRows(controller.rows).filter(r => (r.title || '').toLocaleLowerCase().includes(this.query.toLocaleLowerCase()));
    rows.sort((a, b) => (Date.parse(b.updated_at || b.created_at) || 0) - (Date.parse(a.updated_at || a.created_at) || 0));
    const entries = this.host.querySelector('.research-chat-entries');
    const signature = JSON.stringify([group, this.tree?.id, controller.contextScope, rows, controller.row?.id, this.query, new Date().toDateString()]);
    if (signature === this.entriesSignature) return;
    this.entriesSignature = signature;
    if (!group) { entries.replaceChildren(); return; }
    if (this.lastFocusedTree !== this.tree?.id && this.tree) {
      for (const tree of group.trees) if (tree.id !== this.tree.id) {
        const state = this.sectionStates.get(JSON.stringify([group.id, tree.id]));
        if (state) Object.assign(state, {open: false, full: false});
      }
    }
    const sections = [
      ...(rows.some(r => !r.project_id) || this.groupId === 'global' ? [{id: 'unassigned', title: 'Общие чаты', icon: 'chat', rows: rows.filter(r => !r.project_id)}] : []),
      ...group.trees.map(tree => ({id: tree.id, title: tree.title, icon: 'tree', tree,
        disabled: Boolean(controller.contextScope && !tree.projectIds.includes(controller.contextScope.project_id)),
        rows: rows.filter(r => tree.projectIds.includes(r.project_id))}))
    ].filter(section => section.disabled || !this.query || section.rows.length);
    const focusKey = entries.contains(document.activeElement) ? document.activeElement.closest('[data-focus-key]')?.dataset.focusKey : null;
    const keep = new Set();
    for (const [index, data] of sections.entries()) {
      const key = JSON.stringify([group.id, data.id]);
      keep.add(key);
      let section = [...entries.children].find(el => el.dataset.chatSection === key);
      if (!section) {
        section = document.createElement('section'); section.className = 'research-chat-section conversation-group';
        section.dataset.chatSection = key;
        section.dataset.sectionId = data.id;
        section.innerHTML = `<h3><button type="button" class="research-chat-section-toggle">${navIcon(data.icon)}<span class="research-chat-section-title"></span>${navIcon('left')}</button></h3><div class="research-chat-section-content"></div>`;
        const button = section.querySelector('.research-chat-section-toggle');
        const content = section.lastElementChild;
        content.id = 'chat-section-' + crypto.randomUUID();
        if (button) {
          button.setAttribute('aria-controls', content.id);
          button.dataset.focusKey = 'chat-section-' + key;
          button.onclick = event => {
            if (event.detail > 1 || section.chatData.disabled) return;
            const state = this.sectionStates.get(key);
            state.open = !state.open;
            if (!state.open) state.full = false;
            this.paintSection(section);
            if (state.open && section.chatData.tree && !this.controller.contextScope) {
              this.followActive = false;
              void this.chooseTree(section.chatData.tree.id);
            }
          };
          button.ondblclick = event => {
            event.preventDefault();
            if (section.chatData.disabled) return;
            Object.assign(this.sectionStates.get(key), {open: true, full: true});
            this.paintSection(section);
          };
        }
      }
      section.chatData = data;
      if (!this.sectionStates.has(key)) this.sectionStates.set(key, {open: !data.tree || data.tree.id === this.tree?.id, full: false});
      const selectedIndex = data.rows.findIndex(row => row.id === controller.row?.id);
      if (selectedIndex >= 0 && this.lastSelectedChat !== controller.row?.id && this.sidebar.closest('.workspace').classList.contains('is-chat-open')) {
        Object.assign(this.sectionStates.get(key), {open: true, full: selectedIndex >= 3});
      }
      // A map focus change reveals the corresponding tree, without opening every group.
      if (data.tree && data.tree.id === this.tree?.id && this.lastFocusedTree !== this.tree?.id) this.sectionStates.get(key).open = true;
      const button = section.querySelector('.research-chat-section-toggle');
      section.classList.toggle('research-chat-unassigned', !data.tree);
      if (button) {
        button.disabled = Boolean(data.disabled);
        section.classList.toggle('is-context-disabled', button.disabled);
        button.querySelector('.research-chat-section-title').textContent = data.title;
        button.title = [data.title, data.tree && data.tree.id === this.tree?.id ? 'Дерево в фокусе' : '', data.rows.some(row => row.agent_active) ? 'Агент отвечает' : '', data.rows.length > 3 ? 'Двойной клик — все чаты' : ''].filter(Boolean).join(' · ');
        button.classList.toggle('is-focused-tree', Boolean(data.tree && data.tree.id === this.tree?.id));
      }
      this.paintSection(section);
      if (entries.children[index] !== section) entries.insertBefore(section, entries.children[index] || null);
    }
    for (const section of [...entries.children]) if (!keep.has(section.dataset.chatSection)) section.remove();
    this.lastFocusedTree = this.tree?.id;
    this.lastSelectedChat = controller.row?.id;
    if (!sections.length) {
      const empty = document.createElement('p'); empty.className = 'conversation-list-empty';
      empty.textContent = 'Чаты не найдены'; entries.append(empty);
    }
    if (focusKey) [...entries.querySelectorAll('[data-focus-key]')].find(n => n.dataset.focusKey === focusKey)?.focus({preventScroll: true});
  }

  paintSection(section) {
    this.scheduleIndicators();
    const data = section.chatData;
    const state = this.sectionStates.get(section.dataset.chatSection);
    const open = !data.disabled && (state.open || Boolean(this.query));
    const content = section.lastElementChild;
    section.querySelector('.research-chat-section-toggle')?.setAttribute('aria-expanded', String(open));
    content.hidden = !open;
    const signature = JSON.stringify([data.rows, this.controller.row?.id, open, state.full, this.query, new Date().toDateString()]);
    if (content.dataset.signature === signature) return;
    content.dataset.signature = signature;
    if (!open) { content.replaceChildren(); return; }
    const full = state.full || Boolean(this.query);
    this.renderChats(content, full ? data.rows : data.rows.slice(0, 3));
    if (data.rows.length > 3 && !this.query) {
      const more = document.createElement('button'); more.type = 'button'; more.className = 'research-chat-show-all';
      more.textContent = full ? 'Только последние 3' : 'Показать все';
      more.onclick = () => {
        state.full = !state.full; this.paintSection(section);
        const target = state.full ? content.querySelector('.research-chat-show-all') : section.querySelector('.research-chat-section-toggle') || content.querySelector('.research-chat-show-all');
        target.focus({preventScroll: true});
      };
      content.append(more);
    }
  }

  renderChats(container, rows) {
    const today = new Date();
    const focusKey = container.contains(document.activeElement) ? document.activeElement.closest('[data-focus-key]')?.dataset.focusKey : null;
    container.replaceChildren(...rows.map(row => {
      const entry = this.controller.entry(row);
      if (row.project_id) entry.addEventListener('click', event => {
        if (event.target.closest('[data-conversation]')) void this.focusConversation(row);
      });
      const meta = document.createElement('small'); meta.className = 'research-chat-meta';
      const kind = row.card_id ? 'Карточка' : row.board_id ? 'Метод' : row.program_id && !row.project_id ? 'Общий чат программы' : 'Разговор';
      const date = new Date(row.updated_at || row.created_at);
      const when = Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('ru', date.toDateString() === today.toDateString() ? {hour: '2-digit', minute: '2-digit'} : {day: 'numeric', month: 'short'}).format(date);
      meta.textContent = this.controller.status(row) || [kind, when].filter(Boolean).join(' · ');
      entry.querySelector('.conversation-entry-text').append(meta);
      return entry;
    }));
    if (!rows.length) {
      const empty = document.createElement('p'); empty.className = 'conversation-list-empty';
      empty.textContent = this.query ? 'Чаты не найдены' : 'Пока нет чатов'; container.append(empty);
    }
    if (focusKey) [...container.querySelectorAll('[data-focus-key]')].find(n => n.dataset.focusKey === focusKey)?.focus({preventScroll: true});
  }
}
