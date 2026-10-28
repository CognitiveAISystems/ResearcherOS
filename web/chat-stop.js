/* The classic layout has per-project/card turns instead of conversation controls. */
export function syncChatStop(button, item, {cancel, refresh, error, sending = false}) {
  if (!button) return;
  if (!button.stopState) {
    button.stopState = {icon: button.innerHTML, label: button.getAttribute('aria-label')};
    button.addEventListener('click', async event => {
      const state = button.stopState;
      if (!state.item) return;
      event.preventDefault(); event.stopImmediatePropagation();
      if (button.disabled) return;
      const id = state.item.id;
      button.disabled = true;
      button.setAttribute('aria-label', 'Останавливаем…');
      try {
        await state.cancel(id);
        await state.refresh();
      } catch (err) {
        if (button.stopState.item?.id === id) {
          button.disabled = false;
          button.setAttribute('aria-label', 'Остановить');
          state.error(err.message);
        }
      }
    });
  }
  const state = button.stopState;
  Object.assign(state, {item, cancel, refresh, error});
  const stopping = item?.live?.cancelled;
  const label = item ? (stopping ? 'Останавливаем…' : 'Остановить') : state.label;
  button.type = item ? 'button' : 'submit';
  button.disabled = Boolean(stopping || (!item && sending));
  button.setAttribute('aria-label', label); button.title = label;
  const action = item ? 'stop' : 'send';
  if (button.dataset.action !== action) {
    button.dataset.action = action;
    button.innerHTML = item
      ? '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="1" fill="currentColor" stroke="none"/></svg>'
      : state.icon;
  }
}
