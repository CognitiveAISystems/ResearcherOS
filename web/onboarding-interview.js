import { MindmapCamera } from './lab-canvas.js';

const PHASE_SLOT = { problem: 0, cause: 1, branch: 2, hypothesis: 2, evidence: 2, method: 3 };
const PHASE_TYPE = { problem: 'problem', cause: 'cause', hypothesis: 'remediation', evidence: 'cause_evidence', method: 'method' };
const TYPE_LABELS = {
  problem: 'Проблема', cause: 'Причина', remediation: 'Гипотеза',
  cause_evidence: 'Доказательство', method: 'Метод', experiment: 'Эксперимент',
};
const NODE_SIZE = {
  problem: [220, 105, '50%'], cause: [182, 80, '12px'],
  remediation: [170, 72, '4px'], cause_evidence: [170, 72, '12px'],
  method: [165, 68, '6px'], experiment: [165, 68, '6px'],
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

async function post(url, payload) {
  const response = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
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
  const layer = { problem: 0, cause: 1, remediation: 2, cause_evidence: 2, method: 3 };
  const byLayer = [[], [], [], []];
  for (const node of nodes) byLayer[layer[node.type]].push(node);
  const positions = new Map();
  byLayer.forEach((items, depth) => {
    const gap = depth === 0 ? 0 : Math.min(195, 610 / Math.max(1, items.length));
    items.forEach((node, index) => positions.set(node.id, {
      x: 360 + (index - (items.length - 1) / 2) * gap,
      y: 105 + depth * 145,
    }));
  });
  return positions;
}

function renderTree(world, nodes, empty, pendingId, positions = layoutNodes(nodes)) {
  world.querySelectorAll('.onboarding-interview__node').forEach((node) => node.remove());
  const svg = world.querySelector('.onboarding-interview__edges');
  svg.querySelectorAll('.onboarding-interview__edge').forEach((edge) => edge.remove());
  empty.hidden = nodes.length > 0;
  const byId = new Map(nodes.map((node) => [node.id, node]));
  for (const node of nodes) {
    const point = positions.get(node.id);
    const [width, height, radius] = NODE_SIZE[node.type];
    const card = el('div', `map-node onboarding-interview__node ${node.type}`);
    if (node.id === pendingId) card.classList.add('is-pending');
    card.style.left = `${point.x}px`;
    card.style.top = `${point.y}px`;
    card.style.width = `${width}px`;
    card.style.height = `${height}px`;
    card.style.borderRadius = radius;
    card.title = node.description;
    card.append(el('span', 'node-label', TYPE_LABELS[node.type]), el('span', 'node-title', node.title));
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
  const branchLabel = el('p', 'desktop-onboarding__tree-branch', `Ветка: ${branch}`);
  branchLabel.title = branch;
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

export async function runOnboardingInterview({ overlay, repoPath, workspaceRoot, onBack, program, branch }) {
  const shell = el('div', 'desktop-onboarding__shell onboarding-interview');
  shell.setAttribute('role', 'dialog');
  shell.setAttribute('aria-modal', 'true');
  shell.setAttribute('aria-label', 'Интервью о новом проекте');
  shell.innerHTML = `
    <header class="desktop-onboarding__header">
      <div class="onboarding-interview__top"><p class="desktop-onboarding__eyebrow">ResearcherOS</p><span class="onboarding-interview__repo">Репозиторий <strong></strong></span></div>
      <ol class="desktop-onboarding__steps" aria-label="Этапы интервью"></ol>
      <p class="onboarding-interview__step-hint">Выберите заполненный этап, чтобы изменить узел. Все следующие узлы нужно будет заполнить заново.</p>
    </header>
    <div class="onboarding-interview__body">
      <section class="onboarding-interview__chat" aria-label="Интервью">
        <div class="onboarding-interview__messages" role="log" aria-live="polite"></div>
        <div class="onboarding-interview__composer">
          <p class="onboarding-interview__edit-hint" role="status" hidden>Измените формулировку и отправьте её. Следующие узлы нужно заполнить заново.</p>
          <div class="onboarding-interview__input-wrap">
            <textarea class="onboarding-interview__input" rows="1" placeholder="Ваш ответ…" aria-label="Ваш ответ"></textarea>
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
  const steps = shell.querySelector('.desktop-onboarding__steps');
  const messages = shell.querySelector('.onboarding-interview__messages');
  const textarea = shell.querySelector('.onboarding-interview__input');
  const send = shell.querySelector('.onboarding-interview__send');
  const editHint = shell.querySelector('.onboarding-interview__edit-hint');
  const finish = shell.querySelector('.onboarding-interview__finish');
  const error = shell.querySelector('.onboarding-interview__error');
  const world = shell.querySelector('.onboarding-interview__world');
  const empty = shell.querySelector('.onboarding-interview__empty');
  shell.querySelector('.onboarding-interview__repo strong').textContent = repoPath.split('/').filter(Boolean).at(-1) || repoPath;
  let state = null;
  let busy = false;

  function sizeInput() {
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 180)}px`;
  }
  function messageRow(entry, choosable) {
    const row = el('div', `onboarding-interview__row ${entry.role === 'user' ? 'is-user' : 'is-agent'}`);
    if (entry.role !== 'user') row.append(el('span', 'onboarding-interview__avatar', '✦'));
    const bubble = el('div', 'onboarding-interview__bubble');
    const question = el('p', 'onboarding-interview__question');
    const split = entry.text.indexOf('\n');
    const lead = split === -1 ? entry.text : entry.text.slice(0, split);
    if (entry.role !== 'user' && (lead.startsWith('Опишите') || lead.startsWith('Что делать дальше'))) {
      question.append(el('strong', null, lead));
      if (split !== -1) question.append(document.createTextNode(entry.text.slice(split)));
    } else {
      question.textContent = entry.text;
    }
    bubble.append(question);
    const choices = entry.options || [];
    if (entry.role !== 'user' && choices.length >= 2) {
      const list = el('ol', 'onboarding-interview__choices');
      choices.forEach((choice, index) => {
        const item = el('li');
        const number = String(index + 1);
        if (choosable) {
          const button = el('button', 'onboarding-interview__pick', number);
          button.type = 'button';
          button.setAttribute('aria-label', `Вариант ${number}`);
          button.addEventListener('click', () => { void submit(choice, 'answer'); });
          item.append(button);
        } else {
          item.append(el('span', 'onboarding-interview__pick is-static', number));
        }
        item.append(el('span', 'onboarding-interview__choice', choice));
        list.append(item);
      });
      bubble.append(list);
    }
    row.append(bubble);
    return row;
  }
  function typingRow() {
    const row = el('div', 'onboarding-interview__row is-agent onboarding-interview__typing');
    row.dataset.loading = 'true';
    row.setAttribute('role', 'status');
    row.setAttribute('aria-label', 'Обновляем дерево…');
    const bubble = el('div', 'onboarding-interview__bubble');
    bubble.innerHTML = '<span class="onboarding-interview__typing-label">Обновляем дерево…</span><span class="onboarding-interview__dots" aria-hidden="true"><i></i><i></i><i></i></span>';
    row.append(el('span', 'onboarding-interview__avatar', '✦'), bubble);
    return row;
  }
  function setBusy(value) {
    busy = value;
    send.disabled = value || Boolean(state?.complete);
    steps.querySelectorAll('button').forEach(button => { button.disabled = value || button.dataset.available !== 'true'; });
    messages.querySelectorAll('.onboarding-interview__pick').forEach((button) => { button.disabled = value; });
    finish.disabled = value;
    textarea.disabled = value || Boolean(state?.complete);
    if (value) {
      messages.querySelector('[data-loading]')?.remove();
      messages.append(typingRow());
      messages.scrollTop = messages.scrollHeight;
    } else {
      messages.querySelector('[data-loading]')?.remove();
    }
  }
  function render() {
    if (!state) return;
    const proving = state.track === 'evidence' || state.phase === 'evidence';
    const choosing = state.phase === 'branch';
    const stepsModel = [
      ['problem', 'Проблема'],
      ['cause', 'Причина'],
      [proving ? 'evidence' : (choosing ? 'branch' : 'hypothesis'), proving ? 'Доказательство' : (choosing ? 'Выбор' : 'Гипотеза')],
      ['method', 'Метод'],
    ];
    const active = PHASE_SLOT[state.phase] ?? 0;
    steps.replaceChildren(...stepsModel.map(([phase, title], index) => {
      const item = el('li');
      const step = el('button', 'desktop-onboarding__step onboarding-interview__step');
      const filled = state.nodes.some(node => node.type === PHASE_TYPE[phase]);
      step.type = 'button';
      step.dataset.available = String(filled);
      step.disabled = busy || !filled;
      step.setAttribute('aria-label', `Редактировать узел «${title}»`);
      if (index < active || state.complete) step.classList.add('is-done');
      else if (index === active) { step.classList.add('is-active'); step.setAttribute('aria-current', 'step'); }
      step.append(el('span', 'desktop-onboarding__step-index', index < active || state.complete ? '✓' : String(index + 1)), el('span', '', title));
      step.addEventListener('click', () => { void rewind(phase); });
      item.append(step);
      return item;
    }));
    const last = state.messages.length - 1;
    messages.replaceChildren(...state.messages.map((entry, index) => messageRow(entry, !state.complete && index === last)));
    messages.scrollTop = messages.scrollHeight;
    const editingNode = state.nodes.find(node => node.type === PHASE_TYPE[state.editing_phase]);
    renderTree(world, state.nodes, empty, editingNode?.id);
    const choices = state.complete ? [] : (state.messages[last]?.options || []);
    editHint.hidden = !state.editing_phase;
    textarea.value = state.edit_answer || '';
    textarea.placeholder = state.phase === 'branch' ? 'Выберите 1 или 2…' : (choices.length >= 2 ? 'Или напишите свой вариант…' : 'Ваш ответ…');
    finish.hidden = !state.complete;
    textarea.hidden = state.complete;
    send.hidden = state.complete;
    shell.querySelector('.onboarding-interview__input-wrap').hidden = state.complete;
    send.disabled = state.complete;
    sizeInput();
  }
  async function start() {
    setBusy(true);
    error.textContent = '';
    try {
      const payload = { repo_path: repoPath, workspace_root: workspaceRoot, branch };
      if (program?.title) payload.program_title = program.title;
      else if (program?.id) payload.program_id = program.id;
      state = await post('/api/desktop/onboarding/interview/start', payload);
      render();
    } catch (problem) {
      error.textContent = problem.message;
    } finally { setBusy(false); }
    (state?.complete ? finish : textarea).focus();
  }
  async function rewind(phase) {
    if (busy || !state) return;
    error.textContent = '';
    setBusy(true);
    let changed = false;
    try {
      state = await post('/api/desktop/onboarding/interview/reply', { repo_path: repoPath, branch, decision: 'rewind', phase });
      render();
      changed = true;
    } catch (problem) {
      error.textContent = problem.message;
    } finally { setBusy(false); }
    if (changed) {
      textarea.focus();
      textarea.setSelectionRange(0, textarea.value.length);
    }
  }
  async function submit(answer, decision) {
    if (busy || !state || state.complete) return;
    if (!answer) return;
    error.textContent = '';
    const pending = messageRow({ role: 'user', text: answer });
    pending.dataset.pending = 'true';
    messages.append(pending);
    textarea.value = '';
    sizeInput();
    setBusy(true);
    try {
      state = await post('/api/desktop/onboarding/interview/reply', { repo_path: repoPath, answer, decision, branch });
      render();
    } catch (problem) {
      pending?.remove();
      textarea.value = answer;
      sizeInput();
      error.textContent = problem.message;
    } finally { setBusy(false); }
    (state?.complete ? finish : textarea).focus();
  }
  function reply() { return submit(textarea.value.trim(), 'answer'); }
  send.addEventListener('click', reply);
  textarea.addEventListener('input', sizeInput);
  textarea.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void reply(); }
  });
  finish.addEventListener('click', async () => {
    if (busy || !state?.complete) return;
    setBusy(true);
    error.textContent = '';
    try {
      const created = await post('/api/desktop/onboarding/interview/finish', { path: repoPath, branch });
      window.location.replace(`/?project=${encodeURIComponent(created.project_id)}`);
    } catch (problem) {
      error.textContent = problem.message;
      setBusy(false);
    }
  });
  shell.querySelector('.onboarding-interview__back').addEventListener('click', () => { if (!busy) onBack(); });
  await start();
}
