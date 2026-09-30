// A storefront check: one page per storefront, before a big run.
import { api, enc } from '../api.js';
import { clear, h, icon } from '../dom.js';
import { liveView } from './collect.js';
import { checkTable } from './shared.js';

export async function render(view, id, draftId) {
  view.classList.add('wide');
  const body = h('div', { class: 'stack' });
  const back = draftId ? h('a', { class: 'btn primary', href: `#/draft/${draftId}` }, icon('back'), 'Back to the plan') : null;
  clear(view,
    h('nav', { class: 'crumbs', 'aria-label': 'Breadcrumb' }, h('a', { href: '#/storefronts' }, 'Storefront health'), h('span', { 'aria-hidden': 'true', text: '/' }),
      h('span', { text: 'Storefront check' })),
    h('div', { class: 'page-head' },
      h('div', { class: 'text' }, h('h1', { class: 'page-title', text: 'Storefront check' }),
        h('p', { class: 'page-sub', text: 'Opens one result page per storefront to spot cookie walls, redirects and bot checks before a big run.' })),
      h('div', { class: 'actions' }, back)),
    body);

  const finished = (live) => {
    const rows = live.table || [];
    const ok = rows.filter((r) => ['OK', 'Partial'].includes(r.result)).length;
    clear(body,
      h('p', { class: 'finding' }, h('b', { text: `${ok} of ${rows.length}` }), ' storefronts work.',
        ok < rows.length ? ' Leave out the others on the plan, or try them later.' : ' You are ready to collect.'),
      checkTable(rows, 'Result per storefront'));
  };
  const live = await api.get(`/api/runs/${enc(id)}/live`);
  if (live.active) return liveView(body, id, { onFinished: finished, stopLabel: 'Stop the check' });
  finished(live);
  return null;
}
