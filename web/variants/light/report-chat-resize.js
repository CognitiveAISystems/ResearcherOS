export function attachReportChatResize(panel) {
  const workspace = panel.closest('.report-workspace');
  const handle = panel.querySelector('.report-chat-resize');
  let drag;
  const width = () => panel.getBoundingClientRect().width;
  const setWidth = value => {
    const maximum = Math.max(280, Math.min(680, workspace.clientWidth * 0.5));
    const next = Math.round(Math.max(280, Math.min(maximum, value)));
    workspace.style.setProperty('--report-chat-width', `${next}px`);
    handle.setAttribute('aria-valuenow', next);
    handle.setAttribute('aria-valuemax', Math.round(maximum));
  };
  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0) return;
    event.preventDefault();
    drag = {x: event.clientX, width: width()};
    handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener('pointermove', event => {
    if (drag) setWidth(drag.width + drag.x - event.clientX);
  });
  handle.addEventListener('lostpointercapture', () => { drag = null; });
  handle.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    setWidth(event.key === 'Home' ? 280 : event.key === 'End' ? 680 : width() + (event.key === 'ArrowLeft' ? 24 : -24));
  });
  new ResizeObserver(() => {
    if (panel.getClientRects().length) handle.setAttribute('aria-valuenow', Math.round(width()));
  }).observe(panel);
}
