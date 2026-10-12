import { runOnboardingInterview } from './onboarding-interview.js';

const desktop = window.researchOSDesktop;

if (desktop) {
  const reconfigure = new URLSearchParams(window.location.search).get('onboarding') === '1';
  const overlay = document.createElement('div');
  overlay.className = 'desktop-onboarding';
  const state = { step: 'tree', tree: null, repo: null, workspace: null, busy: false, error: '' };

  const screens = {
    tree: {
      title: 'У вас уже есть папка с исследованиями (./tree) для ResearcherOS?',
      body: 'Выберите папку tree, в которой хранятся материалы проектов.',
      yesAction: 'choose-tree',
      yesLabel: 'Указать папку',
      nextAction: 'old',
      noLabel: 'Создать →',
    },
    old: {
      title: 'Есть ли репозиторий проекта, который вы или коллега подключали к ResearcherOS?',
      body: 'Выберите Git-репозиторий, в котором уже есть ветка с материалами исследования.',
      yesAction: 'choose-old',
      yesLabel: 'Указать репозиторий',
      nextAction: 'new',
      noLabel: 'Дальше →',
    },
    new: {
      title: 'Хотите подключить репозиторий с кодом?',
      body: 'Выберите Git-репозиторий. ResearcherOS создаст для материалов ветку koi-project и папку ~/Documents/tree.',
      yesAction: 'choose-new',
      yesLabel: 'Указать репозиторий',
      nextAction: 'no-repo',
      noLabel: 'Нет репозитория',
    },
    'no-repo': {
      title: 'Выберите папку с исследованиями или репозиторий.',
      body: 'Вернитесь и укажите папку tree либо Git-репозиторий с кодом.',
    },
  };

  const steps = ['tree', 'old', 'new'];

  function render() {
    const screen = screens[state.step];
    overlay.replaceChildren();
    const shell = document.createElement('div');
    shell.className = 'desktop-onboarding__shell';
    shell.setAttribute('role', 'dialog');
    shell.setAttribute('aria-modal', 'true');
    shell.setAttribute('aria-labelledby', 'desktop-onboarding-title');
    shell.setAttribute('aria-busy', state.busy ? 'true' : 'false');

    const header = document.createElement('header');
    header.className = 'desktop-onboarding__header';
    const eyebrow = document.createElement('p');
    eyebrow.className = 'desktop-onboarding__eyebrow';
    eyebrow.textContent = 'ResearcherOS';
    const heading = document.createElement('h1');
    heading.id = 'desktop-onboarding-title';
    heading.textContent = 'Настройка рабочей папки';
    const subtitle = document.createElement('p');
    subtitle.className = 'desktop-onboarding__subtitle';
    subtitle.textContent = 'Код остаётся в репозитории. Материалы исследования живут в отдельной папке.';
    const stepList = document.createElement('ol');
    stepList.className = 'desktop-onboarding__steps';
    stepList.setAttribute('aria-label', 'Шаги настройки');
    const active = state.step === 'no-repo' ? 2 : steps.indexOf(state.step);
    ['Папка tree', 'Готовый репозиторий', 'Новый репозиторий'].forEach((label, index) => {
      const item = document.createElement('li');
      item.className = 'desktop-onboarding__step';
      if (index < active) item.classList.add('is-done');
      if (index === active) item.classList.add('is-active');
      const indexEl = document.createElement('span');
      indexEl.className = 'desktop-onboarding__step-index';
      indexEl.textContent = String(index + 1);
      const name = document.createElement('span');
      name.textContent = label;
      item.append(indexEl, name);
      stepList.append(item);
    });
    header.append(eyebrow, heading, subtitle, stepList);

    const main = document.createElement('div');
    main.className = 'desktop-onboarding__body';
    const panelTitle = document.createElement('h2');
    panelTitle.className = 'desktop-onboarding__panel-title';
    panelTitle.textContent = screen.title;
    const lead = document.createElement('p');
    lead.className = 'desktop-onboarding__lead';
    lead.textContent = screen.body;
    main.append(panelTitle, lead);

    function actionButton(action, label, variant = '') {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `desktop-onboarding__button ${variant}`.trim();
      button.dataset.action = action;
      button.textContent = label;
      button.disabled = state.busy;
      return button;
    }

    if (screen.yesAction) {
      const choices = document.createElement('div');
      choices.className = 'desktop-onboarding__choices';
      const yes = document.createElement('section');
      yes.className = 'desktop-onboarding__choice desktop-onboarding__choice--yes';
      const yesText = document.createElement('p');
      yesText.className = 'desktop-onboarding__choice-summary';
      const yesLead = document.createElement('strong');
      yesLead.textContent = 'ДА,';
      yesText.append(yesLead, document.createTextNode(state.step === 'tree'
        ? ' у меня уже есть папка tree с материалами исследований.'
        : state.step === 'old'
          ? ' в репозитории уже есть ветка с материалами исследований.'
          : ' у меня есть репозиторий с кодом, который хочу подключить.'));
      yes.append(yesText, actionButton(screen.yesAction, screen.yesLabel));
      const selected = state.step === 'tree' ? state.tree : state.repo;
      if (selected) {
        const detail = document.createElement('p');
        detail.className = 'desktop-onboarding__detail';
        detail.setAttribute('role', 'status');
        detail.textContent = state.step === 'tree'
          ? `${selected.tree_root} · найдено проектов: ${selected.projects.length}`
          : `${selected.repo_path} · ${selected.branch_exists ? 'найдена ветка' : 'будет создана ветка'} ${selected.branch} · ${state.workspace}/tree`;
        yes.append(detail, actionButton(state.step === 'tree' ? 'finish-tree' : 'connect',
          state.step === 'tree' ? 'Открыть ResearcherOS' : 'Подключить и открыть',
          'desktop-onboarding__button--primary'));
      }
      const no = document.createElement('section');
      no.className = 'desktop-onboarding__choice desktop-onboarding__choice--no';
      const noText = document.createElement('p');
      noText.className = 'desktop-onboarding__choice-summary';
      const noLead = document.createElement('strong');
      noLead.textContent = 'НЕТ,';
      noText.append(noLead, document.createTextNode(state.step === 'tree'
        ? ' такой папки пока нет. Создам её из репозитория.'
        : state.step === 'old'
          ? ' исследовательской ветки ещё нет. Подключу новый репозиторий.'
          : ' сейчас нет репозитория, который можно подключить.'));
      no.append(noText, actionButton(screen.nextAction, screen.noLabel,
        'desktop-onboarding__button--secondary'));
      choices.append(yes, no);
      main.append(choices);
    }

    const footer = document.createElement('footer');
    footer.className = 'desktop-onboarding__footer';
    if (state.step !== 'tree') footer.append(actionButton('back', '← Назад', 'desktop-onboarding__button--back'));
    if (reconfigure && state.previousWorkspace) {
      footer.append(actionButton('keep-current', 'Оставить текущие настройки', 'desktop-onboarding__button--keep'));
    }
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

  async function saveWorkspace(path) {
    const response = await fetch('/api/desktop/workspace-root', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace_root: path }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Не удалось сохранить рабочую папку.');
    window.location.replace('/');
  }

  async function act(action) {
    state.error = '';
    if (action === 'connect' && state.step === 'new') {
      await runOnboardingInterview({
        overlay,
        repoPath: state.repo.repo_path,
        workspaceRoot: state.workspace,
        onBack: render,
      });
      return;
    }
    if (action === 'keep-current') {
      window.location.replace('/');
      return;
    }
    if (['old', 'new', 'no-repo'].includes(action)) {
      state.repo = null;
      state.step = action;
      render();
      return;
    }
    if (action === 'back') {
      state.repo = null;
      state.step = ({ old: 'tree', new: 'old', 'no-repo': 'new' })[state.step];
      render();
      return;
    }
    state.busy = true;
    render();
    try {
      if (action === 'choose-tree') {
        const path = await desktop.chooseDirectory('workspace');
        if (path) {
          state.tree = null;
          state.tree = await post('/api/desktop/onboarding/existing-tree', { path });
        }
      } else if (action === 'choose-old' || action === 'choose-new') {
        const path = await desktop.chooseDirectory('repository');
        if (path) {
          state.repo = null;
          const inspected = await post('/api/desktop/onboarding/git-project', { path });
          if (action === 'choose-old' && !inspected.branch_exists) {
            throw new Error('В этом репозитории нет ветки с материалами исследования.');
          }
          if (action === 'choose-new' && inspected.branch_exists) {
            throw new Error('В этом репозитории уже есть ветка с материалами. Вернитесь на предыдущий шаг.');
          }
          state.repo = inspected;
        }
      } else if (action === 'finish-tree') {
        await saveWorkspace(state.tree.workspace_root);
      } else if (action === 'connect') {
        await post('/api/desktop/onboarding/connect', {
          repo_path: state.repo.repo_path,
          workspace_root: state.workspace,
          require_existing: state.step === 'old',
        });
        window.location.replace('/');
      }
    } catch (problem) {
      state.error = problem.message || String(problem);
    } finally {
      state.busy = false;
      render();
    }
  }

  overlay.addEventListener('click', (event) => {
    const action = event.target.closest('button[data-action]')?.dataset.action;
    if (action && !state.busy) void act(action);
  });

  async function start() {
    const [response, defaultResponse] = await Promise.all([
      fetch('/api/desktop/workspace-root'),
      fetch('/api/desktop/onboarding/default-location'),
    ]);
    if (!response.ok) throw new Error('Не удалось прочитать настройки рабочей папки.');
    if (!defaultResponse.ok) throw new Error('Не удалось определить папку Documents.');
    const settings = await response.json();
    const location = await defaultResponse.json();
    state.workspace = location.workspace_root;
    state.previousWorkspace = settings.workspace_root;
    if (reconfigure || !settings.workspace_root) {
      render();
      document.body.append(overlay);
      document.documentElement.classList.add('desktop-onboarding-active');
      document.documentElement.classList.remove('desktop-onboarding-pending');
      return false;
    }
    document.documentElement.classList.remove('desktop-onboarding-pending');
    return true;
  }

  window.researchOSOnboardingReady = start().catch((problem) => {
    state.error = problem.message || String(problem);
    render();
    document.body.append(overlay);
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
    heading.textContent = 'Новый проект';
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
