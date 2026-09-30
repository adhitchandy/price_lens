// Live run screen: progress, one line per storefront, the live log, cancel / force stop.
// Python refreshes `data` every 2 seconds; buttons send setTriggerValue('action', ...).

const FONT_HREF = 'https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap';
const INT = new Intl.NumberFormat('en-US');

function ensureFont() {
  if (!document.getElementById('pi-geist-font')) {
    const link = document.createElement('link');
    link.id = 'pi-geist-font';
    link.rel = 'stylesheet';
    link.href = FONT_HREF;
    document.head.appendChild(link);
  }
}

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'text') el.textContent = value;
    else if (key === 'style') Object.assign(el.style, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2).toLowerCase(), value);
    else el.setAttribute(key, value === true ? '' : String(value));
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function createApp(root) {
  const app = { data: {}, api: {}, open: true, sent: null };
  const header = h('div');
  const progress = h('section', { class: 'card card-pad progress', 'aria-label': 'Progress' });
  const detail = h('div', { class: 'detail' });
  root.append(header, progress, detail);

  const send = (action) => {
    if (!app.api.setTriggerValue) return;
    app.sent = action;
    app.api.setTriggerValue('action', action);
    renderHeader();
  };

  function renderHeader() {
    const d = app.data;
    const cancelling = d.state === 'cancelling';
    const stateChip = cancelling
      ? h('span', { class: 'chip' }, h('span', { class: 'dot warn' }), 'Stopping after the current step…')
      : h('span', { class: 'chip' }, h('span', { class: 'dot live' }), d.state === 'queued' ? 'Starting…' : 'Running in the background');
    const actions = [];
    if (!cancelling) {
      actions.push(h('button', { type: 'button', class: 'btn', disabled: app.sent === 'cancel', onclick: () => send('cancel'),
        title: 'Stops after the current step and keeps what is finished.' }, app.sent === 'cancel' ? 'Cancelling…' : 'Cancel after this step'));
    }
    if (d.can_force) {
      actions.push(h('button', { type: 'button', class: 'btn danger', disabled: app.sent === 'force', onclick: () => send('force'),
        title: 'Ends the browser and the background process now.' }, 'Force stop'));
    }
    actions.push(h('button', { type: 'button', class: 'btn', 'aria-expanded': String(app.open),
      onclick: () => { app.open = !app.open; render(); } }, app.open ? 'Hide details' : 'Show details'));
    header.replaceChildren(h('div', { class: 'hd' },
      h('div', { class: 'hd-text' },
        h('span', { class: 'eyebrow' }, 'Run / ', h('b', { text: d.run || '' })),
        h('h1', { class: 'title', text: d.label || 'Collecting listings' }),
        h('div', { class: 'chips' }, stateChip, h('span', { class: 'chip', text: 'Safe to close or refresh this tab' }))),
      h('div', { class: 'hd-actions' }, actions)));
  }

  function stat(label, value, sub, accent) {
    return h('div', { class: 'stat' }, h('span', { class: 'kpi-label', text: label }),
      h('span', { class: `v${accent ? ' accent' : ''}`, text: value }), h('span', { class: 'sub', text: sub || '' }));
  }

  function renderProgress() {
    const d = app.data;
    const stores = d.stores || [];
    const waiting = stores.filter((s) => s.status === 'Waiting for network').length;
    const pct = Math.max(0, Math.min(100, d.progress || 0));
    const search = d.search || {};
    progress.replaceChildren(
      h('div', { class: 'stats' },
        stat('Search', `${search.current || 1} / ${search.total || 1}`, search.term || ''),
        stat('Storefronts done', stores.length ? `${d.stores_done || 0} / ${stores.length}` : '—',
          waiting ? `${waiting} waiting for the connection` : 'finished or skipped'),
        stat('Listings so far', INT.format(d.listings || 0), 'saved after every storefront', true),
        stat('Time left', d.time_left || '—', d.started ? `started ${d.started}` : '')),
      h('div', {},
        h('div', { class: 'bar', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(pct),
                   'aria-label': 'Run progress' }, h('div', { style: { width: `${pct}%` } })),
        h('div', { class: 'bar-meta' }, h('span', { text: `${pct}% complete` }),
          h('span', { text: 'estimate only — pages, bot checks and the network vary' }))));
  }

  function renderDetail() {
    const d = app.data;
    if (!app.open) { detail.replaceChildren(); detail.style.display = 'none'; return; }
    detail.style.display = 'grid';
    const stores = d.stores || [];
    const multi = new Set(stores.map((s) => s.search)).size > 1;
    const items = [];
    let lastSearch = null;
    for (const s of stores) {
      if (multi && s.search !== lastSearch) {
        lastSearch = s.search;
        items.push(h('div', { class: 'srow search-head', text: `Search ${s.search}` }));
      }
      items.push(h('div', { class: 'srow' },
        h('span', { class: `dot ${s.tone === 'info' ? 'info live' : s.tone}` }),
        h('div', { class: 'name' }, h('span', { text: s.country || s.platform || '' }), h('span', { text: s.store })),
        h('span', { class: 'n', text: s.count === null || s.count === undefined ? '–' : INT.format(s.count) }),
        h('span', { class: `pill ${s.tone === 'idle' ? '' : s.tone}`, text: s.status })));
    }
    const logBody = h('div', { class: 'log-body', 'aria-live': 'polite' },
      (d.log || []).map((l) => h('div', { class: l.k, text: l.m })));
    detail.replaceChildren(
      h('section', { class: 'card stores', 'aria-label': 'Storefronts' },
        h('h2', { class: 'card-title', style: { marginBottom: '8px' }, text: 'Storefronts' }),
        items.length ? items : h('p', { class: 'sub', text: 'Preparing the storefront list…' })),
      h('section', { class: 'log', 'aria-label': 'Live log' },
        h('div', { class: 'log-head' }, h('h2', { text: 'Live log' }), h('span', { class: 'sub mono', text: 'log.txt · newest at the bottom' })),
        logBody));
    logBody.scrollTop = logBody.scrollHeight;
  }

  function render() { renderHeader(); renderProgress(); renderDetail(); }
  app.update = (data) => {
    data = data || {};
    if (data.run !== app.data.run || data.state !== app.data.state) app.sent = null;
    app.data = data;
    render();
  };
  return app;
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  ensureFont();
  const root = parentElement.querySelector('.pi-run');
  if (!root) return;
  if (!root.__app) root.__app = createApp(root);
  root.__app.api = { setTriggerValue };
  root.__app.update(data || {});
}
