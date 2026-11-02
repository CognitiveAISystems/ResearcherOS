import { activitySvg, renderExistingTree, runOnboardingInterview } from './onboarding-interview.js';

const desktop = window.researchOSDesktop;

let newProjectOverlay = null;

async function openOnboarding({ newTree = false } = {}) {
  const reconfigure = new URLSearchParams(window.location.search).get('onboarding') === '1';
  const previousFocus = document.activeElement;
  const overlay = document.createElement('div');
  overlay.className = 'desktop-onboarding';
  const state = { step: newTree ? 'repository' : 'welcome', repo: null, repositoryPath: '', treePath: '', workspace: null, locations: [], busy: false, error: '' };
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
      const trees = [...state.repo.trees, ...(state.repo.local_tree ? [state.repo.local_tree] : [])];
      if (trees.length > 1) {
        const label = element('label', 'desktop-onboarding__field', 'Выберите дерево для продолжения.');
        const select = document.createElement('select');
        trees.forEach(tree => {
          const option = element('option', '', `${tree.title} · ${tree.branch || 'Локальное дерево'}`);
          option.value = tree.branch || 'local';
          select.append(option);
        });
        select.value = state.selectedBranch;
        select.disabled = state.busy;
        select.addEventListener('change', () => { state.selectedBranch = select.value; render(); });
        label.append(select);
        main.append(label);
      }
      const tree = trees.find(item => (item.branch || 'local') === state.selectedBranch);
      if (tree) {
        const preview = element('section', 'desktop-onboarding__tree-preview');
        preview.append(element('h2', 'desktop-onboarding__panel-title', tree.title));
        disposeTreePreview = renderExistingTree(preview, tree.nodes, tree.branch);
        main.append(preview);
        actions.append(button('continue-tree', 'Продолжить в этом дереве', primary));
      } else {
        main.append(element('p', 'desktop-onboarding__lead', 'В папке исследований уже есть материалы этого проекта. Новое дерево будет создано отдельно.'));
      }
      actions.append(button('new-tree', 'Создать новое дерево', tree ? '' : primary));
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
    if (newTree || (reconfigure && state.previousWorkspace)) {
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

  function close() {
    disposeTreePreview();
    overlay.remove();
    newProjectOverlay = null;
    document.documentElement.classList.remove('desktop-onboarding-active');
    previousFocus?.focus();
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
      branch, onBack: render, onboarding: !newTree,
    });
  }

  async function act(action) {
    state.error = '';
    if (action === 'new-tree') { await interview(state.repo.next_branch); return; }
    if (action === 'keep-current') {
      if (newTree) close();
      else window.location.replace('/');
      return;
    }
    if (newTree && action === 'back' && state.step === 'repository') { close(); return; }
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
          state.repo = await request('/api/desktop/onboarding/git-project', { path, workspace_root: state.workspace });
          if (state.repo.branch_exists || state.repo.tree_folder_occupied) {
            state.selectedBranch = state.repo.branch_exists ? state.repo.branch : 'local';
            state.step = 'existing';
          } else createTree = true;
        }
      } else if (action === 'continue-tree') {
        if (state.selectedBranch === 'local' && state.repo.local_tree) {
          await request('/api/desktop/workspace-root', { workspace_root: state.repo.local_tree.workspace_root }, 'PUT');
          window.location.replace(`/?project=${encodeURIComponent(state.repo.local_tree.project_id)}`);
          return;
        }
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
    if (event.key === 'Escape' && !state.busy && (newTree || state.step !== 'welcome')) {
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
    if (newTree || reconfigure || !settings.workspace_root) {
      document.body.append(overlay);
      render();
      document.documentElement.classList.add('desktop-onboarding-active');
      document.documentElement.classList.remove('desktop-onboarding-pending');
      return false;
    }
    document.documentElement.classList.remove('desktop-onboarding-pending');
    return true;
  }

  if (newTree) newProjectOverlay = overlay;
  return start().catch(problem => {
    state.error = problem.message || String(problem);
    document.body.append(overlay);
    render();
    document.documentElement.classList.add('desktop-onboarding-active');
    document.documentElement.classList.remove('desktop-onboarding-pending');
    return false;
  });
}

window.researchOSOnboardingReady = desktop ? openOnboarding() : Promise.resolve(true);

export async function openNewProjectWizard() {
  if (!desktop) return false;
  if (!newProjectOverlay) await openOnboarding({ newTree: true });
  return true;
}

export async function openLocalTreeInterview({ title, description, tag, programId, programTitle, onBack }) {
  const overlay = document.createElement('div');
  overlay.className = 'desktop-onboarding';
  document.body.append(overlay);
  await runOnboardingInterview({
    overlay,
    localProject: { title, description, tag },
    program: programId ? { id: programId } : (programTitle ? { title: programTitle } : null),
    onBack: () => { overlay.remove(); onBack(); },
  });
}
