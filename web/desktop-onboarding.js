import { activitySvg, renderExistingTree, runOnboardingInterview } from './onboarding-interview.js';

const desktop = window.researchOSDesktop;

if (desktop) {
  const reconfigure = new URLSearchParams(window.location.search).get('onboarding') === '1';
  const overlay = document.createElement('div');
  overlay.className = 'desktop-onboarding';
  const state = { step: 'welcome', repo: null, repositoryPath: '', treePath: '', workspace: null, locations: [], busy: false, error: '' };
  const primary = 'desktop-onboarding__button--primary';
  let disposeTreePreview = () => {};

  function element(tag, className, text) {
    const node = document.createElement(tag);
    node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function button(action, text, variant = '') {
    const node = element('button', `desktop-onboarding__button ${variant}`, text);
    node.type = 'button';
    node.dataset.action = action;
    node.disabled = state.busy;
    return node;
  }

  function render() {
    disposeTreePreview();
    const focusedAction = overlay.contains(document.activeElement) ? document.activeElement.dataset.action || document.activeElement.dataset.focus : null;
    const titles = {
      welcome: 'Подключались ли вы с этого ноутбука к ResearcherOS?',
      tree: 'Откройте свои исследования',
      repository: 'Выберите репозиторий проекта, который хотите подключить',
      existing: 'В репозитории уже есть дерево',
    };
    overlay.replaceChildren();
    const shell = element('div', `desktop-onboarding__shell desktop-onboarding__shell--entry is-${state.step}`);
    shell.setAttribute('role', 'dialog');
    shell.setAttribute('aria-modal', 'true');
    shell.setAttribute('aria-labelledby', 'desktop-onboarding-title');
    shell.setAttribute('aria-busy', String(state.busy));
    const header = element('header', 'desktop-onboarding__header');
    const heading = element('h1', '', titles[state.step]);
    heading.id = 'desktop-onboarding-title';
    header.append(heading);
    const main = element('div', 'desktop-onboarding__body');
    const actions = element('div', 'desktop-onboarding__entry-actions');
    if (state.step !== 'existing') {
      const activity = element('div', 'desktop-onboarding__activity');
      activity.setAttribute('aria-hidden', 'true');
      activity.innerHTML = activitySvg();
      main.append(activity);
    }

    if (state.step === 'welcome') {
      actions.append(button('new-user', 'Нет', primary), button('returning-user', 'Да'));
    } else if (state.step === 'tree') {
      const guidance = state.findingTrees || state.error
        ? 'Выберите папку tree с проектами, которые уже подключали к ResearcherOS.'
        : state.locations.length > 1
          ? 'ResearcherOS нашёл несколько папок с исследованиями. Выберите подходящую из списка или укажите другую папку.'
          : state.locations.length === 1
            ? 'ResearcherOS нашёл папку с исследованиями. Откройте её или укажите другую папку.'
            : 'ResearcherOS не нашёл папку с исследованиями автоматически. Укажите её самостоятельно.';
      main.append(element('p', 'desktop-onboarding__lead desktop-onboarding__guidance', guidance));
      const field = element('div', 'desktop-onboarding__field desktop-onboarding__tree-field');
      const label = element('label', '', 'Папка с исследованиями');
      label.htmlFor = 'desktop-onboarding-tree-location';
      const row = element('div', 'desktop-onboarding__folder-row');
      const select = document.createElement('select');
      select.id = label.htmlFor;
      select.dataset.focus = 'tree-location';
      if (!state.locations.length) {
        const empty = element('option', '', 'Папка не найдена');
        empty.value = '';
        select.append(empty);
      }
      state.locations.forEach(tree => {
        const home = state.homePath;
        const displayPath = home && tree.tree_root.startsWith(home) && /[/\\]/.test(tree.tree_root[home.length] || '') ? `~${tree.tree_root.slice(home.length)}` : tree.tree_root;
        const option = element('option', '', displayPath);
        option.value = tree.tree_root;
        select.append(option);
      });
      select.value = state.treePath;
      select.title = state.treePath;
      select.disabled = state.busy || !state.locations.length;
      select.addEventListener('change', () => { state.treePath = select.value; render(); });
      const open = button('open-tree', 'Открыть исследования', primary);
      open.disabled = state.busy || !state.treePath;
      row.append(select, open);
      field.append(label, row);
      main.append(field);
      actions.append(button('choose-tree', 'Указать другую папку', 'desktop-onboarding__button--manual'));
    } else if (state.step === 'repository') {
      const row = element('div', 'desktop-onboarding__repository-row');
      const path = element('output', 'desktop-onboarding__path', state.repositoryPath || 'Папка не выбрана');
      path.setAttribute('aria-label', 'Путь к репозиторию');
      path.setAttribute('aria-live', 'polite');
      row.append(button('choose-repository', 'Выбрать репозиторий', primary), path);
      main.append(row);
    } else if (state.step === 'existing') {
      if (state.repo.trees.length > 1) {
        const label = element('label', 'desktop-onboarding__field', 'Выберите дерево для продолжения.');
        const select = document.createElement('select');
        state.repo.trees.forEach(tree => {
          const option = element('option', '', `${tree.title} · ${tree.branch}`);
          option.value = tree.branch;
          select.append(option);
        });
        select.value = state.selectedBranch;
        select.disabled = state.busy;
        select.addEventListener('change', () => { state.selectedBranch = select.value; render(); });
        label.append(select);
        main.append(label);
      }
      const tree = state.repo.trees.find(item => item.branch === state.selectedBranch);
      const preview = element('section', 'desktop-onboarding__tree-preview');
      preview.append(element('h2', 'desktop-onboarding__panel-title', tree.title));
      disposeTreePreview = renderExistingTree(preview, tree.nodes, tree.branch);
      main.append(preview);
      actions.append(button('continue-tree', 'Продолжить в этом дереве', primary), button('new-tree', 'Создать новое дерево'));
    }
    if (state.step !== 'existing') main.append(actions);
    const status = element('p', 'desktop-onboarding__lead', state.busy ? state.busyText : '');
    status.setAttribute('role', 'status');
    status.hidden = !state.busy;
    main.append(status);
    const footer = element('footer', 'desktop-onboarding__footer');
    if (state.step === 'existing') {
      footer.append(actions);
    }
    if (state.step !== 'welcome') footer.append(button('back', 'Назад', 'desktop-onboarding__button--back'));
    const error = element('p', 'desktop-onboarding__error', state.error);
    error.setAttribute('role', 'alert');
    footer.append(error);
    shell.append(header, main);
    if (state.step !== 'welcome' || state.error) shell.append(footer);
    if (reconfigure && state.previousWorkspace) {
      const close = button('keep-current', '×', 'desktop-onboarding__close');
      close.setAttribute('aria-label', 'Закрыть настройку');
      shell.append(close);
    }
    overlay.append(shell);
    if (!state.busy) {
      const previous = [...shell.querySelectorAll('button, select')].find(node => !node.disabled && (node.dataset.action || node.dataset.focus) === focusedAction);
      (previous || shell.querySelector('[data-action="continue-tree"]') || main.querySelector('select:not(:disabled), button:not(:disabled)'))?.focus();
    }
  }

  async function request(url, payload, method = 'POST') {
    const response = await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Не удалось выполнить действие.');
    return data;
  }

  async function openTree(path) {
    const tree = await request('/api/desktop/onboarding/existing-tree', { path });
    await request('/api/desktop/workspace-root', { workspace_root: tree.workspace_root }, 'PUT');
    window.location.replace('/');
  }

  async function interview(branch) {
    disposeTreePreview();
    await runOnboardingInterview({
      overlay, repoPath: state.repo.repo_path, workspaceRoot: state.workspace,
      branch, onBack: render,
    });
  }

  async function act(action) {
    state.error = '';
    if (action === 'new-tree') { await interview(state.repo.next_branch); return; }
    if (action === 'keep-current') { window.location.replace('/'); return; }
    if (action === 'new-user' || action === 'back') {
      state.step = action === 'new-user' || state.step === 'existing' ? 'repository' : 'welcome';
      state.repo = null;
      render();
      return;
    }
    if (action === 'returning-user') state.step = 'tree';
    state.findingTrees = action === 'returning-user';
    state.busyText = ({ 'returning-user': 'Ищем папку tree…', 'choose-tree': 'Проверяем папку…', 'choose-repository': 'Проверяем репозиторий…' })[action] || 'Открываем исследования…';
    state.busy = true;
    render();
    let createTree = false;
    try {
      if (action === 'returning-user') {
        const found = await request('/api/desktop/onboarding/tree-locations', undefined, 'GET');
        state.locations = found.trees;
        state.treePath = state.locations.some(tree => tree.tree_root === state.treePath) ? state.treePath : state.locations[0]?.tree_root || '';
      } else if (action === 'choose-tree') {
        const path = await desktop.chooseDirectory('workspace');
        if (path) {
          const tree = await request('/api/desktop/onboarding/existing-tree', { path });
          if (!state.locations.some(item => item.tree_root === tree.tree_root)) state.locations.push(tree);
          state.treePath = tree.tree_root;
        }
      } else if (action === 'open-tree') {
        await openTree(state.treePath);
      } else if (action === 'choose-repository') {
        const path = await desktop.chooseDirectory('repository');
        if (path) {
          state.repositoryPath = path;
          render();
          state.repo = await request('/api/desktop/onboarding/git-project', { path });
          if (state.repo.branch_exists) {
            state.selectedBranch = state.repo.branch;
            state.step = 'existing';
          } else createTree = true;
        }
      } else if (action === 'continue-tree') {
        const connected = await request('/api/desktop/onboarding/connect', {
          repo_path: state.repo.repo_path, workspace_root: state.workspace,
          require_existing: true, branch: state.selectedBranch,
        });
        window.location.replace(`/?project=${encodeURIComponent(connected.project_id)}`);
      }
    } catch (problem) {
      state.error = problem.message || String(problem);
    } finally {
      state.busy = false;
      state.findingTrees = false;
      if (!createTree) render();
    }
    if (createTree) await interview();
  }

  overlay.addEventListener('click', event => {
    const action = event.target.closest('button[data-action]')?.dataset.action;
    if (action && !state.busy) void act(action);
  });
  overlay.addEventListener('keydown', event => {
    if (!overlay.querySelector('.desktop-onboarding__shell--entry')) return;
    if (event.key === 'Escape' && !state.busy && state.step !== 'welcome') {
      event.preventDefault();
      void act('back');
    }
    if (event.key === 'Tab') {
      const controls = [...overlay.querySelectorAll('button:not(:disabled), select:not(:disabled), [tabindex="0"]')];
      if (!controls.length) { event.preventDefault(); return; }
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });

  async function start() {
    const [settings, location] = await Promise.all([
      request('/api/desktop/workspace-root', undefined, 'GET'),
      request('/api/desktop/onboarding/default-location', undefined, 'GET'),
    ]);
    state.workspace = settings.workspace_root || location.workspace_root;
    state.homePath = location.workspace_root.replace(/[/\\][^/\\]+$/, '');
    state.previousWorkspace = settings.workspace_root;
    if (reconfigure || !settings.workspace_root) {
      document.body.append(overlay);
      render();
      document.documentElement.classList.add('desktop-onboarding-active');
      document.documentElement.classList.remove('desktop-onboarding-pending');
      return false;
    }
    document.documentElement.classList.remove('desktop-onboarding-pending');
    return true;
  }

  window.researchOSOnboardingReady = start().catch(problem => {
    state.error = problem.message || String(problem);
    document.body.append(overlay);
    render();
    document.documentElement.classList.add('desktop-onboarding-active');
    document.documentElement.classList.remove('desktop-onboarding-pending');
    return false;
  });
} else {
  window.researchOSOnboardingReady = Promise.resolve(true);
}

let newProjectOverlay = null;

export async function openNewProjectWizard(programs = []) {
  if (!desktop) return false;
  if (newProjectOverlay?.isConnected) return true;
  const overlay = document.createElement('div');
  overlay.className = 'desktop-onboarding';
  newProjectOverlay = overlay;
  const state = {
    step: 'program',
    programs: programs.filter((item) => item?.id),
    programId: '',
    programTitle: '',
    repo: null,
    workspace: null,
    busy: false,
    error: '',
  };
  const steps = ['program', 'old', 'fresh'];

  function programChoice() {
    const title = state.programTitle.trim();
    return title ? { title } : (state.programId ? { id: state.programId } : null);
  }

  function button(action, label, variant = '') {
    const node = document.createElement('button');
    node.type = 'button';
    node.className = `desktop-onboarding__button ${variant}`.trim();
    node.dataset.action = action;
    node.textContent = label;
    node.disabled = state.busy;
    return node;
  }

  function render() {
    overlay.replaceChildren();
    const shell = document.createElement('div');
    shell.className = 'desktop-onboarding__shell';
    shell.setAttribute('role', 'dialog');
    shell.setAttribute('aria-modal', 'true');
    shell.setAttribute('aria-labelledby', 'new-project-title');
    const header = document.createElement('header');
    header.className = 'desktop-onboarding__header';
    const eyebrow = document.createElement('p');
    eyebrow.className = 'desktop-onboarding__eyebrow';
    eyebrow.textContent = 'ResearcherOS';
    const heading = document.createElement('h1');
    heading.id = 'new-project-title';
    heading.textContent = 'Новое дерево';
    const subtitle = document.createElement('p');
    subtitle.className = 'desktop-onboarding__subtitle';
    subtitle.textContent = 'Сначала программа, потом репозиторий с кодом. Дерево исследования соберём в чате.';
    const stepList = document.createElement('ol');
    stepList.className = 'desktop-onboarding__steps';
    stepList.setAttribute('aria-label', 'Шаги нового проекта');
    const active = steps.indexOf(state.step);
    ['Программа', 'Репозиторий', 'Вопросы'].forEach((label, index) => {
      const item = document.createElement('li');
      item.className = 'desktop-onboarding__step';
      if (index < active) item.classList.add('is-done');
      if (index === active) item.classList.add('is-active');
      const indexEl = document.createElement('span');
      indexEl.className = 'desktop-onboarding__step-index';
      indexEl.textContent = String(index + 1);
      item.append(indexEl, document.createTextNode(label));
      stepList.append(item);
    });
    header.append(eyebrow, heading, subtitle, stepList);

    const main = document.createElement('div');
    main.className = 'desktop-onboarding__body';
    const panelTitle = document.createElement('h2');
    panelTitle.className = 'desktop-onboarding__panel-title';
    const lead = document.createElement('p');
    lead.className = 'desktop-onboarding__lead';
    main.append(panelTitle, lead);

    if (state.step === 'program') {
      panelTitle.textContent = 'В какой программе будет этот проект?';
      lead.textContent = 'Выберите программу из списка или напишите название новой.';
      if (state.programs.length) {
        const existing = document.createElement('label');
        existing.className = 'desktop-onboarding__field';
        existing.append(document.createTextNode('Существующая программа'));
        const select = document.createElement('select');
        select.dataset.programId = '1';
        const empty = document.createElement('option');
        empty.value = '';
        empty.textContent = 'Выберите из списка';
        select.append(empty);
        for (const program of state.programs) {
          const option = document.createElement('option');
          option.value = program.id;
          option.textContent = program.title || program.id;
          if (program.id === state.programId) option.selected = true;
          select.append(option);
        }
        existing.append(select);
        main.append(existing);
      }
      const created = document.createElement('label');
      created.className = 'desktop-onboarding__field';
      created.append(document.createTextNode('Новая программа'));
      const input = document.createElement('input');
      input.type = 'text';
      input.maxLength = 80;
      input.placeholder = 'Название программы';
      input.dataset.programTitle = '1';
      input.value = state.programTitle;
      created.append(input);
      main.append(created, button('continue', 'Дальше', 'desktop-onboarding__button--primary'));
    } else if (state.step === 'old') {
      panelTitle.textContent = 'Есть ли репозиторий проекта, который вы или коллега подключали к ResearcherOS?';
      lead.textContent = 'Выберите Git-репозиторий, в котором уже есть ветка с материалами исследования.';
      const choices = document.createElement('div');
      choices.className = 'desktop-onboarding__choices';
      const yes = document.createElement('section');
      yes.className = 'desktop-onboarding__choice desktop-onboarding__choice--yes';
      const yesText = document.createElement('p');
      yesText.className = 'desktop-onboarding__choice-summary';
      const yesLead = document.createElement('strong');
      yesLead.textContent = 'ДА,';
      yesText.append(yesLead, document.createTextNode(' в репозитории уже есть ветка с материалами исследований.'));
      yes.append(yesText, button('choose-old', 'Указать репозиторий'));
      if (state.repo?.branch_exists) {
        const detail = document.createElement('p');
        detail.className = 'desktop-onboarding__detail';
        detail.textContent = `${state.repo.repo_path} · найдена ветка ${state.repo.branch}`;
        yes.append(detail, button('open-old', 'Открыть проект', 'desktop-onboarding__button--primary'));
      }
      const no = document.createElement('section');
      no.className = 'desktop-onboarding__choice desktop-onboarding__choice--no';
      const noText = document.createElement('p');
      noText.className = 'desktop-onboarding__choice-summary';
      const noLead = document.createElement('strong');
      noLead.textContent = 'НЕТ,';
      noText.append(noLead, document.createTextNode(' исследовательской ветки ещё нет. Подключу новый репозиторий.'));
      no.append(noText, button('fresh', 'Дальше →', 'desktop-onboarding__button--secondary'));
      choices.append(yes, no);
      main.append(choices);
    } else {
      panelTitle.textContent = 'Выберите репозиторий с кодом.';
      lead.textContent = 'В нём ещё нет материалов исследования. После выбора откроется чат, где вы опишете проблему, причину и проверку.';
      main.append(button('choose-fresh', 'Указать репозиторий'));
      if (state.repo && !state.repo.branch_exists) {
        const detail = document.createElement('p');
        detail.className = 'desktop-onboarding__detail';
        detail.textContent = state.repo.repo_path;
        main.append(detail, button('chat', 'Открыть чат', 'desktop-onboarding__button--primary'));
      }
    }

    const footer = document.createElement('footer');
    footer.className = 'desktop-onboarding__footer';
    footer.append(button(state.step === 'program' ? 'close' : 'back', state.step === 'program' ? 'Закрыть' : '← Назад', 'desktop-onboarding__button--back'));
    const error = document.createElement('p');
    error.className = 'desktop-onboarding__error';
    error.setAttribute('role', 'alert');
    error.textContent = state.error;
    footer.append(error);
    shell.append(header, main, footer);
    overlay.append(shell);
  }

  async function post(url, payload) {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Не удалось выполнить действие.');
    return data;
  }

  async function chooseRepo(expectExisting) {
    const path = await desktop.chooseDirectory('repository');
    if (!path) return;
    state.repo = null;
    const inspected = await post('/api/desktop/onboarding/git-project', { path });
    if (expectExisting && !inspected.branch_exists) {
      throw new Error('В этом репозитории нет ветки с материалами исследования.');
    }
    if (!expectExisting && inspected.branch_exists) {
      throw new Error('В этом репозитории уже есть ветка с материалами. Вернитесь на предыдущий шаг.');
    }
    state.repo = inspected;
  }

  function close() {
    overlay.remove();
    newProjectOverlay = null;
    document.documentElement.classList.remove('desktop-onboarding-active');
  }

  async function act(action) {
    state.error = '';
    if (action === 'close') {
      close();
      return;
    }
    if (action === 'back') {
      state.repo = null;
      state.step = state.step === 'fresh' ? 'old' : 'program';
      render();
      return;
    }
    if (action === 'fresh') {
      state.repo = null;
      state.step = 'fresh';
      render();
      return;
    }
    if (action === 'continue') {
      state.programTitle = overlay.querySelector('[data-program-title]')?.value.trim() || '';
      state.programId = overlay.querySelector('[data-program-id]')?.value || '';
      if (!programChoice()) {
        state.error = 'Выберите программу или напишите название новой.';
        render();
        return;
      }
      state.repo = null;
      state.step = 'old';
      render();
      return;
    }
    if (!state.workspace && action !== 'continue') {
      state.error = 'Не удалось прочитать папку исследований.';
      render();
      return;
    }
    if (action === 'chat') {
      state.busy = true;
      try {
        await runOnboardingInterview({
          overlay,
          repoPath: state.repo.repo_path,
          workspaceRoot: state.workspace,
          program: programChoice(),
          onBack: render,
        });
      } finally {
        state.busy = false;
      }
      return;
    }
    state.busy = true;
    render();
    let stay = true;
    try {
      if (action === 'choose-old') await chooseRepo(true);
      else if (action === 'choose-fresh') await chooseRepo(false);
      else if (action === 'open-old') {
        await post('/api/desktop/onboarding/connect', {
          repo_path: state.repo.repo_path,
          workspace_root: state.workspace,
          require_existing: true,
          ...(programChoice().title ? { program_title: programChoice().title } : { program_id: programChoice().id }),
        });
        window.location.replace('/');
        stay = false;
        return;
      }
    } catch (problem) {
      state.error = problem.message || String(problem);
    } finally {
      state.busy = false;
      if (stay && overlay.isConnected) render();
    }
  }

  overlay.addEventListener('click', (event) => {
    const action = event.target.closest('button[data-action]')?.dataset.action;
    if (action && !state.busy) void act(action);
  });

  render();
  document.body.append(overlay);
  document.documentElement.classList.add('desktop-onboarding-active');
  try {
    const response = await fetch('/api/desktop/workspace-root');
    const settings = await response.json().catch(() => ({}));
    if (!response.ok || !settings.workspace_root) throw new Error('Не удалось прочитать папку исследований.');
    state.workspace = settings.workspace_root;
  } catch (problem) {
    state.error = problem.message || String(problem);
    render();
  }
  return true;
}
