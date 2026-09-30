// Settings: defaults for new researches, AI review, clean-up.
import { api, getMeta } from '../api.js';
import { clear, confirmDialog, h, toast } from '../dom.js';

export async function render(view) {
  const [meta, settings, cleanup] = await Promise.all([getMeta(true), api.get('/api/settings'), api.get('/api/cleanup')]);
  const ex = { ...settings.execution };
  const pagesMode = { on: !ex.products_per_storefront };
  const num = (label, key, min, max, step = 1, hint = '') => h('label', { class: 'label' }, label,
    h('input', { class: 'field sm num', type: 'number', min, max, step, value: ex[key] ?? '', style: { width: '160px' },
      onchange: (e) => { const n = Number(e.target.value); if (Number.isFinite(n)) ex[key] = Math.min(max, Math.max(min, n)); } }),
    hint ? h('span', { class: 'hint', text: hint }) : null);
  const sizeBox = h('div', { class: 'stack tight' });
  const drawSize = () => clear(sizeBox,
    h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: pagesMode.on, onchange: (e) => { pagesMode.on = e.target.checked; drawSize(); } }),
      'Use a fixed number of result pages instead of a number of products'),
    pagesMode.on ? num('Pages per query', 'pages', 1, 20) : num('Products per storefront', 'products_per_storefront', 1, 5000, 10,
      'Per storefront and query; the scraper keeps paging (up to 20 pages) until it has this many.'));
  drawSize();
  const delays = ex.delay_seconds || [2.5, 4.5];

  clear(view,
    h('div', { class: 'page-head' }, h('div', { class: 'text' }, h('h1', { class: 'page-title big', text: 'Settings' }))),
    h('div', { class: 'split' },
      h('div', { class: 'stack' },
        h('section', { class: 'card pad stack' },
          h('div', { class: 'stack tight' }, h('h2', { class: 'card-title', text: 'New researches start with' }),
            h('p', { class: 'muted', text: 'Each research can change these in its plan under "Collection settings".' })),
          sizeBox,
          num('Retries on failure', 'retries', 0, 5),
          h('div', { class: 'row' },
            h('label', { class: 'label' }, 'Min pause between pages (s)', h('input', { class: 'field sm num', type: 'number', min: 0.5, max: 60, step: 0.5, value: delays[0], style: { width: '160px' },
              onchange: (e) => { delays[0] = Math.max(0.5, Number(e.target.value) || 2.5); } })),
            h('label', { class: 'label' }, 'Max pause between pages (s)', h('input', { class: 'field sm num', type: 'number', min: 0.5, max: 60, step: 0.5, value: delays[1], style: { width: '160px' },
              onchange: (e) => { delays[1] = Math.max(0.5, Number(e.target.value) || 4.5); } }))),
          h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!ex.headless, onchange: (e) => { ex.headless = e.target.checked; } }), 'Hide the browser window'),
          h('span', { class: 'hint', text: 'Visible browsers are blocked less often by bot checks.' }),
          h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!ex.enrich_details, onchange: (e) => { ex.enrich_details = e.target.checked; } }),
            'Open product pages for extra details (Zalando, MediaMarkt)'),
          num('Max product pages per storefront', 'max_detail_products', 1, 10000),
          h('div', {}, h('button', { type: 'button', class: 'btn primary', onclick: async () => {
            const execution = { ...ex, delay_seconds: [Math.min(delays[0], delays[1]), Math.max(delays[0], delays[1])] };
            if (pagesMode.on) delete execution.products_per_storefront; else execution.products_per_storefront = execution.products_per_storefront || 100;
            try { await api.put('/api/settings', { execution }); await getMeta(true); toast('Settings saved.'); } catch (err) { toast(err.message, 'bad'); }
          } }, 'Save'))),
        h('section', { class: 'card pad stack tight' },
          h('h2', { class: 'card-title', text: 'AI relevance review' }),
          meta.claude_api
            ? h('p', {}, h('span', { class: 'pill ok', text: 'Claude API key found' }), ' Reviews can run automatically, several batches at once.')
            : h('div', { class: 'stack tight' }, h('p', {}, h('span', { class: 'pill', text: 'No API key' }), ' You can still review with any AI chat by copy and paste.'),
              h('p', { class: 'hint', text: 'To review automatically, set an ANTHROPIC_API_KEY environment variable (Windows: open "Edit environment variables for your account"), then restart the app. PI_REVIEW_MODEL chooses the model.' }))),
        h('section', { class: 'card pad stack tight' },
          h('h2', { class: 'card-title', text: 'Clean up' }),
          cleanup.runs.length
            ? [h('p', { text: `${cleanup.runs.length} failed or empty run(s) take up space and have nothing to show.` }),
              h('div', {}, h('button', { type: 'button', class: 'btn danger', onclick: async () => {
                if (!(await confirmDialog('Delete failed and empty runs?', `${cleanup.runs.length} run folder(s) are deleted: ${cleanup.runs.slice(0, 6).join(', ')}${cleanup.runs.length > 6 ? '…' : ''}`))) return;
                try {
                  const res = await api.post('/api/cleanup');
                  toast(`Deleted ${res.removed.length} run(s).${res.locked.length ? ` ${res.locked.length} are in use by another program (OneDrive, Excel?) and were left.` : ''}`);
                  render(view);
                } catch (err) { toast(err.message, 'bad'); }
              } }, 'Delete them'))]
            : h('p', { class: 'muted', text: 'Nothing to clean up.' }))),
      h('aside', { class: 'card pad stack tight' },
        h('h2', { class: 'card-title', text: 'Where your data lives' }),
        h('p', { class: 'mono small', style: { overflowWrap: 'anywhere' }, text: meta.output_dir }),
        h('p', { class: 'hint', text: 'Every research is a folder here with its listings, reports and review. Drafts are in the "drafts" folder.' }),
        h('p', { class: 'hint', text: `Price Lens ${meta.version || ''}` }))));
  return null;
}
