// ③ Results screen. Filtering, the price summary and the chart run here, in the browser,
// so every click is instant. Python builds the downloads: the button sends the exact rows
// on screen (setTriggerValue 'export'), Python answers with the file in `data.export`.

const FONT_HREF = 'https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap';
const PAGE_SIZE = 50;
const USD = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const NUM2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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

// Small element builder. Text always goes in as text (scraped titles are never parsed as HTML).
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'text') el.textContent = value;
    else if (key === 'style') Object.assign(el.style, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'value') el.value = value;
    else if (key === 'checked') el.checked = !!value;
    else el.setAttribute(key, value === true ? '' : String(value));
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

function svg(path, size = 16, stroke = 'currentColor') {
  const ns = 'http://www.w3.org/2000/svg';
  const s = document.createElementNS(ns, 'svg');
  s.setAttribute('width', size); s.setAttribute('height', size); s.setAttribute('viewBox', '0 0 24 24');
  s.setAttribute('fill', 'none'); s.setAttribute('stroke', stroke); s.setAttribute('stroke-width', '2.2');
  s.setAttribute('stroke-linecap', 'round'); s.setAttribute('stroke-linejoin', 'round'); s.setAttribute('aria-hidden', 'true');
  for (const d of path) { const p = document.createElementNS(ns, 'path'); p.setAttribute('d', d); s.append(p); }
  return s;
}
const ICON_DOWNLOAD = ['M12 4v11', 'M7 10l5 5 5-5', 'M5 20h14'];
const ICON_WARN = ['M12 3l9.5 17h-19z', 'M12 10v4', 'M12 17.5v.01'];

