// One research: header, the five steps, and the step that is open.
import { api, enc } from '../api.js';
import { clear, confirmDialog, fmt, h, icon, platformName, STATUS_PILL, stepsNav, toast } from '../dom.js';
import { renderCollect } from './collect.js';
import { checkTable } from './shared.js';
import { renderResults } from './results.js';
import { renderReview } from './review.js';
import { repriceDialog } from './rates.js';

const FILE_LABELS = {
  'final_products.csv': 'All collected listings (CSV)', 'detailed_products.csv': 'Listings with all details (CSV)',
  'raw_products.csv': 'Raw listings before cleaning (CSV)', 'analyst_plan.json': 'Plan (JSON)', 'log.txt': 'Full log (text)',
  'ai_review/final_products.csv': 'Reviewed listings (CSV)', 'ai_review/final_products.xlsx': 'Reviewed listings (Excel)',
  'ai_review/ai_classified_products.csv': 'Review audit with reasons (CSV)',
};

export async function render(view, id, tab) {
  let detail = await api.get(`/api/runs/${enc(id)}`);
  if (!tab) {
    tab = detail.status === 'running' || detail.status === 'paused' || detail.active_retry ? 'collect' : detail.collected ? 'results' : 'collect';
    location.replace(`#/r/${id}/${tab}`);
    return null;
  }
  view.classList.add('wide');
  const stepsSlot = h('div');
  const actions = h('div', { class: 'actions' });
  const body = h('div', { class: 'stack', style: { gap: '24px' } });
  const statusPill = h('span');
  let stepCleanup = null;

  async function refresh() {
    try {
      detail = await api.get(`/api/runs/${enc(id)}`);
      drawSteps();
    } catch (err) { /* keep what is shown */ }
    return detail;
  }

  function drawSteps() {
    clear(stepsSlot, stepsNav(detail.steps, `#/r/${id}`, tab));
    clear(statusPill, h('span', { class: `pill ${STATUS_PILL[detail.status] || ''}`, text: detail.label }));
  }

  const summary = detail.summary;
  const metaLine = [
    summary.platforms.map(platformName).join(', '),
    summary.countries ? `${summary.countries} ${summary.countries === 1 ? 'country' : 'countries'}` : '',
    detail.job.started_at ? `collected ${fmt.date(detail.job.started_at)}` : '',
    detail.fx,
  ].filter(Boolean).join(' · ');

  const more = h('details', { class: 'pop-anchor' },
    h('summary', { class: 'btn', 'aria-label': 'More actions', style: { listStyle: 'none' } }, icon('more')),
    h('div', { class: 'popover', style: { right: 0, width: '290px' } },
      h('button', { type: 'button', class: 'btn ghost block', style: { justifyContent: 'flex-start' }, onclick: async () => {
        try {
          const draft = await api.post('/api/drafts', { from_run: id });
          location.hash = `#/draft/${draft.id}`;
        } catch (err) { toast(err.message, 'bad'); }
      } }, icon('refresh'), 'Run again as a new research'),
      detail.collected && !detail.active ? h('button', { type: 'button', class: 'btn ghost block', style: { justifyContent: 'flex-start' }, onclick: () => {
        more.open = false;
        repriceDialog(id, () => window.dispatchEvent(new HashChangeEvent('hashchange')));
      } }, icon('swap'), 'Update USD prices') : null,
      h('hr', { class: 'divider', style: { margin: '6px 0' } }),
      h('span', { class: 'muted small', style: { padding: '4px 8px' }, text: 'Download' }),
      detail.files.map((f) => h('button', { type: 'button', class: 'btn ghost block small', style: { justifyContent: 'flex-start' },
        onclick: () => api.file('GET', `/api/runs/${enc(id)}/files?file=${enc(f)}`).catch((e) => toast(e.message, 'bad')) },
      icon('download', 14), FILE_LABELS[f] || f)),
      h('hr', { class: 'divider', style: { margin: '6px 0' } }),
      h('button', { type: 'button', class: 'btn ghost block danger', style: { justifyContent: 'flex-start' }, onclick: async () => {
        if (!(await confirmDialog('Delete this research?', 'Its folder with every collected listing, the review and the reports is deleted. This cannot be undone.'))) return;
        try {
          await api.del(`/api/runs/${enc(id)}`);
          toast('Research deleted.');
          location.hash = '#/';
        } catch (err) { toast(err.message, 'bad'); }
      } }, icon('x'), 'Delete research')));
  const closeMore = (e) => { if (more.open && !more.contains(e.target)) more.open = false; };
  document.addEventListener('click', closeMore);

  clear(view,
    h('nav', { class: 'crumbs', 'aria-label': 'Breadcrumb' }, h('a', { href: '#/' }, 'Researches'), h('span', { 'aria-hidden': 'true', text: '/' }),
      h('span', { text: detail.title })),
    h('div', { class: 'page-head' },
      h('div', { class: 'text' },
        h('h1', { class: 'page-title', text: detail.title }),
        h('div', { class: 'row', style: { gap: '10px' } }, statusPill, h('p', { class: 'page-sub', text: metaLine }))),
      h('div', { class: 'actions' }, actions, more)),
    stepsSlot, body);
  drawSteps();

  const ctx = { id, detail: () => detail, refresh, actions, go: (t) => { location.hash = `#/r/${id}/${t}`; } };
  if (tab === 'plan') stepCleanup = planStep(body, detail, id);
  else if (tab === 'check') stepCleanup = await checkStep(body, detail);
  else if (tab === 'collect') stepCleanup = await renderCollect(body, ctx);
  else if (tab === 'review') stepCleanup = await renderReview(body, ctx);
  else if (tab === 'results') stepCleanup = await renderResults(body, ctx);
  else location.replace(`#/r/${id}`);

  const timer = setInterval(() => { if (detail.active || detail.active_retry) refresh(); }, 5000);
  return () => {
    clearInterval(timer);
    document.removeEventListener('click', closeMore);
    if (typeof stepCleanup === 'function') stepCleanup();
  };
}

