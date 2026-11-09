/* Search and add extensions observed in the authorized date range. */
(() => {
  'use strict';
  const dates = document.getElementById('history-filters');
  if (!dates) return;
  const fa = document.documentElement.lang === 'fa';
  const t = (a, b) => fa ? a : b;
  const digits = value => value.replace(/[۰-۹]/g, x => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(x)))
    .replace(/[٠-٩]/g, x => String('٠١٢٣٤٥٦٧٨٩'.indexOf(x)));
  const create = (tag, text) => {
    const element = document.createElement(tag);
    if (text) element.textContent = text;
    return element;
  };

  for (const id of ['history-cdr-filters', 'pbx-performance-filters', 'pbx-reason-filters']) {
    const form = document.getElementById(id);
    const input = form?.elements.endpoint;
    if (!input) continue;

    const details = create('details');
    details.className = 'pbx-endpoint-picker';
    const summary = create('summary');
    const menu = create('div');
    menu.className = 'pbx-endpoint-menu';
    const searchLabel = create('label', t('جست‌وجوی داخلی در فهرست', 'Find an extension in the list'));
    const search = create('input');
    search.type = 'search';
    search.inputMode = 'numeric';
    search.placeholder = '100';
    searchLabel.append(search);
    const list = create('select');
    list.size = 6;
    list.setAttribute('aria-label', t('داخلی‌های مشاهده‌شده', 'Observed extensions'));
    const add = create('button', t('افزودن داخلی', 'Add extension'));
    add.type = 'button';
    const status = create('p');
    status.setAttribute('role', 'status');
    menu.append(searchLabel, list, add, status);
    details.append(summary, menu);
    input.parentElement.insertAdjacentElement('afterend', details);
    input.placeholder = '100, 200';
    input.removeAttribute('inputmode');

    const selected = () => new Set(input.value.split(',').map(value => digits(value.trim())).filter(Boolean));
    let serial = 0;
    let endpoints = [];

    function updateSummary() {
      const count = selected().size;
      summary.textContent = t('انتخاب داخلی از فهرست', 'Choose extensions') +
        (count ? ' · ' + count.toLocaleString(fa ? 'fa-IR' : 'en-GB') + ' ' + t('انتخاب', 'selected') : '');
    }
    function render() {
      const query = digits(search.value.trim()).toLowerCase();
      const current = selected();
      const options = endpoints.filter(endpoint => endpoint.toLowerCase().includes(query)).map(endpoint => {
        const [technology, number] = endpoint.split('/');
        const option = new Option(number + ' · ' + technology, endpoint);
        option.disabled = current.has(endpoint) || current.has(number);
        return option;
      });
      list.replaceChildren(...options);
      list.selectedIndex = options.findIndex(option => !option.disabled);
      add.disabled = list.selectedIndex < 0;
      status.textContent = options.length ? '' : t('داخلی مطابق جست‌وجو پیدا نشد.', 'No matching extensions.');
      updateSummary();
    }
    async function load() {
      const generation = ++serial;
      if (!dates.reportValidity()) return;
      endpoints = [];
      list.replaceChildren();
      add.disabled = true;
      status.textContent = t('در حال دریافت داخلی‌ها…', 'Loading extensions…');
      try {
        const query = new URLSearchParams({from: dates.elements.from.value, to: dates.elements.to.value});
        const response = await fetch('/api/history/cdr/summary?' + query, {credentials: 'same-origin'});
        if (!response.ok || response.redirected || !response.headers.get('content-type')?.includes('application/json')) throw Error();
        const data = await response.json();
        if (generation !== serial || !details.open) return;
        if (!data.can_search_numbers) {
          status.textContent = t('مجوز مشاهدهٔ داخلی‌ها لازم است.', 'Permission to view extensions is required.');
          return;
        }
        endpoints = [...new Set(data.endpoints.map(item => item.endpoint)
          .filter(value => typeof value === 'string' && /^(SIP|PJSIP)\/[A-Za-z0-9_.-]{1,48}$/.test(value)))]
          .sort((a, b) => a.split('/')[1].localeCompare(b.split('/')[1], undefined, {numeric:true}) || a.localeCompare(b));
        render();
      } catch {
        if (generation === serial) status.textContent = t('فهرست داخلی‌ها در دسترس نیست.', 'Extension list unavailable.');
      }
    }
    search.addEventListener('input', event => {
      event.stopPropagation();
      render();
    });
    search.addEventListener('change', event => event.stopPropagation());
    search.addEventListener('keydown', event => {
      if (event.key === 'Enter') {
        event.preventDefault();
        add.click();
      }
    });
    list.addEventListener('input', event => event.stopPropagation());
    list.addEventListener('change', event => event.stopPropagation());
    add.addEventListener('click', () => {
      const current = selected();
      if (!list.value) return;
      if (current.size >= 20) {
        status.textContent = t('حداکثر ۲۰ داخلی انتخاب کنید.', 'Select at most 20 extensions.');
        return;
      }
      current.add(list.value);
      input.value = [...current].join(', ');
      input.dispatchEvent(new Event('input', {bubbles:true}));
      render();
      search.focus();
    });
    details.addEventListener('keydown', event => {
      if (event.key === 'Escape' && details.open) {
        event.preventDefault();
        details.open = false;
        summary.focus();
      }
    });
    details.addEventListener('toggle', () => {
      if (details.open) {
        search.value = '';
        load();
      } else serial++;
    });
    input.addEventListener('input', updateSummary);
    for (const event of ['input', 'change']) dates.addEventListener(event, () => { details.open = false; serial++; });
    form.addEventListener('reset', () => {
      details.open = false;
      serial++;
      setTimeout(updateSummary, 0);
    });
    updateSummary();
  }
})();
