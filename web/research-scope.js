export function isResearchStart(text) {
  return /^\/koi-arbor-autoresearch(?:\s|$)/.test(text.trim()) &&
    !/^\/koi-arbor-autoresearch\s+(?:resume|продолжи)(?:\s|$)/.test(text.trim());
}

/** Confirm before enqueueing; native dialog makes the background inert. */
export function confirmResearchScope({methodTitle, projectTitle}) {
  const previousFocus = document.activeElement;
  const dialog = document.createElement('dialog');
  dialog.className = 'tag-settings-dialog';
  dialog.setAttribute('aria-labelledby', 'research-scope-title');
  dialog.setAttribute('aria-describedby', 'research-scope-description');
  const heading = document.createElement('h2');
  heading.id = 'research-scope-title';
  heading.textContent = 'Масштаб автоисследования';
  const description = document.createElement('p');
  description.id = 'research-scope-description';
  description.textContent = methodTitle
    ? `Исследовать улучшения метода «${methodTitle}» или перейти к поиску идей и гипотез на уровне дерева?`
    : `Начать поиск идей, гипотез и методов на уровне дерева «${projectTitle}»?`;
  const actions = document.createElement('div');
  actions.className = 'form-actions tag-delete-actions';
  dialog.append(heading, description, actions);
  document.body.append(dialog);
  return new Promise(resolve => {
    function finish(scope) {
      dialog.close();
      dialog.remove();
      previousFocus?.focus();
      resolve(scope);
    }
    const choices = methodTitle
      ? [[null, 'Отмена'], ['tree', 'На уровне дерева'], ['method', 'В рамках метода']]
      : [[null, 'Отмена'], ['tree', 'Начать исследование']];
    for (const [scope, label] of choices) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = scope === (methodTitle ? 'method' : 'tree') ? 'btn btn-primary' : 'btn';
      button.style.minHeight = '44px';
      button.textContent = label;
      button.onclick = () => finish(scope);
      actions.append(button);
    }
    dialog.onkeydown = event => {
      if (event.key !== 'Tab') return;
      const buttons = [...actions.children];
      const edge = event.shiftKey ? buttons[0] : buttons.at(-1);
      if (document.activeElement === edge) {
        event.preventDefault();
        (event.shiftKey ? buttons.at(-1) : buttons[0]).focus();
      }
    };
    dialog.oncancel = event => { event.preventDefault(); finish(null); };
    dialog.showModal();
  });
}
