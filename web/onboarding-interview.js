import { MindmapCamera } from './lab-canvas.js';

const TYPE_LABELS = {
  topic: 'Тема', direction: 'Направление', program: 'Инженерное решение',
  problem: 'Проблема', cause: 'Причина', remediation: 'Гипотеза',
  cause_evidence: 'Доказательство', method: 'Метод', experiment: 'Эксперимент',
};
const NODE_SIZE = {
  topic: [220, 105, '50%'], direction: [220, 105, '50%'], program: [182, 80, '12px'],
  problem: [220, 105, '50%'], cause: [182, 80, '12px'],
  remediation: [170, 72, '4px'], cause_evidence: [170, 72, '12px'],
  method: [165, 68, '6px'], experiment: [165, 68, '6px'],
};
const CHILD_TYPES = { topic: ['problem', 'direction', 'program'], problem: ['program', 'method'], direction: ['program', 'method'], program: ['program', 'method'], method: [] };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

async function post(url, payload) {
  let response;
  try {
    response = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload), signal: AbortSignal.timeout(140000),
    });
  } catch (problem) {
    if (problem.name === 'TimeoutError' || problem.name === 'AbortError') throw new Error('Не удалось дождаться ответа агента. Повтори отправку или выбери другого агента.');
    throw problem;
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || 'Не удалось продолжить интервью.');
  return data;
}

export function activitySvg() {
  return `<svg class="method-activity-svg theme-agent" viewBox="0 0 88 44" aria-hidden="true">
    <defs><linearGradient id="onboard-activity-grad" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" stop-color="var(--pink)"/><stop offset="50%" stop-color="var(--purple)"/><stop offset="100%" stop-color="var(--cyan)"/></linearGradient></defs>
    <ellipse class="ma-floor" cx="44" cy="38" rx="28" ry="4"/>
    <circle class="ma-core" cx="44" cy="22" r="9" fill="url(#onboard-activity-grad)"/>
    <circle class="ma-core-ring" cx="44" cy="22" r="13"/>
    <g class="ma-orbit ma-orbit-a"><circle cx="44" cy="8" r="2.5" fill="var(--cyan)"/></g>
    <g class="ma-orbit ma-orbit-b"><circle cx="68" cy="22" r="2" fill="var(--pink)"/></g>
    <g class="ma-orbit ma-orbit-c"><circle cx="44" cy="36" r="1.8" fill="var(--lime)"/></g>
    <text class="ma-q" x="58" y="14">?</text>
  </svg>`;
}

function layoutNodes(nodes) {
  const depths = new Map();
  const positions = new Map();
  const layers = new Map();
  for (const node of nodes) {
    const depth = node.parent_id ? (depths.get(node.parent_id) ?? -1) + 1 : 0;
    depths.set(node.id, depth);
    if (!layers.has(depth)) layers.set(depth, []);
    layers.get(depth).push(node);
  }
  const width = Math.max(720, ...[...layers.values()].map(layer => layer.length * 240 + 80));
  for (const [depth, layer] of layers) layer.forEach((node, index) => positions.set(node.id, { x: width / 2 + (index - (layer.length - 1) / 2) * 240, y: 105 + depth * 115 }));
  return positions;
}

