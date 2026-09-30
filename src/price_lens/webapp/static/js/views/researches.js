// Home: every research (run or draft), newest first, plus storefront health.
import { api } from '../api.js';
import { clear, fmt, h, icon, platformName, STATUS_PILL, toast } from '../dom.js';
import { importPlanDialog } from './shared.js';

const TABS = [['all', 'All'], ['running', 'Running'], ['paused', 'Paused'], ['attention', 'Needs attention'], ['draft', 'Drafts']];

export async function render(view) {
  const state = { tab: 'all', q: '' };
  let data = await api.get('/api/researches');
  const list = h('section', { class: 'card', 'aria-label': 'Research list', style: { overflow: 'hidden' } });
  const tabs = h('div', { class: 'tabs', role: 'tablist', 'aria-label': 'Filter researches' });
  const health = h('section', { class: 'grid-3', 'aria-label': 'Storefront health' });
  const notice = h('div');

  async function importPlan() {
    const plan = await importPlanDialog();
    if (!plan) return;
    const draft = await api.post('/api/drafts', { plan });
    location.hash = `#/draft/${draft.id}`;
  }

  clear(view,
    h('div', { class: 'page-head' },
      h('div', { class: 'text' }, h('h1', { class: 'page-title big', text: 'Researches' }),
        h('p', { class: 'page-sub', text: 'Price research across Amazon, eBay, Zalando and MediaMarkt.' })),
      h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'btn', onclick: () => importPlan().catch((e) => toast(e.message, 'bad')) }, 'Import plan'),
        h('a', { class: 'btn primary', href: '#/new' }, icon('plus'), 'New research'))),
    h('div', { class: 'tabbar' }, tabs,
      h('label', { class: 'search-box', style: { width: '280px', marginBottom: '6px' } }, icon('search', 15),
        h('input', { type: 'search', placeholder: 'Search researches', 'aria-label': 'Search researches',
          oninput: (e) => { state.q = e.target.value.toLowerCase(); draw(); } }))),
    notice, list, health);

  function matches(item) {
    if (state.tab !== 'all' && item.status !== state.tab) return false;
    return !state.q || item.title.toLowerCase().includes(state.q);
  }

  function spread(item) {
    if (item.median === null || item.lo === null) return h('div', { class: 'spread' });
    const top = item.hi * 1.1 || 1;
    const pct = (v) => `${Math.max(0, Math.min(100, (v / top) * 100))}%`;
    return h('div', { class: 'spread', title: `Middle 90% of prices: ${fmt.usd(item.lo)} to ${fmt.usd(item.hi)}` },
      h('div', { class: 'base' }),
      h('div', { class: 'range', style: { left: pct(item.lo), width: pct(item.hi - item.lo) } }),
      h('div', { class: 'med', style: { left: pct(item.median) } }));
  }

  function href(item) {
    if (item.kind === 'draft') return `#/draft/${item.id}`;
    if (item.status === 'running' || item.status === 'paused') return `#/r/${item.id}/collect`;
    return `#/r/${item.id}`;
  }

  function draw() {
    const counts = Object.fromEntries(TABS.map(([k]) => [k, k === 'all' ? data.items.length : data.items.filter((i) => i.status === k).length]));
    clear(tabs, TABS.map(([key, label]) => h('button', {
      type: 'button', role: 'tab', 'aria-selected': String(state.tab === key),
      onclick: () => { state.tab = key; draw(); },
    }, label, h('span', { class: 'count', text: counts[key] }))));
    const items = data.items.filter(matches);
    if (!data.items.length) {
      clear(list, h('div', { class: 'empty' }, h('h2', { text: 'No researches yet' }),
        h('p', { text: 'Start one to compare prices across storefronts and countries.' }),
        h('a', { class: 'btn primary', href: '#/new' }, icon('plus'), 'New research')));
      return;
    }
    clear(list,
      h('div', { class: 'rlist-head' }, h('span', { text: 'RESEARCH' }), h('span', { text: 'STATUS' }),
        h('span', { class: 'r', style: { textAlign: 'right' }, text: 'LISTINGS' }), h('span', { style: { textAlign: 'right' }, text: 'MEDIAN' }),
        h('span', { text: 'PRICE SPREAD (USD)' }), h('span', { style: { textAlign: 'right' }, text: 'UPDATED' })),
      items.length ? items.map((item) => h('a', { class: 'rlist-row', href: href(item) },
        h('div', { style: { display: 'flex', flexDirection: 'column', gap: '4px', minWidth: 0 } },
          h('span', { class: 'rlist-title', text: item.title }),
          h('span', { class: 'rlist-meta', text: [item.platforms.map(platformName).join(', '), item.countries ? `${item.countries} ${item.countries === 1 ? 'country' : 'countries'}` : '',
            item.storefronts ? `${item.storefronts} ${item.storefronts === 1 ? 'storefront' : 'storefronts'}` : 'no storefronts yet',
            item.left ? (item.searches_total > 1 ? `${fmt.int(item.left)} storefront searches left` : `${fmt.int(item.left)} left to collect`) : ''].filter(Boolean).join(' · ') })),
        h('span', { style: { justifySelf: 'start' } }, h('span', { class: `pill ${STATUS_PILL[item.status] || ''}`, text: item.label })),
        h('span', { class: 'mono', style: { textAlign: 'right' }, text: item.listings === null ? '–' : fmt.int(item.listings) }),
        h('span', { class: 'mono', style: { textAlign: 'right' }, text: fmt.usd(item.median) }),
        spread(item),
        h('span', { class: 'muted small', style: { textAlign: 'right' }, text: item.status === 'running' ? 'Now' : fmt.when(item.updated) })))
        : h('p', { class: 'loading', text: 'Nothing matches.' }));
  }

  async function drawHealth() {
    try {
      const [sf, cleanup] = await Promise.all([api.get('/api/storefronts'), api.get('/api/cleanup')]);
      const bad = sf.storefronts.filter((s) => !['OK', 'Partial'].includes(s.result)).slice(0, 3);
      const lastCheck = sf.checks[0];
      clear(health,
        h('div', { class: 'card pad stack tight' }, h('span', { class: 'muted', text: 'Storefronts working' }),
          h('span', { class: 'stat-big' }, sf.total ? `${sf.working} ` : '–', sf.total ? h('span', { class: 'muted', style: { fontSize: '18px' }, text: `of ${sf.total}` }) : null),
          h('span', { class: 'muted', text: sf.total ? 'From your runs and storefront checks' : 'Known after your first run or check' })),
        h('div', { class: 'card pad stack tight' }, h('span', { class: 'muted', text: 'Need attention' }),
          bad.length ? bad.map((s) => h('span', { class: 'row', style: { justifyContent: 'space-between' } },
            h('span', { class: 'mono small', text: s.storefront }), h('span', { class: s.result === 'Network' ? 'muted' : 'dear', style: { color: 'var(--bad-fg)' }, text: s.result })))
            : h('span', { class: 'muted', text: 'Nothing right now.' }),
          h('a', { class: 'link', href: '#/storefronts' }, 'All storefronts')),
        h('div', { class: 'card pad stack tight', style: { justifyContent: 'space-between' } },
          h('span', { class: 'muted', text: 'Last storefront check' }),
          h('span', { style: { fontSize: '15px' }, text: lastCheck ? `${fmt.when(lastCheck.started)} · ${lastCheck.ok} of ${lastCheck.total} OK` : 'None yet' }),
          h('span', { class: 'hint', text: 'Checks start from a research plan ("Test storefronts first").' })));
      clear(notice, cleanup.runs.length ? h('div', { class: 'banner info' }, h('span', { class: 'grow',
        text: `${cleanup.runs.length} failed or empty run(s) can be cleaned up.` }), h('a', { class: 'link', href: '#/settings' }, 'Clean up')) : null);
    } catch (err) {
      clear(health);
    }
  }

  draw();
  drawHealth();
  const timer = setInterval(async () => {
    if (!data.active.length) return;
    try { data = await api.get('/api/researches'); draw(); } catch (e) { /* ignore */ }
  }, 5000);
  return () => clearInterval(timer);
}