// ---- Plan (read only) --------------------------------------------------------------------------
function planStep(body, detail, id) {
  const plan = detail.plan || {};
  const ex = plan.execution || {};
  const line = (label, value) => h('div', { style: { display: 'grid', gridTemplateColumns: '170px minmax(0, 1fr)', gap: '14px', padding: '8px 0',
    borderBottom: '1px solid var(--line-row)' } }, h('span', { class: 'muted', text: label }), h('span', {}, value || '–'));
  clear(body,
    detail.goal ? h('p', { class: 'finding', text: detail.goal }) : null,
    h('div', { class: 'row', style: { justifyContent: 'space-between' } },
      h('p', { class: 'muted', text: 'This is the plan the research ran with. To change it, run it again as a new research.' }),
      h('button', { type: 'button', class: 'btn', onclick: async () => {
        const draft = await api.post('/api/drafts', { from_run: id });
        location.hash = `#/draft/${draft.id}`;
      } }, icon('refresh'), 'Run again as a new research')),
    (plan.searches || []).map((s, i) => {
      const q = s.query || {};
      const f = q.filters || {};
      const translations = Object.entries(q.translations || {}).map(([lang, v]) => `${lang}: ${typeof v === 'object' ? v.search_term : v}`);
      return h('section', { class: 'card pad' },
        h('h2', { class: 'card-title', style: { marginBottom: '10px' }, text: `Search ${i + 1} · ${s.product_type || q.default || ''}` }),
        line('Search for', q.default),
        line('Other languages', translations.join(' · ')),
        line('Where', (s.targets || []).map((t) => `${platformName(t.platform)}: ${(t.countries || []).map((c) => (c === 'all' ? 'all countries' : c)).join(', ')}`).join(' · ')),
        line('Audiences', (s.audiences || []).map(fmt.cap).join(', ')),
        line('Left out', (f.exclude || []).join(', ')),
        line('Must mention', (f.include || []).join(', ')),
        line('Price (USD)', f.min_price || f.max_price ? `${f.min_price || 0} to ${f.max_price || 'no limit'}` : ''));
    }),
    h('section', { class: 'card pad' }, h('h2', { class: 'card-title', style: { marginBottom: '10px' }, text: 'Collection settings' }),
      line('Size', ex.products_per_storefront ? `${ex.products_per_storefront} products per storefront` : `${ex.pages || 1} page(s) per query`),
      line('Retries', String(ex.retries ?? '')),
      line('Pause between pages', ex.delay_seconds ? `${ex.delay_seconds[0]} to ${ex.delay_seconds[1]} s` : ''),
      line('Browser window', ex.headless ? 'Hidden' : 'Visible'),
      line('Product pages', ex.enrich_details ? `Opened for details (max ${ex.max_detail_products})` : 'Not opened')));
  return null;
}

// ---- Storefront check --------------------------------------------------------------------------
async function checkStep(body, detail) {
  if (!detail.checks.length) {
    clear(body, h('section', { class: 'card' }, h('div', { class: 'empty' }, h('h2', { text: 'No storefront check for this research' }),
      h('p', { text: 'Checks are optional. They open one page per storefront before a big run, to spot cookie walls, redirects and bot checks.' }),
      h('a', { class: 'btn', href: '#/storefronts' }, 'Storefront health'))));
    return null;
  }
  const name = detail.checks[detail.checks.length - 1];
  const live = await api.get(`/api/runs/${enc(name)}/live`);
  clear(body, checkTable(live.table || [], `Storefront check${live.started ? ` · started ${live.started}` : ''}`));
  return null;
}