const safeUrl = (u) => (typeof u === 'string' && /^https?:\/\//i.test(u) ? u : null);
const fmtUsd = (v) => (v === null || v === undefined ? '—' : USD.format(v));
const fmtLocal = (v, cur) => (v === null || v === undefined ? '—' : `${NUM2.format(v)} ${cur || ''}`.trim());
const cap = (v) => { const t = String(v); return t.charAt(0).toUpperCase() + t.slice(1); };
const dash = (v) => (v === null || v === undefined || v === '' ? '—' : String(v));

function median(values) {
  if (!values.length) return null;
  const s = values.slice().sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}
const round2 = (v) => (v === null ? null : Math.round(v * 100) / 100);

function niceMax(value) {
  if (!(value > 0)) return 100;
  const rough = value / 4;
  const mag = Math.pow(10, Math.floor(Math.log10(rough)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rough);
  return step * 4;
}

const STATUS = {
  completed: ['Completed', ''], partial: ['Partly completed', 'warn'], failed: ['Failed', 'bad'],
  cancelled: ['Cancelled', 'warn'], recovered: ['Recovered after a crash', 'warn'], crashed: ['Stopped unexpectedly', 'bad'],
};
const REVIEW_PILL = { accepted: 'ok', uncertain: 'warn', excluded: 'bad', rejected: 'bad' };

function freshFilters() {
  return { countries: new Set(), platformsOff: new Set(), audiences: new Set(), statuses: new Set(),
           priceMin: '', priceMax: '', text: '', minConf: 0 };
}

function createApp(root) {
  const app = {
    data: {}, api: {}, dataset: null, lastExport: null,
    group: null, view: 'chart', sort: null, page: 0, f: freshFilters(), busy: null,
  };

  // ---- static skeleton -------------------------------------------------------------------
  const header = h('div');
  const banners = h('div', { style: { display: 'flex', flexDirection: 'column', gap: '12px' } });
  const controls = h('div', { class: 'controls' });
  const kpis = h('div', { class: 'kpis' });
  const chartCard = h('section', { class: 'card card-pad chart', 'aria-label': 'Prices by storefront' });
  const filterCard = h('aside', { class: 'card filters', 'aria-label': 'Filters' });
  const tableCard = h('section', { class: 'card', 'aria-label': 'Products' });
  const body = h('div', { style: { display: 'flex', flexDirection: 'column', gap: '24px' } },
    kpis, h('div', { class: 'main-grid' }, chartCard, filterCard), tableCard);
  root.append(header, banners, controls, body);

  // ---- data helpers ----------------------------------------------------------------------
  const groupRows = () => {
    const rows = app.data.rows || [];
    return app.group && app.group !== '__all' ? rows.filter((r) => r.g === app.group) : rows;
  };
  const optionsOf = (rows, key) => [...new Set(rows.map((r) => r[key]).filter((v) => v !== null && v !== ''))]
    .sort((a, b) => String(a).localeCompare(String(b)));

  function filtered() {
    const f = app.f;
    const text = f.text.trim().toLowerCase();
    const lo = f.priceMin === '' ? null : Number(f.priceMin);
    const hi = f.priceMax === '' ? null : Number(f.priceMax);
    return groupRows().filter((r) => {
      if (f.countries.size && !f.countries.has(r.c)) return false;
      if (f.platformsOff.has(r.p)) return false;
      if (f.audiences.size && !f.audiences.has(r.a)) return false;
      if (f.statuses.size && !f.statuses.has(r.st)) return false;
      if (lo !== null && !Number.isNaN(lo) && !(r.usd !== null && r.usd >= lo)) return false;
      if (hi !== null && !Number.isNaN(hi) && !(r.usd !== null && r.usd <= hi)) return false;
      if (f.minConf > 0 && !(r.conf !== null && r.conf >= f.minConf)) return false;
      if (text && !(`${r.n || ''} ${r.b || ''}`.toLowerCase().includes(text))) return false;
      return true;
    });
  }

  function summarize(rows) {
    const multiGroup = app.group === '__all' && new Set(rows.map((r) => r.g)).size > 1;
    const withAudience = rows.some((r) => r.a !== null && r.a !== '');
    const keys = [...(multiGroup ? ['g'] : []), 'c', 'p', 'm', ...(withAudience ? ['a'] : [])];
    const buckets = new Map();
    for (const r of rows) {
      const id = keys.map((k) => (r[k] === null || r[k] === '' ? '—' : r[k])).join('\u0001');
      if (!buckets.has(id)) buckets.set(id, { key: Object.fromEntries(keys.map((k) => [k, r[k] === null || r[k] === '' ? '—' : r[k]])), rows: [] });
      buckets.get(id).rows.push(r);
    }
    const out = [...buckets.values()].map(({ key, rows: rs }) => {
      const local = rs.map((r) => r.v).filter((v) => v !== null);
      const usd = rs.map((r) => r.usd).filter((v) => v !== null);
      return {
        ...key, listings: rs.length, with_price: local.length,
        currency: [...new Set(rs.map((r) => r.cur).filter(Boolean))].sort().join(', '),
        min: round2(local.length ? Math.min(...local) : null), median: round2(median(local)),
        max: round2(local.length ? Math.max(...local) : null),
        min_usd: round2(usd.length ? Math.min(...usd) : null), median_usd: round2(median(usd)),
        mean_usd: round2(usd.length ? usd.reduce((a, b) => a + b, 0) / usd.length : null),
        max_usd: round2(usd.length ? Math.max(...usd) : null),
      };
    });
    out.sort((a, b) => keys.map((k) => String(a[k]).localeCompare(String(b[k]))).find((x) => x !== 0) || 0);
    out.sort((a, b) => (a.median_usd === null) - (b.median_usd === null) || (a.median_usd ?? 0) - (b.median_usd ?? 0));
    return { rows: out, keys };
  }

  function headline(rows, summary) {
    const priced = summary.rows.filter((s) => s.median_usd !== null);
    const most = priced.length ? Math.max(...priced.map((s) => s.with_price)) : 0;
    const solid = priced.filter((s) => s.with_price >= Math.min(3, most));
    const usd = rows.map((r) => r.usd).filter((v) => v !== null);
    return {
      listings: rows.length, storefronts: new Set(rows.map((r) => r.m)).size, median: median(usd),
      cheapest: solid[0] || null, dearest: solid.length ? solid[solid.length - 1] : null,
    };
  }

  const storeSub = (s) => [s.m, s.a && s.a !== '—' ? s.a : null, s.g && s.g !== '—' ? s.g : null].filter(Boolean).join(' · ');

  function describeFilters() {
    const f = app.f;
    const parts = [];
    if (f.countries.size) parts.push(`country=${[...f.countries].join('/')}`);
    if (f.platformsOff.size) parts.push(`without ${[...f.platformsOff].join('/')}`);
    if (f.audiences.size) parts.push(`audience=${[...f.audiences].join('/')}`);
    if (f.priceMin !== '' || f.priceMax !== '') parts.push(`price ${f.priceMin || 0}–${f.priceMax || 'any'} USD`);
    if (f.minConf) parts.push(`min confidence=${f.minConf}%`);
    if (f.statuses.size) parts.push(`review status=${[...f.statuses].join('/')}`);
    if (f.text.trim()) parts.push(`text='${f.text.trim()}'`);
    return parts.join(', ') || 'none';
  }
  const hasFilters = () => describeFilters() !== 'none';

  // ---- actions ---------------------------------------------------------------------------
  function requestExport(kind) {
    if (!app.api.setTriggerValue) return;
    app.busy = kind;
    renderHeader();
    const groupLabel = app.group === '__all' ? 'all (not comparable)' : (app.group || '');
    app.api.setTriggerValue('export', { kind, rows: filtered().map((r) => r.i), filters: describeFilters(), group: groupLabel });
  }

  function deliver(exp) {
    app.busy = null;
    if (exp.error) { app.exportError = exp.error; return; }
    app.exportError = null;
    try {
      const bin = atob(exp.b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const url = URL.createObjectURL(new Blob([bytes], { type: exp.mime }));
      const a = document.createElement('a');
      a.href = url; a.download = exp.name; a.style.display = 'none';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } catch (err) {
      app.exportError = `Download failed: ${err}`;
    }
  }

  // ---- rendering -------------------------------------------------------------------------
  function renderHeader() {
    const d = app.data;
    const [statusText, statusKind] = STATUS[d.status] || [d.status ? d.status[0].toUpperCase() + d.status.slice(1) : 'Unknown', 'idle'];
    const busy = !!app.busy || !(d.rows || []).length;
    header.replaceChildren(h('div', { class: 'hd' },
      h('div', { class: 'hd-text' },
        h('span', { class: 'eyebrow' }, 'Results / ', h('b', { text: d.run || '' })),
        h('h1', { class: 'title', text: d.title || d.run || 'Results' }),
        h('div', { class: 'chips' },
          h('span', { class: 'chip' }, h('span', { class: `dot ${statusKind}` }), statusText),
          h('span', { class: 'chip', text: d.source === 'reviewed' ? 'AI-reviewed data' : 'All collected listings' }),
          d.fx ? h('span', { class: 'chip', title: d.fx_title || '', text: d.fx }) : null)),
      h('div', { class: 'hd-actions' },
        h('button', { type: 'button', class: 'btn', disabled: busy, onclick: () => requestExport('csv'),
                      title: 'The products shown below, with ids, scrape time and review fields.' },
          app.busy === 'csv' ? 'Preparing…' : 'Products CSV'),
        h('button', { type: 'button', class: 'btn primary', disabled: busy, onclick: () => requestExport('xlsx'),
                      title: 'Summary per storefront + products + method, with the filters applied.' },
          svg(ICON_DOWNLOAD), app.busy === 'xlsx' ? 'Preparing…' : 'Price report (Excel)'))));
  }

  function renderBanners() {
    const d = app.data;
    const items = [];
    if (d.outdated) {
      items.push(h('div', { class: 'banner warn', role: 'status' }, svg(ICON_WARN, 18),
        h('span', { text: `The relevance review is out of date: ${d.outdated.added} listing(s) were added later (retry) and have not been reviewed. Add them on the ④ Relevance review tab; until then the reviewed data misses them.` })));
    }
    if (app.group === '__all' && (d.groups || []).length > 1) {
      items.push(h('div', { class: 'banner info' }, svg(ICON_WARN, 18),
        h('span', { text: 'Several product groups are combined, so headline prices mix different products. Pick one product group to compare prices.' })));
    }
    if (app.exportError) items.push(h('div', { class: 'banner bad', role: 'alert', text: app.exportError }));
    banners.replaceChildren(...items);
    banners.style.display = items.length ? 'flex' : 'none';
  }

  function renderControls() {
    const d = app.data;
    const groups = d.groups || [];
    const parts = [];
    if (groups.length > 1) {
      parts.push(h('div', { class: 'seg', role: 'group', 'aria-label': 'Product group' },
        h('span', { class: 'seg-label', text: 'Product group' }),
        [...groups, '__all'].map((g) => h('button', {
          type: 'button', 'aria-pressed': String(app.group === g),
          onclick: () => { if (app.group !== g) { app.group = g; resetFilters(false); } },
        }, g === '__all' ? 'All groups' : g))));
    } else {
      parts.push(h('span'));
    }
    if (d.has_review) {
      parts.push(h('div', { class: 'seg', role: 'group', 'aria-label': 'Data' },
        [['reviewed', 'Reviewed'], ['all', 'Everything collected']].map(([value, label]) => h('button', {
          type: 'button', 'aria-pressed': String(d.source === value),
          title: value === 'reviewed' ? 'Listings the AI review accepted or was unsure about' : 'Every listing the scraper kept',
          onclick: () => { if (d.source !== value && app.api.setStateValue) app.api.setStateValue('source', value); },
        }, label))));
    }
    controls.replaceChildren(...parts);
    controls.style.display = groups.length > 1 || d.has_review ? 'flex' : 'none';
  }

  function chipRow(options, selected, onToggle, label) {
    const row = h('div', { class: 'fchips', role: 'group', 'aria-label': label });
    const draw = () => row.replaceChildren(
      h('button', { type: 'button', class: 'fchip', 'aria-pressed': String(selected.size === 0),
                    onclick: () => { selected.clear(); draw(); onToggle(); } }, 'All'),
      ...options.map((o) => h('button', {
        type: 'button', class: 'fchip', 'aria-pressed': String(selected.has(o)),
        onclick: () => { selected.has(o) ? selected.delete(o) : selected.add(o); draw(); onToggle(); },
      }, cap(o))));
    draw();
    return row;
  }

  let textTimer = null;
  function renderFilters() {
    const f = app.f;
    const base = groupRows();
    const countries = optionsOf(base, 'c');
    const platforms = optionsOf(base, 'p');
    const audiences = optionsOf(base, 'a');
    const statuses = optionsOf(base, 'st');
    const hasConf = base.some((r) => r.conf !== null);
    const usd = base.map((r) => r.usd).filter((v) => v !== null);
    const update = () => { app.page = 0; renderResults(); };
    const confOut = h('output', { text: `${f.minConf}%` });

    const groups = [h('div', { class: 'card-head' }, h('h2', { class: 'card-title', text: 'Filters' }),
      h('button', { type: 'button', class: 'link-btn', onclick: () => resetFilters(true) }, 'Reset'))];
    if (countries.length > 1) groups.push(h('div', { class: 'fgroup' }, h('span', { class: 'flabel', text: 'Country' }),
      chipRow(countries, f.countries, update, 'Country')));
    if (platforms.length > 1) groups.push(h('div', { class: 'fgroup' }, h('span', { class: 'flabel', text: 'Platform' }),
      h('div', { class: 'checks' }, platforms.map((p) => h('label', {},
        h('input', { type: 'checkbox', checked: !f.platformsOff.has(p),
                     onchange: (e) => { e.target.checked ? f.platformsOff.delete(p) : f.platformsOff.add(p); update(); } }),
        p[0].toUpperCase() + p.slice(1))))));
    if (audiences.length) groups.push(h('div', { class: 'fgroup' }, h('span', { class: 'flabel', text: 'Audience' }),
      chipRow(audiences, f.audiences, update, 'Audience')));
    groups.push(h('div', { class: 'fgroup' }, h('span', { class: 'flabel', text: 'Price (USD)' }),
      h('div', { class: 'pair' },
        h('label', {}, 'From', h('input', { class: 'field num', type: 'number', min: '0', inputmode: 'decimal', value: f.priceMin,
          placeholder: usd.length ? String(Math.floor(Math.min(...usd))) : '0',
          oninput: (e) => { f.priceMin = e.target.value; update(); } })),
        h('label', {}, 'To', h('input', { class: 'field num', type: 'number', min: '0', inputmode: 'decimal', value: f.priceMax,
          placeholder: usd.length ? String(Math.ceil(Math.max(...usd))) : 'any',
          oninput: (e) => { f.priceMax = e.target.value; update(); } })))));
    if (hasConf) {
      groups.push(h('div', { class: 'fgroup' },
        h('label', { class: 'flabel', for: 'pi-conf' }, h('span', { text: 'Minimum relevance confidence' }), confOut),
        h('input', { id: 'pi-conf', type: 'range', min: '0', max: '100', step: '5', value: String(f.minConf),
                     oninput: (e) => { f.minConf = Number(e.target.value); confOut.textContent = `${f.minConf}%`; update(); } })));
    }
    if (statuses.length) groups.push(h('div', { class: 'fgroup' }, h('span', { class: 'flabel', text: 'Review status' }),
      chipRow(statuses, f.statuses, update, 'Review status')));
    groups.push(h('label', { class: 'fgroup' }, h('span', { class: 'flabel', text: 'Search product or brand' }),
      h('input', { class: 'field', type: 'search', value: f.text, placeholder: 'e.g. Pegasus, Samsung',
                   oninput: (e) => { f.text = e.target.value; clearTimeout(textTimer); textTimer = setTimeout(update, 150); } })));
    filterCard.replaceChildren(...groups);
  }

  function resetFilters(redrawAll) {
    app.f = freshFilters();
    app.page = 0;
    if (redrawAll) app.exportError = null;
    renderControls();
    renderBanners();
    renderFilters();
    renderResults();
  }

  function renderKpis(head) {
    const tile = (label, value, sub, cls) => h('div', { class: 'card kpi' },
      h('span', { class: 'kpi-label', text: label }), h('span', { class: cls, text: value }), h('span', { class: 'kpi-sub', text: sub }));
    kpis.replaceChildren(
      tile('Listings', INT.format(head.listings), `${head.storefronts} storefront${head.storefronts === 1 ? '' : 's'}`, 'kpi-value'),
      tile('Median price', fmtUsd(head.median), 'across the shown listings, USD', 'kpi-value accent'),
      tile('Cheapest storefront', head.cheapest ? head.cheapest.c : '—',
        head.cheapest ? `${storeSub(head.cheapest)} · median ${fmtUsd(head.cheapest.median_usd)}` : 'needs listings with a price', 'kpi-word'),
      tile('Most expensive', head.dearest ? head.dearest.c : '—',
        head.dearest ? `${storeSub(head.dearest)} · median ${fmtUsd(head.dearest.median_usd)}` : 'needs listings with a price', 'kpi-word'));
  }

  function renderChart(summary, head) {
    const viewToggle = h('div', { class: 'seg small', role: 'group', 'aria-label': 'View' },
      [['chart', 'Chart'], ['table', 'Table']].map(([v, label]) => h('button', {
        type: 'button', 'aria-pressed': String(app.view === v), onclick: () => { app.view = v; renderResults(); },
      }, label)));
    const headRow = h('div', { class: 'card-head' }, h('h2', { class: 'card-title', text: 'Prices by storefront' }),
      h('div', { style: { display: 'flex', gap: '18px', alignItems: 'center', flexWrap: 'wrap' } },
        app.view === 'chart' ? h('div', { class: 'legend' },
          h('span', {}, h('i', { class: 'lg-range' }), 'lowest to highest'), h('span', {}, h('i', { class: 'lg-med' }), 'median')) : null,
        viewToggle));
    const priced = summary.rows.filter((s) => s.median_usd !== null);
    if (!priced.length) {
      chartCard.replaceChildren(headRow, h('p', { class: 'sub', text: 'No listings with a price to compare.' }));
      return;
    }
    if (app.view === 'table') {
      const cols = [
        ['Storefront', (s) => h('td', {}, h('div', { class: 'clabel' }, h('span', { class: 'c', text: s.c }), h('span', { class: 'm', text: storeSub(s) })))],
        ['Listings', (s) => h('td', { class: 'num r', text: INT.format(s.listings) }), 'r'],
        ['With price', (s) => h('td', { class: 'num r dim', text: INT.format(s.with_price) }), 'r'],
        ['Currency', (s) => h('td', { class: 'num dim', text: s.currency || '—' })],
        ['Min', (s) => h('td', { class: 'num r dim', text: s.min === null ? '—' : NUM2.format(s.min) }), 'r'],
        ['Median', (s) => h('td', { class: 'num r', text: s.median === null ? '—' : NUM2.format(s.median) }), 'r'],
        ['Max', (s) => h('td', { class: 'num r dim', text: s.max === null ? '—' : NUM2.format(s.max) }), 'r'],
        ['Min USD', (s) => h('td', { class: 'num r dim', text: fmtUsd(s.min_usd) }), 'r'],
        ['Median USD', (s) => h('td', { class: 'num r', style: s === head.cheapest ? { color: 'var(--accent)' } : null, text: fmtUsd(s.median_usd) }), 'r'],
        ['Mean USD', (s) => h('td', { class: 'num r dim', text: fmtUsd(s.mean_usd) }), 'r'],
        ['Max USD', (s) => h('td', { class: 'num r dim', text: fmtUsd(s.max_usd) }), 'r'],
      ];
      chartCard.replaceChildren(headRow, h('div', { class: 'tbl-wrap', style: { margin: '0 -24px -22px' } },
        h('table', {}, h('thead', {}, h('tr', {}, cols.map(([label, , cls]) => h('th', { class: cls, scope: 'col', text: label })))),
          h('tbody', {}, summary.rows.map((s) => h('tr', {}, cols.map(([, cell]) => cell(s))))))));
      return;
    }
    const top = niceMax(Math.max(...priced.map((s) => s.max_usd ?? s.median_usd)));
    const pct = (v) => `${Math.max(0, Math.min(100, (v / top) * 100))}%`;
    const rows = priced.map((s) => {
      const tip = `${s.c} · ${storeSub(s)}\n${s.with_price} listing(s) with a price\nmin ${fmtUsd(s.min_usd)} · median ${fmtUsd(s.median_usd)} · max ${fmtUsd(s.max_usd)}`
        + (s.currency && s.currency !== 'USD' ? `\nmedian ${fmtLocal(s.median, s.currency)}` : '');
      return h('div', { class: 'crow', title: tip },
        h('div', { class: 'clabel' }, h('span', { class: 'c', text: s.c }), h('span', { class: 'm', text: storeSub(s) })),
        h('div', { class: 'track', role: 'img', 'aria-label': tip.replace(/\n/g, ', ') },
          h('div', { class: 'range', style: { left: pct(s.min_usd ?? s.median_usd), width: `calc(${pct((s.max_usd ?? s.median_usd) - (s.min_usd ?? s.median_usd))})` } }),
          h('div', { class: 'med', style: { left: pct(s.median_usd) } })),
        h('span', { class: `cval${s === head.cheapest ? ' best' : ''}`, text: fmtUsd(s.median_usd) }));
    });
    const ticks = [0, 1, 2, 3, 4].map((q) => h('span', { text: USD.format((top * q) / 4).replace(/\.00$/, '') }));
    chartCard.replaceChildren(headRow, h('div', { class: 'rows' }, rows),
      h('div', { class: 'axis' }, h('span'), h('div', { class: 'ticks' }, ticks), h('span')));
  }

  function renderTable(rows) {
    const hasAudience = rows.some((r) => r.a);
    const hasConf = rows.some((r) => r.conf !== null);
    const hasStatus = rows.some((r) => r.st);
    if (!app.sort) app.sort = hasConf ? { key: 'conf', dir: -1 } : { key: 'usd', dir: 1 };
    const { key, dir } = app.sort;
    const val = (r) => (key === 'n' ? (r.n || '').toLowerCase() : key === 'm' ? r.m || '' : r[key]);
    const sorted = rows.slice().sort((a, b) => {
      const x = val(a), y = val(b);
      if (x === null || x === undefined) return (y === null || y === undefined) ? 0 : 1;
      if (y === null || y === undefined) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
    const pages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
    app.page = Math.min(app.page, pages - 1);
    const shown = sorted.slice(app.page * PAGE_SIZE, (app.page + 1) * PAGE_SIZE);

    const th = (label, k, cls) => {
      if (!k) return h('th', { scope: 'col', class: cls, text: label });
      const active = key === k;
      return h('th', { scope: 'col', class: cls, 'aria-sort': active ? (dir > 0 ? 'ascending' : 'descending') : null },
        h('button', { type: 'button', onclick: () => {
          app.sort = active ? { key: k, dir: -dir } : { key: k, dir: k === 'conf' ? -1 : 1 }; app.page = 0; renderResults();
        } }, label, active ? (dir > 0 ? '↑' : '↓') : ''));
    };
    const head = h('tr', {}, th('Product', 'n'), th('Storefront', 'm'), hasAudience ? th('Audience', 'a') : null,
      th('Local price', null, 'r'), th('USD', 'usd', 'r'), hasConf ? th('Confidence', 'conf') : null, hasStatus ? th('Review', 'st') : null);
    const body = shown.map((r) => {
      const url = safeUrl(r.u);
      const conf = r.conf === null ? null : Math.round(r.conf);
      return h('tr', {},
        h('td', {}, h('div', { class: 'pname' },
          url ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer', title: r.n || '', text: r.n || '(no title)' })
              : h('span', { class: 't', title: r.n || '', text: r.n || '(no title)' }),
          r.b ? h('span', { class: 'b', text: r.b }) : null)),
        h('td', { class: 'store', text: r.m || '—' }),
        hasAudience ? h('td', { class: 'dim', text: dash(r.a) }) : null,
        h('td', { class: 'num r dim', text: fmtLocal(r.v, r.cur) }),
        h('td', { class: 'num r', text: fmtUsd(r.usd) }),
        hasConf ? h('td', {}, conf === null ? h('span', { class: 'sub', text: '—' }) : h('div', { class: 'conf' },
          h('div', { class: 'track2' }, h('div', { class: `fill${conf >= 75 ? '' : conf >= 40 ? ' mid' : ' low'}`, style: { width: `${conf}%` } })),
          h('span', { text: `${conf}%` }))) : null,
        hasStatus ? h('td', {}, r.st ? h('span', { class: `pill ${REVIEW_PILL[String(r.st).toLowerCase()] || ''}`, text: cap(r.st) }) : '—') : null);
    });
    const from = sorted.length ? app.page * PAGE_SIZE + 1 : 0;
    const to = Math.min(sorted.length, (app.page + 1) * PAGE_SIZE);
    tableCard.replaceChildren(
      h('div', { class: 'card-head tbl-head' }, h('h2', { class: 'card-title', text: 'Products' }),
        h('span', { class: 'sub', text: `${INT.format(sorted.length)} shown${hasFilters() ? ' · filtered' : ''}` })),
      h('div', { class: 'tbl-wrap' }, h('table', {}, h('thead', {}, head), h('tbody', {}, body))),
      pages > 1 ? h('div', { class: 'pager' }, h('span', { text: `${INT.format(from)}–${INT.format(to)} of ${INT.format(sorted.length)}` }),
        h('div', {},
          h('button', { type: 'button', class: 'btn small', disabled: app.page === 0, onclick: () => { app.page -= 1; renderResults(); } }, 'Previous'),
          h('button', { type: 'button', class: 'btn small', disabled: app.page >= pages - 1, onclick: () => { app.page += 1; renderResults(); } }, 'Next'))) : null);
  }

  function renderResults() {
    const rows = filtered();
    if (!(app.data.rows || []).length) {
      body.replaceChildren(h('div', { class: 'card empty' }, h('strong', { text: 'This run has no listings' }),
        h('span', { text: app.data.note || 'Check the search status and errors below.' })));
      return;
    }
    if (!body.contains(kpis)) body.replaceChildren(kpis, h('div', { class: 'main-grid' }, chartCard, filterCard), tableCard);
    const summary = summarize(rows);
    const head = headline(rows, summary);
    renderKpis(head);
    if (!rows.length) {
      chartCard.replaceChildren(h('div', { class: 'empty' }, h('strong', { text: 'No listings match these filters' }),
        h('button', { type: 'button', class: 'btn small', onclick: () => resetFilters(true) }, 'Reset filters')));
    } else {
      renderChart(summary, head);
    }
    renderTable(rows);
  }

  app.update = (data) => {
    app.data = data || {};
    const groups = app.data.groups || [];
    if (app.data.dataset !== app.dataset) {
      app.dataset = app.data.dataset;
      if (!groups.includes(app.group) && app.group !== '__all') app.group = groups[0] || null;
      if (groups.length <= 1) app.group = null;
      app.f = freshFilters();
      app.sort = null;
      app.page = 0;
      renderFilters();
    }
    const exp = app.data.export;
    if (exp && exp.nonce && exp.nonce !== app.lastExport) {
      app.lastExport = exp.nonce;
      deliver(exp);
    }
    renderHeader();
    renderBanners();
    renderControls();
    renderResults();
  };
  return app;
}

export default function (component) {
  const { data, parentElement, setTriggerValue, setStateValue } = component;
  ensureFont();
  const root = parentElement.querySelector('.pi-results');
  if (!root) return;
  if (!root.__app) root.__app = createApp(root);
  root.__app.api = { setTriggerValue, setStateValue };
  root.__app.update(data || {});
}
