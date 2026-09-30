// Results step. Filters, the storefront summary and the chart run in the browser (instant);
// downloads send the rows on screen to the server, which builds the Excel report / CSV.
import { api, enc } from '../api.js';
import { banner, clear, fmt, h, icon, median, platformName, safeUrl, toast } from '../dom.js';

const PAGE = 50;
const REVIEW_TONE = { accepted: 'ok', uncertain: 'warn', excluded: 'bad' };

function niceMax(v) {
  if (!(v > 0)) return 100;
  const rough = v / 4;
  const mag = 10 ** Math.floor(Math.log10(rough));
  return [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rough) * 4;
}
const round2 = (v) => (v === null ? null : Math.round(v * 100) / 100);
const fresh = () => ({ countries: new Set(), platformsOff: new Set(), audiences: new Set(), statuses: new Set(),
  priceMin: '', priceMax: '', text: '', minConf: 0 });

export async function renderResults(body, ctx) {
  const id = ctx.id;
  let data = await api.get(`/api/runs/${enc(id)}/products`);
  const detail = ctx.detail();
  const st = { group: data.groups[0] || null, f: fresh(), view: 'chart', sort: null, page: 0 };
  if (data.groups.length <= 1) st.group = null;

  const banners = h('div', { class: 'stack tight' });
  const finding = h('p', { class: 'finding' });
  const toolbar = h('div', { class: 'row', style: { justifyContent: 'space-between', gap: '12px' } });
  const chartCard = h('section', { class: 'card pad stack', 'aria-label': 'Price by storefront', style: { gap: '14px' } });
  const statsCard = h('aside', { class: 'card stat-list', 'aria-label': 'Summary', style: { padding: '6px 22px' } });
  const tableCard = h('section', { class: 'card', 'aria-label': 'Listings', style: { overflow: 'hidden' } });
  const menus = [];

  // ---- data ----------------------------------------------------------------------------------------
  const groupRows = () => (st.group && st.group !== '__all' ? data.rows.filter((r) => r.g === st.group) : data.rows);
  const opts = (rows, key) => [...new Set(rows.map((r) => r[key]).filter((v) => v !== null && v !== ''))].sort((a, b) => String(a).localeCompare(String(b)));
  function filtered() {
    const f = st.f;
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
      if (text && !`${r.n || ''} ${r.b || ''}`.toLowerCase().includes(text)) return false;
      return true;
    });
  }
  function summarize(rows) {
    const multi = st.group === '__all' && new Set(rows.map((r) => r.g)).size > 1;
    const aud = rows.some((r) => r.a);
    const keys = [...(multi ? ['g'] : []), 'c', 'p', 'm', ...(aud ? ['a'] : [])];
    const buckets = new Map();
    for (const r of rows) {
      const k = keys.map((key) => r[key] ?? '—').join('\u0001');
      if (!buckets.has(k)) buckets.set(k, { key: Object.fromEntries(keys.map((key) => [key, r[key] ?? '—'])), rows: [] });
      buckets.get(k).rows.push(r);
    }
    const out = [...buckets.values()].map(({ key, rows: rs }) => {
      const loc = rs.map((r) => r.v).filter((v) => v !== null);
      const usd = rs.map((r) => r.usd).filter((v) => v !== null);
      return { ...key, listings: rs.length, with_price: loc.length,
        currency: [...new Set(rs.map((r) => r.cur).filter(Boolean))].sort().join(', '),
        min: round2(loc.length ? Math.min(...loc) : null), median: round2(median(loc)), max: round2(loc.length ? Math.max(...loc) : null),
        min_usd: round2(usd.length ? Math.min(...usd) : null), median_usd: round2(median(usd)),
        mean_usd: round2(usd.length ? usd.reduce((a, b) => a + b, 0) / usd.length : null), max_usd: round2(usd.length ? Math.max(...usd) : null) };
    });
    out.sort((a, b) => (a.median_usd === null) - (b.median_usd === null) || (a.median_usd ?? 0) - (b.median_usd ?? 0));
    return out;
  }
  function headline(rows, summary) {
    const priced = summary.filter((s) => s.median_usd !== null);
    const most = priced.length ? Math.max(...priced.map((s) => s.with_price)) : 0;
    const solid = priced.filter((s) => s.with_price >= Math.min(3, most));
    const usd = rows.map((r) => r.usd).filter((v) => v !== null);
    return { listings: rows.length, storefronts: new Set(rows.map((r) => r.m)).size, median: median(usd),
      mean: usd.length ? usd.reduce((a, b) => a + b, 0) / usd.length : null,
      cheapest: solid[0] || null, dearest: solid.length > 1 ? solid[solid.length - 1] : null };
  }
  const storeSub = (s) => [s.m, s.a && s.a !== '—' ? s.a : null, s.g && s.g !== '—' ? s.g : null].filter(Boolean).join(' · ');
  const delta = (v, m) => (m ? Math.round((v / m - 1) * 100) : 0);
  function describeFilters() {
    const f = st.f;
    const parts = [];
    if (f.countries.size) parts.push(`country=${[...f.countries].join('/')}`);
    if (f.platformsOff.size) parts.push(`without ${[...f.platformsOff].map(platformName).join('/')}`);
    if (f.audiences.size) parts.push(`audience=${[...f.audiences].join('/')}`);
    if (f.priceMin !== '' || f.priceMax !== '') parts.push(`price ${f.priceMin || 0}–${f.priceMax || 'any'} USD`);
    if (f.minConf) parts.push(`min confidence=${f.minConf}%`);
    if (f.statuses.size) parts.push(`review status=${[...f.statuses].join('/')}`);
    if (f.text.trim()) parts.push(`text='${f.text.trim()}'`);
    return parts.join(', ') || 'none';
  }

  // ---- header actions (downloads) ------------------------------------------------------------------
  async function exportFile(kind, button) {
    const label = button.textContent;
    button.disabled = true;
    button.lastChild.textContent = 'Preparing…';
    try {
      await api.file('POST', `/api/runs/${enc(id)}/export`, { kind, source: data.source, rows: filtered().map((r) => r.i),
        filters: describeFilters(), group: st.group === '__all' ? 'all (not comparable)' : st.group || '' });
    } catch (err) { toast(err.message, 'bad'); }
    button.disabled = false;
    button.lastChild.textContent = label;
  }
  const csvBtn = h('button', { type: 'button', class: 'btn', title: 'The listings shown, with ids, scrape time and review fields' }, h('span', { text: 'CSV' }));
  const xlsBtn = h('button', { type: 'button', class: 'btn primary', title: 'Summary per storefront, listings and method, with your filters applied' },
    icon('download'), h('span', { text: 'Excel report' }));
  csvBtn.addEventListener('click', () => exportFile('csv', csvBtn));
  xlsBtn.addEventListener('click', () => exportFile('xlsx', xlsBtn));
  clear(ctx.actions, csvBtn, xlsBtn);

  if (!data.rows.length) {
    clear(body, h('section', { class: 'card' }, h('div', { class: 'empty' }, h('h2', { text: 'No listings yet' }),
      h('p', { text: 'Nothing was collected for this research. See the Collect step for what each storefront returned.' }),
      h('a', { class: 'btn', href: `#/r/${id}/collect` }, 'Open the Collect step'))));
    return null;
  }

  // ---- toolbar ----------------------------------------------------------------------------------------
  function filterMenu(label, build, isActive, summaryText) {
    const summary = h('summary', { class: 'filter-btn', style: { listStyle: 'none' } });
    const panel = h('div', { class: 'popover', style: { width: '280px' } });
    const el = h('details', { class: 'pop-anchor' }, summary, panel);
    const refresh = () => {
      summary.classList.toggle('active', isActive());
      clear(summary, `${label}: ${summaryText()}`, icon('down', 12));
    };
    el.addEventListener('toggle', () => { if (el.open) { menus.forEach((m) => { if (m.el !== el) m.el.open = false; }); clear(panel, build()); } });
    refresh();
    const menu = { el, refresh };
    menus.push(menu);
    return menu;
  }
  function checkList(options, selected, { labelOf = (o) => o, invert = false } = {}) {
    return [
      h('div', { class: 'row', style: { justifyContent: 'space-between', padding: '4px 8px' } },
        h('span', { class: 'muted small', text: invert ? 'Include' : 'Show only' }),
        h('button', { type: 'button', class: 'link', onclick: (e) => { selected.clear(); update(); const d = e.target.closest('details'); d.open = false; } }, 'All')),
      options.map((o) => h('label', { class: 'opt' }, h('input', { type: 'checkbox', checked: invert ? !selected.has(o) : selected.has(o), onchange: (e) => {
        const on = e.target.checked;
        if (invert ? !on : on) selected.add(o); else selected.delete(o);
        update();
      } }), labelOf(o))),
    ];
  }

  function drawToolbar() {
    menus.length = 0;
    const base = groupRows();
    const countries = opts(base, 'c');
    const platforms = opts(base, 'p');
    const audiences = opts(base, 'a');
    const statuses = opts(base, 'st');
    const hasConf = base.some((r) => r.conf !== null);
    const usd = base.map((r) => r.usd).filter((v) => v !== null);
    const f = st.f;
    const left = h('div', { class: 'row', style: { gap: '8px' } });
    if (data.groups.length > 1) {
      left.append(h('div', { class: 'seg', role: 'group', 'aria-label': 'Product group' }, [...data.groups, '__all'].map((g) => h('button', {
        type: 'button', 'aria-pressed': String(st.group === g), onclick: () => { st.group = g; st.f = fresh(); st.page = 0; drawToolbar(); update(); },
      }, g === '__all' ? 'All groups' : g.replace(/^\d+ · /, '')))));
    }
    if (countries.length > 1) left.append(filterMenu('Countries', () => checkList(countries, f.countries), () => f.countries.size > 0,
      () => (f.countries.size ? `${f.countries.size} of ${countries.length}` : `All ${countries.length}`)).el);
    if (platforms.length > 1) left.append(filterMenu('Platforms', () => checkList(platforms, f.platformsOff, { labelOf: platformName, invert: true }),
      () => f.platformsOff.size > 0, () => `${platforms.length - f.platformsOff.size}`).el);
    if (audiences.length) left.append(filterMenu('Audience', () => checkList(audiences, f.audiences, { labelOf: fmt.cap }), () => f.audiences.size > 0,
      () => (f.audiences.size ? [...f.audiences].map(fmt.cap).join(', ') : 'All')).el);
    left.append(filterMenu('Price', () => {
      const min = h('input', { class: 'field sm num', type: 'number', min: '0', value: f.priceMin, placeholder: usd.length ? String(Math.floor(Math.min(...usd))) : '0',
        'aria-label': 'From (USD)', oninput: (e) => { f.priceMin = e.target.value; update(); } });
      const max = h('input', { class: 'field sm num', type: 'number', min: '0', value: f.priceMax, placeholder: usd.length ? String(Math.ceil(Math.max(...usd))) : 'any',
        'aria-label': 'To (USD)', oninput: (e) => { f.priceMax = e.target.value; update(); } });
      return h('div', { class: 'stack tight', style: { padding: '6px' } }, h('span', { class: 'muted small', text: 'Price in USD' }),
        h('div', { class: 'row', style: { flexWrap: 'nowrap' } }, min, h('span', { class: 'muted', text: 'to' }), max));
    }, () => f.priceMin !== '' || f.priceMax !== '', () => (f.priceMin !== '' || f.priceMax !== '' ? `${f.priceMin || 0}–${f.priceMax || 'any'} USD` : 'Any')).el);
    if (hasConf) left.append(filterMenu('Confidence', () => {
      const out = h('output', { class: 'mono', text: `${f.minConf}%` });
      return h('div', { class: 'stack tight', style: { padding: '6px' } },
        h('label', { class: 'row', style: { justifyContent: 'space-between' }, for: 'res-conf' }, h('span', { class: 'muted small', text: 'Minimum relevance confidence' }), out),
        h('input', { id: 'res-conf', type: 'range', min: '0', max: '100', step: '5', value: String(f.minConf), style: { accentColor: 'var(--accent)' },
          oninput: (e) => { f.minConf = Number(e.target.value); out.textContent = `${f.minConf}%`; update(); } }));
    }, () => f.minConf > 0, () => (f.minConf ? `≥ ${f.minConf}%` : 'Any')).el);
    if (statuses.length) left.append(filterMenu('Review', () => checkList(statuses, f.statuses, { labelOf: fmt.cap }), () => f.statuses.size > 0,
      () => (f.statuses.size ? [...f.statuses].map(fmt.cap).join(', ') : 'All')).el);
    const right = h('div', { class: 'row', style: { gap: '8px' } },
      h('label', { class: 'search-box', style: { width: '220px', height: '40px' } }, icon('search', 15),
        h('input', { type: 'search', placeholder: 'Product or brand', 'aria-label': 'Search product or brand', value: f.text,
          oninput: (e) => { f.text = e.target.value; st.page = 0; update(); } })),
      data.has_review ? h('div', { class: 'seg', role: 'group', 'aria-label': 'Data' }, [['reviewed', 'Reviewed'], ['all', 'Everything collected']].map(([v, l]) => h('button', {
        type: 'button', 'aria-pressed': String(data.source === v), title: v === 'reviewed' ? 'Listings the review kept' : 'Every listing the scraper kept',
        onclick: async () => { if (data.source === v) return; data = await api.get(`/api/runs/${enc(id)}/products?source=${v}`); st.f = fresh(); st.page = 0; st.sort = null; drawAll(); },
      }, l))) : null);
    clear(toolbar, left, right);
  }

  // ---- drawing -----------------------------------------------------------------------------------------
  function drawBanners() {
    const items = [];
    if (data.outdated) items.push(banner('warn', `The review is out of date: ${data.outdated.added} listing(s) were added later by a retry and have not been reviewed. `,
      h('a', { href: `#/r/${id}/review` }, 'Review them now')));
    if (st.group === '__all') items.push(banner('info', 'Several product groups are combined, so these prices mix different products. Pick one group to compare prices.'));
    const failed = (detail.failed_storefronts || []).length;
    if (failed) items.push(banner('info', `${failed} storefront(s) returned nothing. `, h('a', { href: `#/r/${id}/collect` }, 'Retry them on the Collect step')));
    clear(banners, items);
  }

  function update() {
    menus.forEach((m) => m.refresh());
    const rows = filtered();
    const summary = summarize(rows);
    const head = headline(rows, summary);
    drawFinding(head);
    drawStats(head, rows);
    drawChart(summary, head);
    drawTable(rows);
  }

  function drawFinding(head) {
    const group = st.group && st.group !== '__all' ? st.group.replace(/^\d+ · /, '') : '';
    if (!head.listings) { clear(finding, 'No listings match these filters. ', h('button', { type: 'button', class: 'link', style: { fontSize: '20px' }, onclick: reset }, 'Reset filters')); return; }
    const m = head.median;
    const parts = [`The median price${group ? ` for ${group.toLowerCase()}` : ''} is `, h('span', { class: 'accent', text: fmt.usd(m) }),
      ` across ${head.storefronts} storefront${head.storefronts === 1 ? '' : 's'}.`];
    if (head.cheapest && head.dearest && head.cheapest !== head.dearest) {
      const dc = delta(head.cheapest.median_usd, m);
      const dd = delta(head.dearest.median_usd, m);
      // name the storefront when both ends are in the same country (e.g. Germany on eBay vs Amazon)
      const same = head.cheapest.c === head.dearest.c;
      const name = (s) => (same ? `${s.c} (${storeSub(s)})` : s.c);
      parts.push(' ', h('b', { text: name(head.cheapest) }), dc < 0 ? [' is cheapest at ', h('span', { class: 'cheap', text: `${Math.abs(dc)}% below` }), ' the median; ']
        : ' is cheapest; ', h('b', { text: name(head.dearest) }), dd > 0 ? [' is ', h('span', { class: 'dear', text: `${dd}% above` }), '.'] : ' is the most expensive.');
    }
    clear(finding, parts);
  }

  function drawStats(head, rows) {
    const filteredOut = groupRows().length - rows.length;
    clear(statsCard,
      h('div', {}, h('span', { class: 'stat-label', text: 'Listings' }), h('span', { class: 'stat-big', text: fmt.int(head.listings) }),
        h('span', { class: 'stat-sub', text: [data.source === 'reviewed' && data.removed ? `of ${fmt.int(data.collected)} collected · ${fmt.int(data.removed)} removed by review` : `${fmt.int(data.collected)} collected`,
          filteredOut ? `${fmt.int(filteredOut)} hidden by filters` : ''].filter(Boolean).join(' · ') })),
      h('div', {}, h('span', { class: 'stat-label', text: 'Median price' }), h('span', { class: 'stat-big', style: { color: 'var(--accent)' }, text: fmt.usd(head.median) }),
        h('span', { class: 'stat-sub', text: head.mean !== null ? `mean ${fmt.usd(head.mean)}` : '' })),
      h('div', {}, h('span', { class: 'stat-label', text: 'Cheapest storefront' }), h('span', { class: 'stat-mid', text: head.cheapest ? head.cheapest.c : '–' }),
        h('span', { class: 'stat-sub mono', text: head.cheapest ? `${storeSub(head.cheapest)} · ${fmt.usd(head.cheapest.median_usd)}` : 'needs listings with a price' })),
      h('div', {}, h('span', { class: 'stat-label', text: 'Most expensive' }), h('span', { class: 'stat-mid', text: head.dearest ? head.dearest.c : '–' }),
        h('span', { class: 'stat-sub mono', text: head.dearest ? `${storeSub(head.dearest)} · ${fmt.usd(head.dearest.median_usd)}` : '' })));
  }

  function drawChart(summary, head) {
    const seg = h('div', { class: 'seg small', role: 'group', 'aria-label': 'View' }, [['chart', 'Chart'], ['table', 'Table']].map(([v, l]) => h('button', {
      type: 'button', 'aria-pressed': String(st.view === v), onclick: () => { st.view = v; update(); } }, l)));
    const headRow = h('div', { class: 'card-head' }, h('h2', { class: 'card-title', text: 'Price by storefront' }),
      h('div', { class: 'row' }, st.view === 'chart' ? h('span', { class: 'legend', text: 'Bar: lowest to highest · dot: median · line: overall median' }) : null, seg));
    const priced = summary.filter((s) => s.median_usd !== null);
    if (!priced.length) { clear(chartCard, headRow, h('p', { class: 'muted', text: 'No listings with a price to compare.' })); return; }
    if (st.view === 'table') {
      const cols = [['Storefront', (s) => h('td', {}, h('div', { class: 'pname' }, h('span', { text: s.c }), h('span', { class: 'b mono', text: storeSub(s) })))],
        ['Listings', (s) => h('td', { class: 'num r', text: fmt.int(s.listings) }), 'r'], ['Currency', (s) => h('td', { class: 'num dim', text: s.currency || '–' })],
        ['Min', (s) => h('td', { class: 'num r dim', text: fmt.local(s.min, '') }), 'r'], ['Median', (s) => h('td', { class: 'num r', text: fmt.local(s.median, '') }), 'r'],
        ['Max', (s) => h('td', { class: 'num r dim', text: fmt.local(s.max, '') }), 'r'], ['Min USD', (s) => h('td', { class: 'num r dim', text: fmt.usd(s.min_usd) }), 'r'],
        ['Median USD', (s) => h('td', { class: 'num r', text: fmt.usd(s.median_usd) }), 'r'], ['Mean USD', (s) => h('td', { class: 'num r dim', text: fmt.usd(s.mean_usd) }), 'r'],
        ['Max USD', (s) => h('td', { class: 'num r dim', text: fmt.usd(s.max_usd) }), 'r']];
      clear(chartCard, headRow, h('div', { class: 'table-wrap', style: { margin: '0 -26px -22px' } }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {}, cols.map(([l, , c]) => h('th', { class: c || '', text: l })))),
        h('tbody', {}, summary.map((s) => h('tr', {}, cols.map(([, cell]) => cell(s))))))));
      return;
    }
    const top = niceMax(Math.max(...priced.map((s) => s.max_usd ?? s.median_usd)));
    const pct = (v) => `${Math.max(0, Math.min(100, (v / top) * 100))}%`;
    const med = head.median;
    const rows = priced.map((s) => {
      const d = delta(s.median_usd, med);
      const tip = `${s.c} · ${storeSub(s)}\n${s.with_price} listing(s) with a price\nlowest ${fmt.usd(s.min_usd)} · median ${fmt.usd(s.median_usd)} · highest ${fmt.usd(s.max_usd)}`;
      return h('div', { class: 'chart-row', title: tip },
        h('div', { class: 'chart-label' }, h('b', { text: s.c }), h('span', { text: storeSub(s) })),
        h('div', { class: 'chart-track', role: 'img', 'aria-label': tip.replace(/\n/g, ', ') },
          med !== null ? h('div', { class: 'median-line', style: { left: pct(med) } }) : null,
          h('div', { class: 'range', style: { left: pct(s.min_usd ?? s.median_usd), width: pct((s.max_usd ?? s.median_usd) - (s.min_usd ?? s.median_usd)) } }),
          h('div', { class: 'med', style: { left: pct(s.median_usd) } })),
        h('div', { class: 'chart-val' }, h('span', { class: 'v', text: fmt.usd(s.median_usd) }),
          h('span', { class: `d ${d < 0 ? 'cheap' : d > 0 ? 'dear' : 'muted'}`, text: fmt.pct(d) })));
    });
    clear(chartCard, headRow, h('div', { class: 'chart-rows' }, rows),
      h('div', { class: 'chart-axis' }, h('span'), h('div', { class: 'ticks' }, [0, 1, 2, 3, 4].map((q) => h('span', { text: fmt.usd0((top * q) / 4) }))), h('span')));
  }

  function drawTable(rows) {
    const hasAud = rows.some((r) => r.a);
    const hasConf = rows.some((r) => r.conf !== null);
    const hasSt = rows.some((r) => r.st);
    if (!st.sort) st.sort = hasConf ? { key: 'conf', dir: -1 } : { key: 'usd', dir: 1 };
    const { key, dir } = st.sort;
    const val = (r) => (key === 'n' ? (r.n || '').toLowerCase() : r[key]);
    const sorted = rows.slice().sort((a, b) => {
      const x = val(a); const y = val(b);
      if (x === null || x === undefined) return (y === null || y === undefined) ? 0 : 1;
      if (y === null || y === undefined) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
    const pages = Math.max(1, Math.ceil(sorted.length / PAGE));
    st.page = Math.min(st.page, pages - 1);
    const shown = sorted.slice(st.page * PAGE, (st.page + 1) * PAGE);
    const th = (label, k, cls) => {
      if (!k) return h('th', { class: cls, text: label });
      const active = key === k;
      return h('th', { class: cls, 'aria-sort': active ? (dir > 0 ? 'ascending' : 'descending') : null }, h('button', { type: 'button', onclick: () => {
        st.sort = active ? { key: k, dir: -dir } : { key: k, dir: k === 'conf' ? -1 : 1 }; st.page = 0; update();
      } }, label, active ? (dir > 0 ? ' ↑' : ' ↓') : ''));
    };
    clear(tableCard,
      h('div', { class: 'card-head bar' }, h('h2', { class: 'card-title', text: 'Listings' }), h('span', { class: 'muted small', text: `${fmt.int(sorted.length)} shown` })),
      h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {}, th('Product', 'n'), th('Storefront', 'm'), hasAud ? th('Audience', 'a') : null, th('Local price', null, 'r'),
          th('USD', 'usd', 'r'), hasConf ? th('Confidence', 'conf', 'r') : null, hasSt ? th('Review', 'st') : null)),
        h('tbody', {}, shown.map((r) => {
          const url = safeUrl(r.u);
          return h('tr', {},
            h('td', {}, h('div', { class: 'pname' }, url ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer', title: r.n || '', text: r.n || '(no title)' })
              : h('span', { class: 'ellipsis', title: r.n || '', text: r.n || '(no title)' }), r.b ? h('span', { class: 'b', text: r.b }) : null)),
            h('td', { class: 'store', text: r.m || '–' }), hasAud ? h('td', { class: 'dim', text: fmt.cap(r.a || '–') }) : null,
            h('td', { class: 'num r dim', text: fmt.local(r.v, r.cur) }), h('td', { class: 'num r', text: fmt.usd(r.usd) }),
            hasConf ? h('td', { class: 'num r', text: r.conf === null ? '–' : `${Math.round(r.conf)}%` }) : null,
            hasSt ? h('td', {}, r.st ? h('span', { class: `pill ${REVIEW_TONE[r.st] || ''}`, text: fmt.cap(r.st) }) : '–') : null);
        })))),
      pages > 1 ? h('div', { class: 'pager' }, h('span', { text: `${fmt.int(st.page * PAGE + 1)}–${fmt.int(Math.min(sorted.length, (st.page + 1) * PAGE))} of ${fmt.int(sorted.length)}` }),
        h('div', { class: 'row' },
          h('button', { type: 'button', class: 'btn small', disabled: st.page === 0, onclick: () => { st.page -= 1; update(); tableCard.scrollIntoView({ block: 'start' }); } }, 'Previous'),
          h('button', { type: 'button', class: 'btn small', disabled: st.page >= pages - 1, onclick: () => { st.page += 1; update(); tableCard.scrollIntoView({ block: 'start' }); } }, 'Next'))) : null);
  }

  function reset() { st.f = fresh(); st.page = 0; drawToolbar(); update(); }

  function drawAll() {
    drawBanners();
    drawToolbar();
    update();
  }

  clear(body, banners, finding, toolbar, h('div', { class: 'split narrow' }, chartCard, statsCard), tableCard);
  drawAll();
  const closeMenus = (e) => menus.forEach((m) => { if (m.el.open && !m.el.contains(e.target)) m.el.open = false; });
  document.addEventListener('click', closeMenus);
  return () => document.removeEventListener('click', closeMenus);
}
