/* Build the screen search exclusively from authorized navigation. */
'use strict';
(() => {
  const nav = document.querySelector('.module-navigation');
  const dialog = document.getElementById('screen-search');
  const opener = document.getElementById('screen-search-open');
  if (!nav || !dialog || !opener || typeof dialog.showModal !== 'function') return;

  const input = dialog.querySelector('input');
  const list = dialog.querySelector('ul');
  const status = dialog.querySelector('[role="status"]');
  const countFormat = new Intl.NumberFormat(document.documentElement.lang === 'fa' ? 'fa-IR' : 'en-US');
  const normalize = value => value.normalize('NFKD').toLocaleLowerCase()
    .replace(/\p{M}|[\u0640]/gu, '')
    .replace(/[يى]/g, 'ی').replace(/ك/g, 'ک')
    .replace(/[\u200c\u200d]/g, ' ')
    .replace(/\s+/g, ' ').trim();
  const entries = Array.from(nav.querySelectorAll('button[data-view], button[data-module-view]'))
    .map(source => {
      const label = source.cloneNode(true);
      label.querySelectorAll('b').forEach(count => count.remove());
      const title = label.textContent.trim();
      const group = source.closest('.nav-module')?.querySelector('summary')?.textContent.trim() || '';
      const family = source.closest('[data-report-family]')?.querySelector('summary')?.textContent.trim() || '';
      return { source, title, group: [group, family].filter(Boolean).join(' · '),
        terms: normalize([title, group, family, source.dataset.view, source.dataset.moduleTarget]
          .filter(Boolean).join(' ').replace(/-/g, ' ')) };
    });

  function render() {
    const query = normalize(input.value).split(' ').filter(Boolean);
    const matches = entries.filter(entry => query.every(term => entry.terms.includes(term)));
    const fragment = document.createDocumentFragment();
    for (const entry of matches) {
      const li = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      const title = document.createElement('strong');
      const group = document.createElement('small');
      title.textContent = entry.title;
      group.textContent = entry.group;
      button.append(title, group);
      button.addEventListener('click', () => {
        dialog.close();
        entry.source.click();
        if (!entry.source.dataset.moduleTarget) {
          const view = document.getElementById(entry.source.dataset.view + '-view');
          const heading = view?.querySelector('h1, h2') || view;
          if (heading) {
            heading.tabIndex = -1;
            heading.focus({preventScroll: true});
          }
        }
      });
      li.append(button);
      fragment.append(li);
    }
    list.replaceChildren(fragment);
    status.textContent = matches.length ? status.dataset.count.replace('{count}', countFormat.format(matches.length))
      : status.dataset.empty;
  }
  function open() {
    if (dialog.open) return;
    input.value = '';
    render();
    dialog.showModal();
    input.focus();
  }
  opener.hidden = false;
  opener.addEventListener('click', open);
  input.addEventListener('input', render);
  dialog.addEventListener('keydown', event => {
    if (event.key === 'Escape') {
      event.preventDefault();
      dialog.close();
      return;
    }
    const choices = Array.from(list.querySelectorAll('button'));
    if (!choices.length || (event.target !== input && !choices.includes(event.target))) return;
    const current = choices.indexOf(event.target);
    if (event.key === 'Enter' && event.target === input) {
      event.preventDefault();
      choices[0].click();
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (event.key === 'ArrowUp' && current === 0) input.focus();
      else choices[event.key === 'ArrowDown' ? Math.min(current + 1, choices.length - 1)
        : current < 0 ? choices.length - 1 : current - 1].focus();
    }
  });
  document.addEventListener('keydown', event => {
    if (event.key.toLowerCase() !== 'k' || !(event.ctrlKey || event.metaKey) || event.altKey
      || document.querySelector('dialog[open]')) return;
    event.preventDefault();
    open();
  });
})();
