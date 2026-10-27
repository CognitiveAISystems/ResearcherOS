export function attachReportChatResize(panel) {
  const workspace = panel.closest('.report-workspace');
  const handle = panel.querySelector('.report-chat-resize');
  let drag;
  const width = () => panel.getBoundingClientRect().width;
  const setWidth = value => {
    const maximum = Math.max(280, Math.min(800, workspace.clientWidth * 0.6));
    const next = Math.round(Math.max(280, Math.min(maximum, value)));
    workspace.style.setProperty('--report-chat-width', `${next}px`);
    handle.setAttribute('aria-valuenow', next);
    handle.setAttribute('aria-valuemax', Math.round(maximum));
  };
  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    event.preventDefault();
    drag = {x: event.clientX, width: width(), direction: getComputedStyle(workspace).direction === "rtl" ? -1 : 1};
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener('pointermove', event => {
    if (drag) setWidth(drag.width + (event.clientX - drag.x) * drag.direction);
  });
  handle.addEventListener('lostpointercapture', () => { drag = null; });
  handle.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const direction = getComputedStyle(workspace).direction === 'rtl' ? -1 : 1;
    setWidth(event.key === 'Home' ? 280 : event.key === 'End' ? 800 : width() + (event.key === 'ArrowRight' ? 24 : -24) * direction);
  });
  new ResizeObserver(() => {
    if (panel.getClientRects().length) handle.setAttribute('aria-valuenow', Math.round(width()));
  }).observe(panel);
}

export function attachMainChatResize(panel, api) {
  const workspace = panel.closest('.workspace');
  const handle = document.createElement('div');
  handle.className = 'main-chat-resize'; handle.tabIndex = 0;
  handle.setAttribute('role', 'separator'); handle.setAttribute('aria-orientation', 'vertical');
  handle.setAttribute('aria-label', 'Ширина панели чатов');
  handle.title = 'Потяните границу, чтобы изменить ширину. Двойной щелчок — стандартная ширина.'; handle.setAttribute('aria-controls', panel.id);
  panel.append(handle);
  const compact = workspace.classList.contains("compact-chat");
  const defaultWidth = compact ? 400 : 960;
  let preferred = defaultWidth, drag, edited = false;
  const minimum = () => Math.min(compact ? 340 : 640, workspace.clientWidth - 180);
  const maximum = () => Math.max(minimum(), Math.min(compact ? 720 : Infinity, workspace.clientWidth - 180));
  const width = () => panel.getBoundingClientRect().width;
  const render = () => {
    const next = Math.round(Math.max(minimum(), Math.min(maximum(), preferred)));
    panel.style.setProperty('--main-chat-width', `${next}px`);
    handle.setAttribute('aria-valuemin', Math.round(minimum()));
    handle.setAttribute('aria-valuemax', Math.round(maximum()));
    handle.setAttribute('aria-valuenow', Math.round(width()));
  };
  const save = () => {
    preferred = Math.round(width()); edited = true;
    api.saveAgentChatSettings({chat_panel_width: preferred}).catch(() => {});
  };
  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    event.preventDefault(); handle.focus();
    drag = {x: event.clientX, width: width(), direction: getComputedStyle(workspace).direction === 'rtl' ? 1 : -1};
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener('pointermove', event => {
    if (!drag) return;
    preferred = drag.width + (drag.x - event.clientX) * drag.direction; render();
  });
  handle.addEventListener('lostpointercapture', () => { if (drag) { drag = null; save(); } });
  handle.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const direction = getComputedStyle(workspace).direction === 'rtl' ? 1 : -1;
    preferred = event.key === 'Home' ? minimum() : event.key === 'End' ? maximum() : width() + (event.key === 'ArrowLeft' ? 24 : -24) * direction;
    render(); save();
  });
  handle.addEventListener('dblclick', () => { preferred = defaultWidth; render(); save(); });
  new ResizeObserver(render).observe(workspace);
  api.getSettings().then(settings => {
    if (!edited && !drag && Number.isFinite(settings.chat_panel_width)) { preferred = compact && settings.chat_panel_width === 960 ? defaultWidth : settings.chat_panel_width; render(); }
  }).catch(() => {});
  render();
}
