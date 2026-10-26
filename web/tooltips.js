// Shared application tooltips: consume title before the browser can show its own bubble.
const tip = document.createElement('div');
tip.id = 'researcheros-tooltip'; tip.className = 'app-tooltip';
tip.setAttribute('role', 'tooltip'); tip.setAttribute('popover', 'manual');
document.body.append(tip);
let anchor, timer, described;

function convert(element) {
  if (element.hasAttribute?.('title')) {
    const text = element.getAttribute('title').trim();
    if (text) {
      element.dataset.tooltip = text; delete element.dataset.tooltipFromAria;
      if (element.matches('button,a,[role="button"]') && !element.textContent.trim() &&
          !element.hasAttribute('aria-label') && !element.hasAttribute('aria-labelledby')) element.setAttribute('aria-label', text);
    } else delete element.dataset.tooltip;
    element.removeAttribute('title');
  }
  const label = element.getAttribute?.('aria-label');
  if (label && element.matches('button,a,[role="button"]') && !element.textContent.trim() &&
      (element.dataset.tooltipFromAria || !element.dataset.tooltip)) {
    element.dataset.tooltip = label; element.dataset.tooltipFromAria = 'true';
  }
  if (element.namespaceURI === 'http://www.w3.org/2000/svg' && element.localName === 'title') {
    const parent = element.parentElement;
    if (parent && element.textContent.trim()) {
      parent.dataset.tooltip = element.textContent.trim();
      if (!parent.hasAttribute("aria-label")) parent.setAttribute("aria-label", element.textContent.trim());
    }
    element.remove();
  }
}
function scan(root) {
  convert(root);
  root.querySelectorAll?.('[title],[aria-label],svg title').forEach(convert);
}
scan(document.documentElement);
new MutationObserver(records => {
  for (const record of records) {
    if (record.type === 'attributes') {
      convert(record.target);
      if (record.target === anchor && tip.matches(':popover-open')) tip.textContent = anchor.dataset.tooltip || '';
    } else for (const node of record.addedNodes) if (node.nodeType === 1) scan(node);
  }
  if (anchor && !anchor.isConnected) hide();
}).observe(document.documentElement, {subtree: true, childList: true, attributes: true, attributeFilter: ['title', 'aria-label']});

function hide() {
  clearTimeout(timer);
  if (tip.matches(':popover-open')) tip.hidePopover();
  if (anchor && described !== undefined) {
    if (described) anchor.setAttribute('aria-describedby', described);
    else anchor.removeAttribute('aria-describedby');
  }
  anchor = null; described = undefined;
}
function isIconButton(element) {
  if (!element?.matches('button,a,[role="button"]')) return false;
  const text = element.textContent.trim();
  const rect = element.getBoundingClientRect();
  return text.length <= 2 && rect.width <= 64 && rect.height <= 64;
}
function show(element) {
  if (!element?.isConnected || !element.dataset.tooltip || !isIconButton(element)) return;
  if (anchor !== element) hide();
  anchor = element;
  tip.textContent = element.dataset.tooltip;
  if (described === undefined) described = element.getAttribute('aria-describedby') || '';
  element.setAttribute('aria-describedby', [described, tip.id].filter(Boolean).join(' '));
  tip.showPopover();
  const rect = element.getBoundingClientRect();
  const size = tip.getBoundingClientRect();
  tip.style.left = `${Math.max(8, Math.min(innerWidth - size.width - 8, rect.left + (rect.width - size.width) / 2))}px`;
  tip.style.top = `${Math.max(8, rect.top >= size.height + 16 ? rect.top - size.height - 8 : Math.min(innerHeight - size.height - 8, rect.bottom + 8))}px`;
}
function schedule(element, delay = 300) {
  if (!element?.dataset.tooltip || !isIconButton(element)) return;
  if (anchor === element && tip.matches(':popover-open')) return;
  hide(); anchor = element;
  timer = setTimeout(() => show(element), delay);
}
document.addEventListener('pointerover', event => {
  if (event.pointerType === 'touch' || tip.contains(event.target)) return;
  const element = event.target.closest?.('[data-tooltip]');
  if (element && !element.contains(event.relatedTarget)) schedule(element);
});
document.addEventListener('pointerout', event => {
  if (!anchor) return;
  if (anchor.contains(event.relatedTarget) || tip.contains(event.relatedTarget)) return;
  if (anchor.contains(event.target) || tip.contains(event.target)) hide();
});
document.addEventListener('focusin', event => schedule(event.target.closest?.('[data-tooltip]'), 0));
document.addEventListener('focusout', event => { if (anchor?.contains(event.target)) hide(); });
document.addEventListener('pointerdown', hide);
document.addEventListener('dragstart', hide);
document.addEventListener('scroll', event => { if (!tip.contains(event.target)) hide(); }, true);
document.addEventListener('keydown', event => { if (event.key === 'Escape' && anchor) { hide(); event.preventDefault(); event.stopPropagation(); } }, true);
window.addEventListener('resize', hide);
