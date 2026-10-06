(() => {
  'use strict';
  const dialog = document.createElement('dialog');
  dialog.className = 'image-viewer';
  dialog.setAttribute('aria-label', 'Просмотр изображения');
  dialog.innerHTML = '<button class="image-viewer__close" type="button" aria-label="Закрыть">×</button><figure><img alt=""><figcaption></figcaption></figure>';
  document.body.append(dialog);
  const full = dialog.querySelector('img');
  const caption = dialog.querySelector('figcaption');
  const close = dialog.querySelector('button');
  let trigger;
  let previousOverflow;
  function open(button) {
    const img = button.querySelector('img');
    if (!img || dialog.open) return;
    trigger = button;
    full.src = img.currentSrc || img.src;
    full.alt = img.alt;
    const label = img.closest('figure')?.querySelector('figcaption');
    caption.textContent = label?.textContent || img.alt;
    previousOverflow = document.body.style.overflow;
    dialog.showModal();
    document.body.style.overflow = 'hidden';
    close.focus();
  }
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener('close', () => {
    document.body.style.overflow = previousOverflow;
    full.removeAttribute('src');
    if (trigger?.isConnected) trigger.focus({preventScroll: true});
  });
  function enhance() {
    document.querySelectorAll('main img, article img, .features-md img').forEach(img => {
      if (img.closest('a, button, dialog, .brand, .partners') || img.classList.contains('brand__logo') || img.classList.contains('hero__logo')) return;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'image-zoom';
      button.setAttribute('aria-haspopup', 'dialog');
      button.setAttribute('aria-label', img.alt ? 'Увеличить: ' + img.alt : 'Увеличить изображение');
      img.replaceWith(button);
      button.append(img);
      button.addEventListener('click', () => open(button));
    });
  }
  enhance();
  // Feature articles insert images after fetching their Markdown.
  new MutationObserver(enhance).observe(document.body, {childList: true, subtree: true});
})();
