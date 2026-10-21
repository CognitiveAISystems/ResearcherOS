export const CARD_SKILLS = [
  {command: 'grill-me', name: 'grill-me', description: 'Уточнить цель, метрики и план эксперимента.'},
  {command: 'prose', name: 'prose', description: 'Проверить и улучшить текст карточки и отчёта.'},
  {command: 'question', name: 'question', description: 'Ответить по материалам карточки без изменений.'},
  {command: 'run', name: 'run', description: 'Выполнить карточку: план, проверки, отчёт и итоговый статус.'},
];

export function reportChatCommand(text) {
  const match = text.match(/^\/(grill-me|grill_me|prose|question|run|make_report)(?:\s+|$)([\s\S]*)$/i);
  if (!match) return {purpose: 'agent', question: text};
  const name = match[1].toLowerCase();
  const purpose = name === 'grill-me' ? 'grill_me' : name;
  const defaults = {grill_me: 'Пройди постановку этой задачи.', prose: 'Проверь и улучши текст карточки и отчёта.', question: 'Ответь на вопрос по этой карточке.', run: 'Выполни эту карточку по системному процессу.', make_report: 'Собери отчёт по этой задаче.'};
  return {purpose, question: match[2].trim() || defaults[purpose]};
}

/** Slash menu shared by the project chat and the report chat. */
export function attachSkillMenu(input, { getProjectId }) {
  const hint = 'Введите /, чтобы посмотреть доступные скиллы для ИИ';
  input.placeholder = hint;
  input.title = hint;
  input.setAttribute('aria-autocomplete', 'list');
  input.setAttribute('aria-haspopup', 'listbox');
  const popup = document.createElement('div');
  popup.className = 'chat-skills';
  popup.setAttribute('popover', 'manual');
  const title = document.createElement('p');
  title.className = 'chat-skills-title';
  title.textContent = 'Скиллы';
  const list = document.createElement('div');
  list.id = `${input.id}-skills`;
  list.setAttribute('role', 'listbox');
  list.setAttribute('aria-label', 'Доступные скиллы');
  popup.append(title, list);
  document.body.append(popup);
  input.setAttribute('aria-controls', list.id);
  let filtered = [], active = 0, project = null;
  const query = () => input.value.slice(0, input.selectionStart).match(/^\/([^\s/]*)$/)?.[1];
  const open = () => popup.matches(':popover-open');
  function close() {
    if (open()) popup.hidePopover();
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  }
  function position() {
    if (!open()) return;
    const rect = input.closest('.agent-chat-composer').getBoundingClientRect();
    popup.style.width = `${Math.min(rect.width, window.innerWidth - 24)}px`;
    popup.style.left = `${Math.max(12, Math.min(rect.left, window.innerWidth - popup.offsetWidth - 12))}px`;
    const above = rect.top - popup.offsetHeight - 8;
    popup.style.top = `${Math.max(12, above >= 12 ? above : Math.min(rect.bottom + 8, window.innerHeight - popup.offsetHeight - 12))}px`;
  }
  function select(index) {
    const skill = filtered[index];
    if (!skill || query() === undefined || project !== getProjectId()) return;
    input.setRangeText(`/${skill.command} `, 0, input.selectionStart, 'end');
    close();
    input.focus();
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }
  function highlight() {
    [...list.children].forEach((row, i) => row.setAttribute('aria-selected', String(i === active)));
    const row = list.children[active];
    if (row) { input.setAttribute('aria-activedescendant', row.id); row.scrollIntoView({ block: 'nearest' }); }
  }
  function render(message) {
    list.replaceChildren();
    input.removeAttribute('aria-activedescendant');
    filtered.forEach((skill, index) => {
      const row = document.createElement('button');
      row.type = 'button';
      row.id = `${list.id}-${index}`;
      row.setAttribute('role', 'option');
      row.tabIndex = -1;
      const name = document.createElement('strong');
      name.textContent = skill.name;
      const description = document.createElement('span');
      description.textContent = skill.description;
      row.append(name, description);
      row.addEventListener('pointerdown', e => e.preventDefault());
      row.addEventListener('click', () => select(index));
      list.append(row);
    });
    if (!filtered.length) {
      const empty = document.createElement('p');
      empty.className = 'chat-skills-empty';
      empty.textContent = message || 'Скиллы не найдены';
      list.append(empty);
    }
    if (!open()) popup.showPopover();
    input.setAttribute('aria-expanded', 'true');
    position();
    if (filtered.length) highlight();
  }
  function refresh() {
    const term = query();
    if (term === undefined || document.activeElement !== input) { close(); return; }
    project = getProjectId();
    active = 0;
    if (!project) { filtered = []; render('Сначала откройте карточку'); return; }
    filtered = CARD_SKILLS.filter(row => `${row.name} ${row.description}`.toLocaleLowerCase().includes(term.toLocaleLowerCase()));
    render();
  }
  input.addEventListener('input', refresh);
  input.addEventListener('click', refresh);
  input.addEventListener('focus', () => { project = null; void refresh(); });
  input.addEventListener('blur', close);
  input.form?.addEventListener('submit', close);
  input.addEventListener('keydown', e => {
    if (!open() || e.isComposing) return;
    if (!['ArrowDown', 'ArrowUp', 'Enter', 'Tab', 'Escape'].includes(e.key)) return;
    if (e.key === 'Tab') { close(); return; }
    e.preventDefault(); e.stopImmediatePropagation();
    if (e.key === 'Escape') { close(); return; }
    if (e.key === 'Enter') { select(active); return; }
    if (filtered.length) { active = (active + (e.key === 'ArrowDown' ? 1 : -1) + filtered.length) % filtered.length; highlight(); }
  }, true);
  window.addEventListener('resize', position);
  document.addEventListener('scroll', position, true);
}