function renderTree(world, nodes, empty, pendingId, positions = layoutNodes(nodes), actions = null) {
  world.querySelectorAll('.onboarding-interview__node').forEach((node) => node.remove());
  const svg = world.querySelector('.onboarding-interview__edges');
  svg.querySelectorAll('.onboarding-interview__edge').forEach((edge) => edge.remove());
  empty.hidden = nodes.length > 0;
  const byId = new Map(nodes.map((node) => [node.id, node]));
  for (const node of nodes) {
    const point = positions.get(node.id);
    const [width, height, radius] = NODE_SIZE[node.type];
    const card = el('div', `map-node onboarding-interview__node ${node.type}`);
    card.dataset.nodeId = node.id;
    if (node.id === pendingId) card.classList.add('is-pending');
    card.style.left = `${point.x}px`;
    card.style.top = `${point.y}px`;
    card.style.width = `${width}px`;
    card.style.height = `${height}px`;
    card.style.borderRadius = radius;
    card.title = node.description;
    card.append(el('span', 'node-label', `[${TYPE_LABELS[node.type]}]`), el('span', 'node-title', node.title));
    if (actions) {
      card.tabIndex = 0;
      card.setAttribute('aria-label', `${node.title}. Двойной щелчок или Enter — редактировать`);
      const title = card.querySelector('.node-title');
      let editing = false;
      const finishTitle = async cancel => {
        if (!editing) return;
        editing = false;
        const value = title.textContent.trim();
        title.removeAttribute('contenteditable'); title.removeAttribute('role'); title.removeAttribute('aria-label');
        title.textContent = node.title;
        if (!cancel && value && value !== node.title) await actions.rename(node, value);
      };
      card.addEventListener('dblclick', event => {
        if (event.target.closest('button') || editing) return;
        event.preventDefault(); editing = true; title.textContent = node.title;
        title.contentEditable = 'plaintext-only'; title.setAttribute('role', 'textbox'); title.setAttribute('aria-label', 'Имя узла');
        title.focus(); window.getSelection().selectAllChildren(title);
      });
      title.addEventListener('keydown', event => {
        if (!editing) return;
        event.stopPropagation();
        if (['Enter', 'Escape'].includes(event.key)) { event.preventDefault(); void finishTitle(event.key === 'Escape'); }
      });
      title.addEventListener('blur', () => { void finishTitle(false); });
      card.addEventListener('keydown', event => { if (event.key === 'Enter' && event.target === card) { event.preventDefault(); actions.edit(node); } });
      if (CHILD_TYPES[node.type]?.length) {
        const controls = el('div', 'node-actions onboarding-interview__actions');
        controls.dataset.nodeType = node.type;
        const add = el('button', 'node-actions-trigger');
        add.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
        add.type = 'button'; add.title = 'Действия с узлом';
        add.setAttribute('aria-label', `Действия с узлом «${node.title}»`);
        add.setAttribute('aria-expanded', 'false');
        const menu = el('div', 'node-action-menu'); menu.popover = 'auto';
        menu.setAttribute('role', 'group'); menu.setAttribute('aria-label', 'Действия с узлом');
        for (const type of CHILD_TYPES[node.type]) {
          const choice = el('button', '', `Добавить: ${TYPE_LABELS[type]}`);
          choice.type = 'button'; choice.dataset.nodeType = type;
          choice.addEventListener('click', event => { event.stopPropagation(); menu.hidePopover(); actions.add(node, type); });
          menu.append(choice);
        }
        add.addEventListener('click', event => {
          event.stopPropagation();
          if (menu.matches(':popover-open')) { menu.hidePopover(); return; }
          menu.showPopover();
          const anchor = add.getBoundingClientRect(); const rect = menu.getBoundingClientRect();
          menu.style.left = `${Math.max(8, Math.min(anchor.right + 6, innerWidth - rect.width - 8))}px`;
          menu.style.top = `${Math.max(8, Math.min(anchor.top, innerHeight - rect.height - 8))}px`;
          menu.querySelector('button')?.focus();
        });
        menu.addEventListener('toggle', event => add.setAttribute('aria-expanded', String(event.newState === 'open')));
        controls.append(add, menu); card.append(controls);
        if (node.id === actions.tutorialId) {
          card.classList.add('is-tutorial');
          card.addEventListener('mouseenter', actions.discover, { once: true });
          card.addEventListener('focusin', actions.discover, { once: true });
        }
      }
    }
    world.append(card);
    if (!node.parent_id || !positions.has(node.parent_id)) continue;
    const parent = positions.get(node.parent_id);
    const parentNode = byId.get(node.parent_id);
    const parentHeight = NODE_SIZE[parentNode.type][1];
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('class', 'onboarding-interview__edge');
    path.setAttribute('d', `M ${parent.x} ${parent.y + parentHeight / 2} Q ${(parent.x + point.x) / 2} ${(parent.y + point.y) / 2} ${point.x} ${point.y - height / 2}`);
    path.setAttribute('marker-end', 'url(#onboard-arrow)');
    svg.append(path);
  }
}

