// Review step: an AI checks each listing against the goal; you can change any decision.
import { api, enc } from '../api.js';
import { banner, clear, confirmDialog, copyText, fmt, h, icon, safeUrl, toast } from '../dom.js';

const PAGE = 50;
const FILTERS = [['attention', 'Unsure + leave out'], ['all', 'All'], ['accepted', 'Keep'], ['uncertain', 'Unsure'],
  ['excluded', 'Leave out'], ['pending', 'Not reviewed'], ['changed', 'Changed by you']];

export async function renderReview(body, ctx) {
  const id = ctx.id;
  let state = await api.get(`/api/runs/${enc(id)}/review`);
  let decisions = [];
  const ui = { filter: 'attention', page: 0, q: '', mode: 'all', batch: null, promptBatches: null };
  let poll = null;

  async function reload({ withDecisions = true } = {}) {
    state = await api.get(`/api/runs/${enc(id)}/review`);
    if (withDecisions && state.prepared) decisions = (await api.get(`/api/runs/${enc(id)}/review/decisions`)).rows;
    draw();
    ctx.refresh();
  }

  function headerActions() {
    const ready = state.prepared && state.progress && !state.progress.pending.length;
    clear(ctx.actions,
      state.prepared ? h('button', { type: 'button', class: 'btn', onclick: async () => {
        if (!(await confirmDialog('Start the review over?', 'All review decisions for this research are deleted, including the ones you changed.', 'Start over'))) return;
        try { await api.post(`/api/runs/${enc(id)}/review/reset`); decisions = []; await reload(); toast('Review deleted.'); } catch (err) { toast(err.message, 'bad'); }
      } }, 'Start over') : null,
      ready && !state.applied ? h('button', { type: 'button', class: 'btn primary', onclick: apply }, 'Apply and see results') : null,
      state.applied ? h('a', { class: 'btn primary', href: `#/r/${id}/results` }, 'See results') : null);
  }

  async function apply() {
    try {
      await api.post(`/api/runs/${enc(id)}/review/apply`);
      toast('Review applied.');
      await ctx.refresh();
      location.hash = `#/r/${id}/results`;
    } catch (err) { toast(err.message, 'bad'); }
  }

  // ---- not prepared yet ----------------------------------------------------------------------------
  function drawStart() {
    const instruction = h('textarea', { id: 'keep', class: 'field', rows: 3, value: state.default_instruction });
    const batch = h('input', { class: 'field sm num', type: 'number', min: 1, max: 500, value: state.batch_size, style: { width: '110px' } });
    const conf = h('input', { type: 'range', min: '50', max: '100', step: '5', value: '80', style: { accentColor: 'var(--accent)', width: '220px' } });
    const confOut = h('output', { class: 'mono', text: '80%' });
    conf.addEventListener('input', () => { confOut.textContent = `${conf.value}%`; });
    const brands = h('input', { class: 'field sm', placeholder: 'e.g. Nike, Adidas (optional)' });
    async function prepare(then) {
      try {
        state = await api.post(`/api/runs/${enc(id)}/review/prepare`, { instruction: instruction.value, batch_size: Number(batch.value),
          min_confidence: Number(conf.value) / 100, brands: brands.value });
        if (then === 'claude') await startClaude();
        else ui.mode = 'all';
        await reload();
      } catch (err) { toast(err.message, 'bad'); }
    }
    clear(body,
      h('p', { class: 'finding' }, 'An AI checks each of the ', h('b', { text: fmt.int(state.listings) }), ' collected listings against your goal and removes accessories and unrelated products.'),
      h('div', { class: 'split' },
        h('section', { class: 'card pad stack', 'aria-label': 'Instructions' },
          h('label', { for: 'keep', class: 'card-title', text: 'What should be kept?' }), instruction,
          h('details', { class: 'adv' }, h('summary', {}, 'Review settings'),
            h('div', { class: 'body' },
              h('label', { class: 'label' }, 'Listings per batch', batch, h('span', { class: 'hint', text: '~150 works reliably when pasting into a chat; ~100 lets the Claude API run several batches at once.' })),
              h('div', { class: 'label' }, h('span', { class: 'row', style: { justifyContent: 'space-between', width: '300px' } }, 'Minimum confidence to keep without flagging', confOut), conf),
              h('label', { class: 'label' }, 'Only these brands', brands))),
          h('div', { class: 'grid-2' },
            h('div', { class: `choice ${state.api ? 'on' : ''}` }, h('span', { class: 'choice-title', text: 'Review with Claude' }),
              h('span', { class: 'hint', text: state.api ? 'Automatic, several batches at once, using your API key.' : 'Needs an ANTHROPIC_API_KEY environment variable. Set it, then restart the app.' }),
              h('button', { type: 'button', class: 'btn primary small', disabled: !state.api, onclick: () => prepare('claude'), style: { alignSelf: 'flex-start' } }, 'Start review')),
            h('div', { class: `choice ${state.api ? '' : 'on'}` }, h('span', { class: 'choice-title', text: 'Use any AI chat' }),
              h('span', { class: 'hint', text: 'Copy a prompt into ChatGPT, Gemini or Claude, then paste the answer back here.' }),
              h('button', { type: 'button', class: `btn small ${state.api ? '' : 'primary'}`, onclick: () => prepare('chat'), style: { alignSelf: 'flex-start' } }, 'Prepare prompts')))),
        h('aside', { class: 'card pad stack tight' }, h('h2', { class: 'card-title', text: `${fmt.int(state.listings)} listings to check` }),
          h('p', { class: 'muted', text: 'Listings the AI is unsure about stay in the results, marked "unsure". Nothing is removed until you apply the review.' }))));
  }

  // ---- prepared --------------------------------------------------------------------------------------
  async function startClaude() {
    try {
      await api.post(`/api/runs/${enc(id)}/review/claude`);
      pollClaude();
    } catch (err) { toast(err.message, 'bad'); }
  }
  function pollClaude() {
    clearInterval(poll);
    poll = setInterval(async () => {
      const fresh = await api.get(`/api/runs/${enc(id)}/review`).catch(() => null);
      if (!fresh) return;
      state = fresh;
      if (!state.claude || !state.claude.running) {
        clearInterval(poll);
        await reload();
        toast(state.claude && state.claude.error ? `Claude review: ${state.claude.error}` : 'Claude has reviewed every listing.', state.claude && state.claude.error ? 'bad' : '');
      } else drawWork();
    }, 2000);
  }

  const workBox = h('div', { class: 'stack' });
  const summaryBox = h('aside', { class: 'card pad stack', 'aria-label': 'Review summary' });
  const decisionsBox = h('section', { class: 'card', 'aria-label': 'Decisions', style: { overflow: 'hidden' } });

  function drawWork() {
    const p = state.progress;
    const claude = state.claude;
    const pending = p.pending.length;
    const items = [];
    if (state.outdated) {
      items.push(banner('warn', `${state.outdated.added} listing(s) were added by a retry after this review. `,
        h('button', { type: 'button', class: 'link', onclick: async () => {
          try { const r = await api.post(`/api/runs/${enc(id)}/review/extend`); toast(`Added ${r.added} listing(s) to the review.`); await reload(); } catch (err) { toast(err.message, 'bad'); }
        } }, `Add them to the review`)));
    }
    if (state.applied && !pending) {
      const a = state.applied;
      items.push(banner('ok', h('span', {}, h('b', { text: 'Review applied. ' }), `${fmt.int(a.accepted)} kept, ${fmt.int(a.uncertain)} unsure (kept), ${fmt.int(a.excluded)} left out. Changes you make below apply right away.`)));
    } else if (!pending) {
      items.push(banner('ok', h('span', { class: 'grow' }, h('b', { text: 'Every listing is reviewed. ' }), 'Check the decisions below, then apply the review.'),
        h('button', { type: 'button', class: 'btn primary small', onclick: apply }, 'Apply review')));
    }
    if (pending) {
      items.push(h('div', { class: 'stack tight' },
        h('div', { class: 'row', style: { justifyContent: 'space-between' } },
          h('span', { class: 'section-title', text: `${p.done} of ${p.total} batches reviewed · ${fmt.int(p.remaining)} listings left` })),
        h('div', { class: 'progress', role: 'progressbar', 'aria-valuenow': String(Math.round((100 * p.done) / Math.max(1, p.total))), 'aria-valuemin': '0', 'aria-valuemax': '100' },
          h('div', { style: { width: `${(100 * p.done) / Math.max(1, p.total)}%` } }))));
      const running = claude && claude.running;
      const claudeCard = h('div', { class: `choice ${state.api ? 'on' : ''}` }, h('span', { class: 'choice-title', text: 'Review with Claude' }),
        running ? h('span', { class: 'hint', text: 'Working… you can leave this page; it keeps going while the app is open.' })
          : h('span', { class: 'hint', text: state.api ? `Sends the ${pending} open batch(es), several at once.` : 'Needs an ANTHROPIC_API_KEY environment variable. Set it, then restart the app.' }),
        running ? h('ol', { class: 'activity', style: { padding: '0', maxHeight: '180px' } }, (claude.log || []).slice(-6).map((m) => h('li', { class: 'plain' }, h('span', { class: 'd' }), h('span', { text: m }))))
          : h('button', { type: 'button', class: 'btn primary small', disabled: !state.api, style: { alignSelf: 'flex-start' }, onclick: startClaude }, `Review ${fmt.int(p.remaining)} listings`));
      items.push(h('div', { class: 'grid-2', style: { alignItems: 'start' } }, claudeCard, chatCard(p)));
    }
    clear(workBox, items);
  }

  function chatCard(p) {
    const note = h('span', { class: 'hint' });
    const promptBox = h('div', { class: 'prompt-box', hidden: true });
    const answer = h('textarea', { class: 'field mono', rows: 5, placeholder: 'p001|keep|0.95|running shoe|complete shoe', 'aria-label': "The AI's answer", style: { fontSize: '12px' } });
    const batchSel = h('select', { class: 'field sm', 'aria-label': 'Batch', onchange: (e) => { ui.batch = e.target.value; ui.promptBatches = null; } },
      p.pending.map((b) => h('option', { value: b, selected: b === ui.batch }, b.replace(/_/g, ' '))));
    if (!p.pending.includes(ui.batch)) ui.batch = p.pending[0];
    const fetchPrompt = async () => {
      const res = await api.get(`/api/runs/${enc(id)}/review/prompt${ui.mode === 'one' ? `?batch=${enc(ui.batch)}` : ''}`);
      ui.promptBatches = res.batches;
      return res;
    };
    return h('div', { class: 'choice' }, h('span', { class: 'choice-title', text: 'Use any AI chat' }),
      h('div', { class: 'seg small', role: 'group', 'aria-label': 'What to copy' }, [['all', 'Everything left in one prompt'], ['one', 'One batch at a time']].map(([v, l]) => h('button', {
        type: 'button', 'aria-pressed': String(ui.mode === v), onclick: () => { ui.mode = v; ui.promptBatches = null; drawWork(); } }, l))),
      ui.mode === 'one' ? batchSel : null,
      h('div', { class: 'row' },
        h('button', { type: 'button', class: 'btn small', onclick: async () => {
          try {
            const res = await fetchPrompt();
            const ok = await copyText(res.prompt);
            note.textContent = ok ? `Copied ${res.count} listings. Paste into your AI chat (Ctrl+V).` : 'Copy was blocked; use "Show prompt".';
          } catch (err) { note.textContent = err.message; }
        } }, icon('copy', 14), '1. Copy prompt'),
        h('button', { type: 'button', class: 'link', onclick: async () => {
          if (!promptBox.hidden) { promptBox.hidden = true; return; }
          try { promptBox.textContent = (await fetchPrompt()).prompt; promptBox.hidden = false; } catch (err) { note.textContent = err.message; }
        } }, 'Show prompt')),
      note, promptBox,
      h('label', { class: 'label' }, "2. Paste the AI's answer", answer),
      h('button', { type: 'button', class: 'btn small primary', style: { alignSelf: 'flex-start' }, onclick: async () => {
        try {
          const batches = ui.promptBatches || (await fetchPrompt()).batches;
          const res = await api.post(`/api/runs/${enc(id)}/review/answer`, { batches, text: answer.value });
          ui.promptBatches = null;
          toast(`Saved ${res.saved} decision(s).${res.missing ? ` ${res.missing} listing(s) were not answered and wait in a follow-up batch.` : ''}`);
          await reload();
        } catch (err) { toast(err.message, 'bad'); }
      } }, 'Save answer'));
  }

  function drawSummary() {
    const c = state.counts || {};
    const total = Object.values(c).reduce((a, b) => a + b, 0) || 1;
    const seg = (n, color) => (n ? h('div', { style: { width: `${(100 * n) / total}%`, background: color } }) : null);
    const line = (label, n, color) => h('span', { class: 'row', style: { justifyContent: 'space-between' } },
      h('span', { class: 'row', style: { gap: '8px' } }, h('span', { class: 'dot', style: { width: '8px', height: '8px', background: color } }), label),
      h('span', { class: 'mono', text: fmt.int(n || 0) }));
    clear(summaryBox,
      h('h2', { class: 'card-title', text: `${fmt.int(total - (c.pending || 0))} of ${fmt.int(total)} checked` }),
      h('div', { class: 'split-bar', 'aria-hidden': 'true' }, seg(c.accepted, 'var(--ok-fg)'), seg(c.uncertain, 'var(--warn-fg)'), seg(c.excluded, 'var(--bad-fg)')),
      h('div', { class: 'stack tight' }, line('Keep', c.accepted, 'var(--ok-fg)'), line('Unsure (kept)', c.uncertain, 'var(--warn-fg)'),
        line('Leave out', c.excluded, 'var(--bad-fg)'), c.pending ? line('Not reviewed yet', c.pending, 'var(--muted)') : null),
      state.overrides ? h('span', { class: 'hint', text: `${state.overrides} decision(s) changed by you.` }) : null,
      h('span', { class: 'hint', text: 'You can change any decision below.' }),
      state.instruction ? h('details', { class: 'adv' }, h('summary', {}, 'Instruction used'), h('div', { class: 'body' }, h('span', { class: 'hint', text: state.instruction }))) : null);
  }

  function drawDecisions() {
    const match = (d) => {
      if (ui.q && !(d.n || '').toLowerCase().includes(ui.q)) return false;
      if (ui.filter === 'all') return true;
      if (ui.filter === 'attention') return d.status === 'uncertain' || d.status === 'excluded';
      if (ui.filter === 'changed') return !!d.override;
      return d.status === ui.filter;
    };
    const rows = decisions.filter(match);
    const pages = Math.max(1, Math.ceil(rows.length / PAGE));
    ui.page = Math.min(ui.page, pages - 1);
    const shown = rows.slice(ui.page * PAGE, (ui.page + 1) * PAGE);
    if (!decisions.some((d) => d.status !== 'pending')) { clear(decisionsBox); decisionsBox.hidden = true; return; }
    decisionsBox.hidden = false;
    clear(decisionsBox,
      h('div', { class: 'card-head bar' }, h('h2', { class: 'card-title', text: 'Decisions' }),
        h('div', { class: 'row' },
          h('label', { class: 'search-box', style: { width: '220px' } }, icon('search', 15), h('input', { type: 'search', placeholder: 'Find a listing', value: ui.q,
            'aria-label': 'Find a listing', oninput: (e) => { ui.q = e.target.value.toLowerCase(); ui.page = 0; drawDecisions(); } })),
          h('select', { class: 'field sm', style: { width: '240px' }, 'aria-label': 'Show', onchange: (e) => { ui.filter = e.target.value; ui.page = 0; drawDecisions(); } },
            FILTERS.map(([v, l]) => h('option', { value: v, selected: ui.filter === v }, `${l} (${decisions.filter((d) => (v === 'all' ? true : v === 'attention'
              ? d.status === 'uncertain' || d.status === 'excluded' : v === 'changed' ? !!d.override : d.status === v)).length})`))))),
      h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {}, ['Listing', 'Decision', 'Storefront', 'Price', 'Confidence', 'Reason'].map((t, i) => h('th', { class: i === 3 || i === 4 ? 'r' : '', text: t })))),
        h('tbody', {}, shown.length ? shown.map(decisionRow) : h('tr', {}, h('td', { colspan: 6, class: 'dim', text: 'Nothing to show.' }))))),
      pages > 1 ? h('div', { class: 'pager' }, h('span', { text: `${ui.page * PAGE + 1}–${Math.min(rows.length, (ui.page + 1) * PAGE)} of ${rows.length}` }),
        h('div', { class: 'row' },
          h('button', { type: 'button', class: 'btn small', disabled: ui.page === 0, onclick: () => { ui.page -= 1; drawDecisions(); } }, 'Previous'),
          h('button', { type: 'button', class: 'btn small', disabled: ui.page >= pages - 1, onclick: () => { ui.page += 1; drawDecisions(); } }, 'Next'))) : null);
  }

  function decisionRow(d) {
    const url = safeUrl(d.u);
    const keepOn = d.override ? d.override === 'keep' : d.status === 'accepted';
    const dropOn = d.override ? d.override === 'drop' : d.status === 'excluded';
    const set = async (want) => {
      const current = d.override;
      const keep = current === (want ? 'keep' : 'drop') ? null : want;
      try {
        await api.post(`/api/runs/${enc(id)}/review/override`, { id: d.id, keep });
        await reload();
      } catch (err) { toast(err.message, 'bad'); }
    };
    // the decision sits next to the name, so it stays in view with long titles and reasons
    return h('tr', {},
      h('td', {}, h('div', { class: 'pname', style: { maxWidth: '340px' } }, url ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer', title: d.n || '', text: d.n || '(no title)' })
        : h('span', { class: 'ellipsis', title: d.n || '', text: d.n || '(no title)' }), d.category ? h('span', { class: 'b', text: d.category }) : null)),
      h('td', {}, d.status === 'pending' ? h('span', { class: 'pill plain', text: 'Waiting' }) : h('div', { class: 'row', style: { gap: '8px', flexWrap: 'nowrap' } },
        h('div', { class: 'keep-seg', role: 'group', 'aria-label': 'Decision' },
          h('button', { type: 'button', class: 'keep', 'aria-pressed': String(keepOn), onclick: () => set(true) }, 'Keep'),
          h('button', { type: 'button', class: 'drop', 'aria-pressed': String(dropOn), onclick: () => set(false) }, 'Leave out')),
        d.override ? h('span', { class: 'small muted nowrap', text: 'by you' }) : d.status === 'uncertain' ? h('span', { class: 'pill warn', text: 'Unsure' }) : null)),
      h('td', { class: 'store', text: d.m || '–' }),
      h('td', { class: 'num r dim', text: fmt.local(d.v, d.cur) }),
      h('td', { class: 'num r', text: d.conf === null ? '–' : `${Math.round(d.conf * 100)}%` }),
      h('td', { class: 'dim small' }, h('div', { class: 'clamp2', title: d.reason || '', text: d.reason || (d.status === 'pending' ? 'Not reviewed yet' : '') })));
  }

  function draw() {
    headerActions();
    if (!state.prepared) { drawStart(); return; }
    drawWork();
    drawSummary();
    drawDecisions();
    if (!body.contains(workBox)) clear(body, h('div', { class: 'split' }, h('div', { class: 'stack' }, workBox), summaryBox), decisionsBox);
  }

  if (state.prepared) decisions = (await api.get(`/api/runs/${enc(id)}/review/decisions`)).rows;
  draw();
  if (state.claude && state.claude.running) pollClaude();
  return () => clearInterval(poll);
}
