// Storefront health: how each storefront did the last time it was used.
import { api } from '../api.js';
import { clear, fmt, h, platformName } from '../dom.js';

const TONE = { OK: 'ok', Partial: 'warn', Network: '' };

export async function render(view) {
  const data = await api.get('/api/storefronts');
  const q = { text: '' };
  const table = h('section', { class: 'card', style: { overflow: 'hidden' } });
  function link(run) {
    if (!run) return '–';
    return h('a', { class: 'mono small', href: run.startsWith('check_') ? `#/check/${run}` : run.startsWith('analyst_') ? `#/r/${run}` : '#/' }, run);
  }
  function draw() {
    const rows = data.storefronts.filter((r) => !q.text || r.storefront.includes(q.text) || (r.platform || '').includes(q.text));
    clear(table, h('div', { class: 'card-head bar' }, h('h2', { class: 'card-title', text: 'Storefronts' }),
      h('input', { class: 'field sm', type: 'search', placeholder: 'Find a storefront', 'aria-label': 'Find a storefront', style: { width: '240px' }, value: q.text,
        oninput: (e) => { q.text = e.target.value.toLowerCase(); draw(); } })),
    rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
      h('thead', {}, h('tr', {}, ['Storefront', 'Platform', 'Result', 'Details', 'Last seen', 'Run'].map((t) => h('th', { text: t })))),
      h('tbody', {}, rows.map((r) => h('tr', {},
        h('td', { class: 'store', text: r.storefront }), h('td', { text: platformName(r.platform) }),
        h('td', {}, h('span', { class: `pill ${TONE[r.result] ?? 'bad'}`, text: r.result })),
        h('td', { class: 'dim small', style: { maxWidth: '460px' } }, h('span', { class: 'ellipsis', title: r.problem || '', text: r.problem || '' })),
        h('td', { class: 'dim small nowrap', text: fmt.date(r.when) }), h('td', {}, link(r.run)))))))
      : h('div', { class: 'empty' }, h('h2', { text: 'Nothing known yet' }), h('p', { text: 'Storefronts appear here after a collection or a storefront check.' })));
  }
  clear(view,
    h('div', { class: 'page-head' }, h('div', { class: 'text' }, h('h1', { class: 'page-title big', text: 'Storefront health' }),
      h('p', { class: 'page-sub', text: 'How each storefront did the last time a collection or check used it. Connection problems on your side are not counted.' }))),
    h('div', { class: 'grid-3' },
      h('div', { class: 'card pad stack tight' }, h('span', { class: 'muted', text: 'Working' }), h('span', { class: 'stat-big', text: `${data.working} of ${data.total}` })),
      h('div', { class: 'card pad stack tight' }, h('span', { class: 'muted', text: 'Need attention' }), h('span', { class: 'stat-big', style: { color: 'var(--bad-fg)' }, text: String(data.total - data.working) })),
      h('div', { class: 'card pad stack tight' }, h('span', { class: 'muted', text: 'Recent checks' }),
        data.checks.length ? data.checks.slice(0, 4).map((c) => h('a', { class: 'row', href: `#/check/${c.id}`, style: { justifyContent: 'space-between', textDecoration: 'none', color: 'var(--ink)' } },
          h('span', { text: fmt.when(c.started) }), h('span', { class: 'mono small', text: c.total ? `${c.ok} of ${c.total} OK` : c.status })))
          : h('span', { class: 'hint', text: 'Start one from a research plan: "Test the storefronts first".' }))),
    table);
  draw();
  return null;
}