export function renderExistingTree(container, nodes, branch) {
  const frame = el('div', 'desktop-onboarding__tree-frame');
  const viewport = el('div', 'desktop-onboarding__tree-map');
  viewport.tabIndex = 0;
  viewport.setAttribute('role', 'region');
  viewport.setAttribute('aria-label', 'Дерево исследования');
  const branchLabel = el('p', 'desktop-onboarding__tree-branch', branch ? `Ветка: ${branch}` : 'Локальное дерево');
  branchLabel.title = branch || 'Локальное дерево';
  frame.append(viewport, branchLabel);
  container.append(frame);
  if (!nodes.length) {
    viewport.classList.add('is-empty');
    viewport.append(el('p', 'desktop-onboarding__lead', 'В этом дереве пока нет узлов.'));
    return () => {};
  }
  const world = el('div', 'onboarding-interview__world');
  world.innerHTML = `<svg class="onboarding-interview__edges" aria-hidden="true"><defs>
    <linearGradient id="onboard-edge-grad"><stop stop-color="var(--pink)"/><stop offset="1" stop-color="var(--cyan)"/></linearGradient>
    <marker id="onboard-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" fill="var(--cyan)"/></marker>
  </defs></svg>`;
  const children = new Map();
  const ids = new Set(nodes.map(node => node.id));
  for (const node of nodes) {
    const parent = ids.has(node.parent_id) ? node.parent_id : null;
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent).push(node);
  }
  const positions = new Map();
  let cursor = 0;
  function place(node, depth) {
    const kids = children.get(node.id) || [];
    kids.forEach(child => place(child, depth + 1));
    const x = kids.length
      ? (positions.get(kids[0].id).x + positions.get(kids.at(-1).id).x) / 2
      : (cursor++ * 260 + 140);
    positions.set(node.id, { x, y: 80 + depth * 110 });
  }
  (children.get(null) || []).forEach(node => place(node, 0));
  renderTree(world, nodes, { hidden: true }, null, positions);
  const width = Math.max(...[...positions.values()].map(point => point.x)) + 140;
  const height = Math.max(...[...positions.values()].map(point => point.y)) + 80;
  world.style.width = `${width}px`;
  world.style.height = `${height}px`;
  world.querySelector('svg').setAttribute('viewBox', `0 0 ${width} ${height}`);
  viewport.append(world);
  const toolbar = el('div', 'desktop-onboarding__tree-tools');
  const camera = new MindmapCamera(viewport, world);
  const bounds = { x: 0, y: 0, width, height };
  const fit = () => {
    camera.setWorldBounds(bounds);
    camera.maxScale = Math.max(2, camera.minScale);
    camera.fitWorld(64);
  };
  for (const [path, label, action] of [
    ['M5 12h14', 'Уменьшить дерево', () => camera.zoomBy(1 / 1.25)],
    ['M5 12h14M12 5v14', 'Увеличить дерево', () => camera.zoomBy(1.25)],
    ['M9 4H4v5m11-5h5v5M4 15v5h5m11-5v5h-5', 'Показать целиком', fit],
  ]) {
    const control = el('button', 'desktop-onboarding__button');
    control.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;
    control.type = 'button';
    control.setAttribute('aria-label', label);
    control.title = label;
    control.addEventListener('click', action);
    toolbar.append(control);
  }
  viewport.addEventListener('keydown', event => {
    const delta = { ArrowLeft: [40, 0], ArrowRight: [-40, 0], ArrowUp: [0, 40], ArrowDown: [0, -40] }[event.key];
    if (!delta) return;
    event.preventDefault();
    camera.x += delta[0];
    camera.y += delta[1];
    camera._apply();
  });
  frame.append(toolbar);
  const observer = new ResizeObserver(fit);
  observer.observe(viewport);
  return () => observer.disconnect();
}


