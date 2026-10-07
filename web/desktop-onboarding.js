const desktop = window.researchOSDesktop;

if (desktop) {
  const overlay = document.createElement('div');
  overlay.className = 'desktop-onboarding';
  overlay.innerHTML = `
    <div class="desktop-onboarding__card" role="dialog" aria-modal="true" aria-labelledby="desktop-onboarding-title">
      <span class="desktop-onboarding__eyebrow">ResearcherOS для macOS</span>
      <h1 id="desktop-onboarding-title">Где находятся ваши проекты?</h1>
      <p>Выберите рабочую папку. В ней ResearcherOS найдёт исследования и сможет создавать новые.</p>
      <button type="button" class="desktop-onboarding__button">Выбрать папку</button>
      <p class="desktop-onboarding__error" role="alert"></p>
    </div>`;
  const button = overlay.querySelector('button');
  const error = overlay.querySelector('[role="alert"]');

  async function loadCurrentRoot() {
    const response = await fetch('/api/desktop/workspace-root');
    if (!response.ok) throw new Error('Не удалось прочитать настройки рабочей папки.');
    const settings = await response.json();
    if (!settings.workspace_root) document.body.append(overlay);
  }

  button.addEventListener('click', async () => {
    error.textContent = '';
    button.disabled = true;
    try {
      const chosen = await desktop.chooseWorkspace();
      if (!chosen) return;
      const response = await fetch('/api/desktop/workspace-root', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspace_root: chosen }),
      });
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail || 'Не удалось сохранить папку.');
      }
      window.location.reload();
    } catch (problem) {
      error.textContent = problem.message || String(problem);
    } finally {
      button.disabled = false;
    }
  });

  loadCurrentRoot().catch((problem) => {
    document.body.append(overlay);
    error.textContent = problem.message || String(problem);
  });
}