export async function runOnboardingInterview({ overlay, repoPath = null, workspaceRoot = null, onBack, program, branch, localProject = null, onboarding = false }) {
  const previousFocus = document.activeElement;
  const shell = el('div', 'desktop-onboarding__shell onboarding-interview');
  shell.setAttribute('role', 'dialog');
  shell.setAttribute('aria-modal', 'true');
  shell.setAttribute('aria-labelledby', 'tree-interview-title');
  shell.innerHTML = `
    <header class="desktop-onboarding__header">
      <div class="onboarding-interview__top"><p id="tree-interview-title" class="desktop-onboarding__eyebrow">ResearcherOS</p><span class="onboarding-interview__repo">Репозиторий <strong></strong></span></div>
      <div class="onboarding-interview__toolbar"><ol class="desktop-onboarding__steps" aria-label="Этапы интервью"></ol></div>
      <p class="onboarding-interview__step-hint" role="status"></p>
    </header>
    <div class="onboarding-interview__body">
      <section class="onboarding-interview__chat" aria-label="Интервью">
        <div class="onboarding-interview__tabs view-control" role="group" aria-label="Чат или бриф"><div class="view-control__segmented"><button class="view-control__seg is-active" data-panel="chat" type="button" aria-pressed="true">Чат</button><button class="view-control__seg onboarding-interview__brief-toggle" data-panel="brief" type="button" aria-pressed="false" disabled>Бриф</button></div></div>
        <div class="onboarding-interview__brief-panel" aria-label="Бриф построения дерева" role="region" hidden></div>
        <div class="onboarding-interview__messages" role="log" aria-live="polite"></div>
        <div class="onboarding-interview__composer">
          <div class="onboarding-interview__input-wrap">
            <textarea id="tree-interview-answer" class="onboarding-interview__input" rows="1" placeholder="Ваш ответ…" aria-label="Ваш ответ"></textarea>
            <select class="agent-cli-select" aria-label="Выбрать агента"><option value="cursor">Cursor</option><option value="codex">Codex</option></select>
            <button class="btn btn-primary agent-chat-send onboarding-interview__send" type="button" aria-label="Отправить сообщение" title="Отправить сообщение"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5m0 0-6 6m6-6 6 6"/></svg></button>
          </div>
          <button class="desktop-onboarding__button desktop-onboarding__button--primary onboarding-interview__finish" type="button" hidden>Создать проект с этим деревом</button>
          <p class="onboarding-interview__error" role="alert"></p>
        </div>
      </section>
      <section class="onboarding-interview__map" aria-label="Дерево исследования">
        <div class="onboarding-interview__world">
          <svg class="onboarding-interview__edges" viewBox="0 0 720 650" aria-hidden="true"><defs>
            <linearGradient id="onboard-edge-grad" x1="0%" y1="0%" x2="100%"><stop offset="0%" stop-color="#ff6bcb"/><stop offset="50%" stop-color="#7b5cff"/><stop offset="100%" stop-color="#3de8ff"/></linearGradient>
            <marker id="onboard-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" fill="#3de8ff"/></marker>
          </defs></svg>
          <div class="onboarding-interview__empty">${activitySvg()}<span>Здесь появится дерево вашего исследования</span></div>
        </div>
      </section>
    </div>
    <footer class="desktop-onboarding__footer"><button class="onboarding-interview__back" type="button">← Назад</button></footer>`;
  overlay.replaceChildren(shell);
  shell.querySelector('.onboarding-interview__repo strong').textContent = repoPath?.split('/').filter(Boolean).at(-1) || localProject?.title || '';
  const messages = shell.querySelector('.onboarding-interview__messages');
  const textarea = shell.querySelector('textarea');
  const send = shell.querySelector('.onboarding-interview__send');
  const agentSelect = shell.querySelector('.agent-cli-select');
  try { agentSelect.value = localStorage.getItem('koi-chat-cli-agent') === 'codex' ? 'codex' : 'cursor'; } catch { /* private mode */ }
  agentSelect.addEventListener('change', () => {
    try { localStorage.setItem('koi-chat-cli-agent', agentSelect.value); } catch { /* private mode */ }
  });
  const finish = shell.querySelector('.onboarding-interview__finish');
  const error = shell.querySelector('.onboarding-interview__error');
  const back = shell.querySelector('.onboarding-interview__back');
  const world = shell.querySelector('.onboarding-interview__world');
  const steps = shell.querySelector('.desktop-onboarding__steps');
  const empty = shell.querySelector('.onboarding-interview__empty');
  const progress = shell.querySelector('.onboarding-interview__step-hint');
  let state = null;
  let busy = false;
  const localSessionKey = localProject ? `researchos-tree-interview:${localProject.tag}` : null;
  const address = () => ({ repo_path: repoPath, branch, session_id: state?.session_id });

  async function mutate(decision, node) {
    if (busy) return;
    error.textContent = ''; setBusy(true, 'Обновляем дерево…');
    try {
      state = await post('/api/desktop/onboarding/interview/reply', { ...address(), decision, node });
      render();
    } finally { setBusy(false); }
  }
  async function discoverEditing() {
    if (busy || !state?.tutorial_required || state.tutorial_seen) return;
    try { await mutate('tutorial_seen'); }
    catch (problem) { error.textContent = problem.message; }
  }
  function editNode(node, adding = false, childType = null) {
    if (busy) return;
    const dialog = el('dialog', 'onboarding-interview__brief-dialog');
    dialog.setAttribute('aria-label', adding ? 'Добавить узел' : 'Редактировать узел');
    const header = el('header', 'desktop-onboarding__header');
    const cancel = el('button', 'desktop-onboarding__button', 'Отмена'); cancel.type = 'button';
    cancel.addEventListener('click', () => dialog.close());
    header.append(el('h2', '', adding ? 'Добавить узел' : 'Редактировать узел'), cancel);
    const form = el('form', 'onboarding-interview__node-form');
    const field = (name, control) => { const label = el('label', 'desktop-onboarding__field', name); control.id = `node-field-${form.children.length}`; label.htmlFor = control.id; form.append(label, control); return control; };
    const kind = el('select');
    for (const type of CHILD_TYPES[node.type] || []) { const option = el('option', '', TYPE_LABELS[type]); option.value = type; kind.append(option); }
    if (adding) { field('Тип узла', kind); if (childType) kind.value = childType; }
    const title = field('Название', el('input')); title.required = true; title.maxLength = 180; title.value = adding ? '' : node.title;
    const description = field('Описание', el('textarea')); description.rows = 4; description.maxLength = 4000; description.value = adding ? '' : node.description;
    const parent = adding ? node : state.nodes.find(item => item.id === node.parent_id);
    const edge = el('select');
    for (const [value, label] of [['hypothesis', 'Гипотеза'], ['evidence', 'Доказательство']]) { const option = el('option', '', label); option.value = value; edge.append(option); }
    const edgeLabel = el('input'); edgeLabel.maxLength = 1500;
    if (parent?.node_type === 'problem' || parent?.type === 'problem') {
      field('Связь с проблемой', edge); field('Формулировка связи', edgeLabel);
      edge.value = adding ? 'hypothesis' : node.edge_type; edgeLabel.value = adding ? '' : node.edge_label;
    }
    const formError = el('p', 'onboarding-interview__error'); formError.setAttribute('role', 'alert');
    const save = el('button', 'desktop-onboarding__button desktop-onboarding__button--primary', adding ? 'Добавить узел' : 'Сохранить изменения'); save.type = 'submit';
    form.append(formError, save);
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (busy) return; save.disabled = true;
      const problemParent = parent?.node_type === 'problem' || parent?.type === 'problem';
      try {
        await mutate(adding ? 'add_node' : 'edit_node', { id: node.id, parent_id: node.id, node_type: kind.value, title: title.value.trim(), description: description.value.trim(), edge_type: problemParent ? edge.value : 'direction', edge_label: problemParent ? edgeLabel.value.trim() : '' });
        dialog.close();
      } catch (problem) { formError.textContent = problem.message; }
      finally { save.disabled = false; }
    });
    dialog.append(header, form); shell.append(dialog);
    dialog.addEventListener('close', () => { dialog.remove(); world.querySelector(`[data-node-id="${node.id}"]`)?.focus(); }, { once: true });
    dialog.showModal(); title.focus();
  }

  function sizeInput() {
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }
  function renderBrief(entry) {
    const brief = el('div', 'onboarding-interview__brief');
    brief.append(el('h2', '', 'Бриф'));
    for (const section of entry.brief || []) {
      const heading = el('h3', '', section.title);
      const scroll = el('div', 'onboarding-interview__brief-scroll');
      scroll.tabIndex = 0;
      scroll.setAttribute('role', 'region');
      scroll.setAttribute('aria-label', section.title);
      const table = el('table');
      const head = el('thead');
      const titles = el('tr');
      for (const text of ['Тип узла', 'Вопрос', 'Мой ответ', 'Нужно ли уточнение', 'Что уточнить?']) {
        const th = el('th', '', text); th.scope = 'col'; titles.append(th);
      }
      head.append(titles);
      const body = el('tbody');
      for (const row of section.rows) {
        const tr = el('tr');
        for (const text of [row.node_type, row.question, `${row.answer} (${row.source})`, row.needs_clarification ? 'Да' : 'Нет', row.clarification || '—']) tr.append(el('td', '', text));
        body.append(tr);
      }
      table.append(head, body); scroll.append(table); brief.append(heading, scroll);
    }
    const question = entry.question;
    brief.append(el('h3', '', 'Неуверенность в дереве и текущее уточнение'));
    brief.append(el('p', '', question ? `${question.target_title || question.target_id}: ${question.text}` : 'Структурных уточнений нет.'));
    if (question) for (const variant of question.alternatives) brief.append(el('p', '', variant));
    brief.append(el('h3', '', 'Ответы пользователя'));
    for (const answer of state.messages.slice(0, state.messages.indexOf(entry)).filter(item => item.role === 'user')) {
      brief.append(el('p', '', `${answer.question_text || 'Описание проекта'} — ${answer.text}`));
    }
    if (question) brief.append(el('p', '', `${question.text} — ожидается`));
    brief.append(el('h3', '', 'Изменения дерева'), el('p', '', entry.changes || 'Нет'));
    brief.append(el('h3', '', 'Лимиты'), el('p', '', `Вопросы: ${entry.question_count}/4; подтверждения: ${entry.confirmation_count}/2`));
    return brief;
  }
  function messageRow(entry) {
    const row = el('div', `onboarding-interview__row ${entry.role === 'user' ? 'is-user' : 'is-agent'}`);
    const bubble = el('div', 'onboarding-interview__bubble');
    bubble.append(el('p', 'onboarding-interview__question', entry.text));
    if (entry.role !== 'user') row.append(el('span', 'onboarding-interview__avatar', '✦'));

    row.append(bubble);
    return row;
  }
  const inspect = shell.querySelector('.onboarding-interview__brief-toggle');
  const briefPanel = shell.querySelector('.onboarding-interview__brief-panel');
  const composer = shell.querySelector('.onboarding-interview__composer');
  let activePanel = 'chat';
  function showPanel(panel) {
    activePanel = panel;
    messages.hidden = panel !== 'chat';
    composer.hidden = panel !== 'chat';
    briefPanel.hidden = panel !== 'brief';
    for (const button of shell.querySelectorAll('[data-panel]')) {
      button.classList.toggle('is-active', button.dataset.panel === panel);
      button.setAttribute('aria-pressed', String(button.dataset.panel === panel));
    }
  }
  for (const button of shell.querySelectorAll('[data-panel]')) button.addEventListener('click', () => showPanel(button.dataset.panel));
  function setBusy(value, label = '') {
    busy = value;
    shell.setAttribute('aria-busy', String(value));
    textarea.disabled = value;
    send.disabled = value;
    agentSelect.disabled = value;
    finish.disabled = value || !state?.complete || Boolean(state?.tutorial_required && !state?.tutorial_seen);
    back.disabled = value;
    inspect.disabled = !state?.nodes.length || !state?.messages.some(entry => entry.brief);
    messages.querySelector('[data-loading]')?.remove();
    if (value) {
      const loading = el('div', 'onboarding-interview__row is-agent onboarding-interview__typing');
      loading.dataset.loading = 'true'; loading.setAttribute('role', 'status');
      const bubble = el('div', 'onboarding-interview__bubble');
      const dots = el('span', 'onboarding-interview__dots'); dots.setAttribute('aria-hidden', 'true');
      dots.append(el('i'), el('i'), el('i'));
      bubble.append(el('span', 'onboarding-interview__typing-label', label || `${agentSelect.selectedOptions[0].textContent} изучает материалы и обновляет дерево…`), dots);
      loading.append(el('span', 'onboarding-interview__avatar', '✦'), bubble); messages.append(loading);
      messages.scrollTop = messages.scrollHeight;
    }
  }
  function render() {
    messages.replaceChildren(...state.messages.map(messageRow));
    const briefEntry = state.messages.findLast(entry => entry.brief);
    briefPanel.replaceChildren(...(briefEntry ? [renderBrief(briefEntry)] : []));
    showPanel(activePanel);
    const nodes = state.nodes.map(node => ({ ...node, type: node.node_type }));
    const tutorialId = state.complete && state.tutorial_required && !state.tutorial_seen ? nodes.find(node => CHILD_TYPES[node.type]?.length)?.id : null;
    renderTree(world, nodes, empty, state.question?.target_id, layoutNodes(nodes), { edit: node => editNode(node), add: (node, type) => editNode(node, true, type), rename: async (node, title) => { try { await mutate('edit_node', { ...node, title }); } catch (problem) { error.textContent = problem.message; } }, tutorialId, discover: discoverEditing });
    const points = [...layoutNodes(nodes).values()];
    const width = Math.max(720, ...points.map(point => point.x + 140));
    const height = Math.max(650, ...points.map(point => point.y + 80));
    world.style.width = `${width}px`; world.style.height = `${height}px`;
    world.querySelector('svg').setAttribute('viewBox', `0 0 ${width} ${height}`);
    const current = state.phase === 'description' ? 0 : state.complete ? 2 : 1;
    steps.replaceChildren(...['Описание', 'Дерево', 'Уточнения'].map((title, index) => {
      const item = el('li', `desktop-onboarding__step${index < current || state.complete ? ' is-done' : index === current ? ' is-active' : ''}`);
      if (index === current && !state.complete) item.setAttribute('aria-current', 'step');
      item.append(el('span', 'desktop-onboarding__step-index', index < current || state.complete ? '✓' : String(index + 1)), el('span', '', title));
      return item;
    }));
    progress.textContent = state.phase === 'description' ? 'Описание → дерево → уточнения структуры' : `Вопросы: ${state.question_count}/4 · Подтверждения: ${state.confirmation_count}/2`;
    finish.hidden = !state.complete;
    shell.querySelector('.onboarding-interview__input-wrap').hidden = false;
    textarea.placeholder = state.phase === 'description' ? 'Хочу исследовать…' : state.complete ? 'Что исправить в дереве?' : 'Ответ одним предложением…';
    const last = messages.lastElementChild;
    if (last) messages.scrollTop = Math.max(0, last.offsetTop - messages.offsetTop);
  }
  async function submit() {
    const answer = textarea.value.trim();
    if (busy || !state || !answer) return;
    error.textContent = '';
    const pending = messageRow({ role: 'user', text: answer });
    pending.dataset.pending = 'true'; messages.append(pending);
    textarea.value = ''; sizeInput(); setBusy(true);
    try {
      state = await post('/api/desktop/onboarding/interview/reply', { ...address(), answer, cli_agent: agentSelect.value });
      render();
    } catch (problem) {
      pending.remove(); textarea.value = answer; sizeInput(); error.textContent = problem.message;
    }
    finally { setBusy(false); }
    textarea.focus();
  }
  send.addEventListener('click', () => { void submit(); });
  textarea.addEventListener('input', sizeInput);
  textarea.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); void submit(); }
  });
  shell.addEventListener('keydown', event => {
    if (event.key !== 'Tab' || shell.querySelector('dialog[open]')) return;
    const controls = [...shell.querySelectorAll('button:not(:disabled), textarea:not(:disabled), select:not(:disabled), [tabindex="0"]')].filter(node => node.getClientRects().length);
    const first = controls[0], last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  });
  back.addEventListener('click', () => { if (!busy) { onBack(); if (previousFocus?.isConnected) previousFocus.focus(); } });
  finish.addEventListener('click', async () => {
    if (busy || !state?.complete || (state.tutorial_required && !state.tutorial_seen)) return;
    error.textContent = ''; setBusy(true);
    try {
      const created = await post('/api/desktop/onboarding/interview/finish', { path: repoPath, branch, session_id: state.session_id });
      if (localSessionKey) sessionStorage.removeItem(localSessionKey);
      window.location.replace(`/?project=${encodeURIComponent(created.project_id)}`);
    } catch (problem) { error.textContent = problem.message; setBusy(false); }
  });
  setBusy(true);
  try {
    state = await post('/api/desktop/onboarding/interview/start', { repo_path: repoPath, workspace_root: workspaceRoot, branch, project_tag: localProject?.tag, title: localProject?.title, program_id: program?.id, program_title: program?.title, session_id: localSessionKey ? sessionStorage.getItem(localSessionKey) : null, onboarding });
    if (localSessionKey) sessionStorage.setItem(localSessionKey, state.session_id);
    render();
    if (localProject?.description && state.phase === 'description') textarea.value = localProject.description;
  } catch (problem) { error.textContent = problem.message; }
  finally { setBusy(false); }
  textarea.focus(); sizeInput();
}
