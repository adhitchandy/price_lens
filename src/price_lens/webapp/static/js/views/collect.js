// Collect step: live progress while the scraper runs, then what each storefront returned
// (with a retry for storefronts that returned nothing).
import { api, enc } from '../api.js';
import { banner, clear, confirmDialog, fmt, h, platformName, toast } from '../dom.js';
import { checkTable } from './shared.js';

const TONE = { ok: 'ok', info: 'info', warn: 'warn', bad: 'bad', idle: '' };

/** Live view of a running job (collection, retry or storefront check). */
export function liveView(container, run, { onFinished, stopLabel = 'Stop' } = {}) {
  let timer = null;
  let stopped = false;
  const pauseBtn = h('button', { type: 'button', class: 'btn', hidden: true,
    title: 'Finishes the storefront in progress, then stops. Everything collected is kept, and you can resume any time, even after a restart.',
    onclick: async () => {
      pauseBtn.disabled = true;
      try { await api.post(`/api/runs/${enc(run)}/pause`); tick(); } catch (err) { toast(err.message, 'bad'); pauseBtn.disabled = false; }
    } }, 'Pause');
  const stopBtn = h('button', { type: 'button', class: 'btn', title: 'Stops right away; the storefront in progress is dropped. Finished storefronts are kept.', onclick: async () => {
    stopBtn.disabled = true;
    try { await api.post(`/api/runs/${enc(run)}/cancel`); tick(); } catch (err) { toast(err.message, 'bad'); stopBtn.disabled = false; }
  } }, stopLabel);
  const forceBtn = h('button', { type: 'button', class: 'btn danger', hidden: true, onclick: async () => {
    if (!(await confirmDialog('Force stop?', 'The browser and the background process are ended now. Storefronts that finished are kept.', 'Force stop'))) return;
    try { await api.post(`/api/runs/${enc(run)}/force-stop`); tick(); } catch (err) { toast(err.message, 'bad'); }
  } }, 'Force stop');
  const sentence = h('p', { class: 'finding' });
  const bar = h('div', { class: 'progress', role: 'progressbar', 'aria-label': 'Progress', 'aria-valuemin': '0', 'aria-valuemax': '100' }, h('div'));
  const barNote = h('div', { class: 'row small muted', style: { justifyContent: 'space-between' } });
  const stores = h('section', { class: 'card', 'aria-label': 'Storefronts', style: { overflow: 'hidden' } });
  const activity = h('ol', { class: 'activity' });
  clear(container,
    h('section', { class: 'stack tight', 'aria-label': 'Progress', 'aria-live': 'polite' },
      h('div', { class: 'row', style: { justifyContent: 'space-between', alignItems: 'flex-start' } }, sentence, h('div', { class: 'actions' }, pauseBtn, stopBtn, forceBtn)),
      bar, barNote),
    h('div', { class: 'split half' }, stores,
      h('section', { class: 'card', 'aria-label': 'Activity', style: { overflow: 'hidden' } },
        h('div', { class: 'card-head bar' }, h('h2', { class: 'card-title', text: 'Activity' }), h('span', { class: 'muted small', text: 'newest at the bottom' })),
        activity)));

  function draw(d) {
    const total = d.stores.length;
    const waiting = d.stores.filter((s) => s.status === 'Waiting for network').length;
    clear(sentence,
      d.state === 'cancelling' ? h('span', { text: 'Stopping… ' }) : null,
      d.state === 'pausing' ? h('span', { text: 'Pausing after the current storefront… ' }) : null,
      h('b', { text: `${d.stores_done} of ${total || '?'}` }), ' storefronts done, ',
      h('span', { class: 'accent', text: `${fmt.int(d.listings)} listings` }), ' saved so far',
      d.time_left ? [', about ', h('b', { text: d.time_left.replace('~', '') }), ' left.'] : '.',
      waiting ? h('span', { class: 'dear', text: ' Waiting for the internet connection…' }) : null);
    bar.firstChild.style.width = `${d.progress}%`;
    bar.setAttribute('aria-valuenow', String(d.progress));
    clear(barNote, h('span', { text: `${d.progress}% · ${d.label}${d.search.total > 1 ? ` · search ${d.search.current} of ${d.search.total}` : ''}${d.search.term ? ` (${d.search.term})` : ''}` }),
      h('span', { text: `${d.started ? `started ${d.started} · ` : ''}runs in the background, so you can close this window` }));
    stopBtn.hidden = d.state === 'cancelling';
    pauseBtn.hidden = !d.can_pause;
    forceBtn.hidden = !d.can_force;
    const byStatus = { Done: 100, 'No products': 100, 'No result': 100 };
    clear(stores, h('div', { class: 'card-head bar' }, h('h2', { class: 'card-title', text: 'Storefronts' })),
      h('div', { class: 'table-wrap' }, h('table', { class: 'table' }, h('tbody', {}, d.stores.map((s) => h('tr', {},
        h('td', {}, h('div', { class: 'pname' }, h('span', { text: s.country || platformName(s.platform) }),
          h('span', { class: 'b mono', text: d.search.total > 1 && s.product ? `${s.store} · ${s.product}` : s.store }))),
        h('td', { style: { width: '120px' } }, h('div', { class: 'mini-bar' }, h('div', { style: { width: `${byStatus[s.status] ?? (s.status === 'Collecting' ? 40 : 0)}%`,
          background: s.tone === 'bad' ? 'var(--bad-fg)' : s.tone === 'warn' ? 'var(--warn-fg)' : 'var(--accent)' } }))),
        h('td', { class: 'num r', text: s.count === null ? '–' : fmt.int(s.count) }),
        h('td', { class: 'r' }, h('span', { class: `pill ${TONE[s.tone] ?? ''}`, text: s.status }))))))));
    const atBottom = activity.scrollHeight - activity.scrollTop - activity.clientHeight < 40;
    clear(activity, d.log.map((l) => h('li', { class: l.k }, h('span', { class: 'd' }), h('span', { text: l.m.replace(/^\s*#+\s*|\s*#+\s*$/g, '') }))));
    if (atBottom) activity.scrollTop = activity.scrollHeight;
  }

  async function tick() {
    if (stopped) return;
    try {
      const d = await api.get(`/api/runs/${enc(run)}/live`);
      draw(d);
      if (!d.active) {
        stopped = true;
        clearInterval(timer);
        if (onFinished) onFinished(d);
      }
    } catch (err) { /* try again on the next tick */ }
  }
  tick();
  timer = setInterval(tick, 2000);
  return () => { stopped = true; clearInterval(timer); };
}

export async function renderCollect(body, ctx) {
  const detail = ctx.detail();
  clear(ctx.actions);
  if (detail.active) {
    return liveView(body, ctx.id, { onFinished: async (d) => {
      await ctx.refresh();
      toast({ paused: 'Paused. Everything collected so far is saved.', cancelled: 'Stopped. Finished storefronts are kept.' }[d.state] || 'Collection finished.');
      finished(body, ctx, await api.get(`/api/runs/${enc(ctx.id)}/live`));
    } });
  }
  if (detail.active_retry) {
    const note = h('div');
    const box = h('div', { class: 'stack' });
    const resuming = detail.active_retry_resume;
    clear(body, banner('info', resuming
      ? 'Resuming: only the storefronts not collected yet. New listings are added to this research as each part finishes, also if you pause again.'
      : 'Retrying storefronts that returned nothing. New listings are added to this research when it finishes.'), box, note);
    return liveView(box, detail.active_retry, { onFinished: async (d) => {
      await ctx.refresh();
      const added = d.summary && d.summary.added_listings !== undefined ? `${fmt.int(d.summary.added_listings)} listing(s) added` : d.state;
      toast(d.state === 'paused' ? `Paused: ${added}.` : `${resuming ? 'Collection' : 'Retry'} finished: ${added}.`);
      finished(body, ctx, await api.get(`/api/runs/${enc(ctx.id)}/live`));
    } });
  }
  finished(body, ctx, await api.get(`/api/runs/${enc(ctx.id)}/live`));
  return null;
}

function finished(body, ctx, live) {
  const detail = ctx.detail();
  const table = live.table || [];
  const ok = table.filter((r) => ['OK', 'Partial'].includes(r.result)).length;
  const failed = detail.failed_storefronts || [];
  clear(ctx.actions,
    detail.collected ? h('a', { class: 'btn', href: `#/r/${ctx.id}/review` }, 'Review listings') : null,
    detail.collected ? h('a', { class: 'btn primary', href: `#/r/${ctx.id}/results` }, 'See results') : null);
  const resume = detail.status === 'paused' && detail.remaining ? resumePanel(ctx, detail) : null;
  const stateNote = resume ? null : {
    cancelled: banner('warn', 'This collection was stopped before the end. Listings from storefronts that finished are kept.'),
    failed: banner('bad', `The collection failed${detail.job.error ? `: ${detail.job.error}` : '.'}`),
    crashed: banner('warn', 'The collection stopped unexpectedly (crash, sleep or shutdown). Listings from storefronts that finished were recovered.'),
    recovered: banner('warn', 'The collection stopped unexpectedly (crash, sleep or shutdown). Listings from storefronts that finished were recovered.'),
  }[detail.job.status];
  clear(body,
    h('p', { class: 'finding' }, 'Collected ', h('span', { class: 'accent', text: `${fmt.int(detail.collected)} listings` }),
      table.length ? [' from ', h('b', { text: `${ok} of ${table.length}` }), ' storefronts.'] : '.'),
    resume,
    stateNote || null,
    failed.length ? retryPanel(ctx, failed) : null,
    table.length ? checkTable(table, 'What each storefront returned') : null,
    detail.searches.length ? h('details', { class: 'card pad adv' }, h('summary', {}, 'Search status and errors'),
      h('div', { class: 'body' }, h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {}, ['Search', 'Status', 'Collected', 'Kept', 'Errors'].map((t) => h('th', { text: t })))),
        h('tbody', {}, detail.searches.map((s) => h('tr', {},
          h('td', { class: 'num', text: `${s.search_id}${s.retry_run ? ' (retry)' : ''}` }), h('td', { text: s.status || '' }),
          h('td', { class: 'num', text: s.raw_rows ?? '–' }), h('td', { class: 'num', text: s.cleaned_rows ?? '–' }),
          h('td', { class: 'dim small', style: { whiteSpace: 'normal', padding: '10px 12px' }, text: s.errors || '' })))))))) : null,
    live.log && live.log.length ? h('details', { class: 'card pad adv' }, h('summary', {}, 'Last log lines'),
      h('div', { class: 'body' }, h('div', { class: 'log', text: live.log.map((l) => l.m).join('\n') }))) : null);
}

function resumePanel(ctx, detail) {
  const done = detail.total_storefronts - detail.remaining;
  const why = { paused: 'Paused', cancelled: 'Stopped' }[detail.job.status] || 'Stopped unexpectedly (crash, sleep or shutdown)';
  const btn = h('button', { type: 'button', class: 'btn primary', onclick: async () => {
    btn.disabled = true;
    try {
      await api.post(`/api/runs/${enc(ctx.id)}/resume`);
      toast('Resumed.');
      location.reload();
    } catch (err) { toast(err.message, 'bad'); btn.disabled = false; }
  } }, 'Resume collecting');
  const pct = detail.total_storefronts ? Math.round((100 * done) / detail.total_storefronts) : 0;
  const unit = (n) => (detail.summary.searches > 1 ? `storefront search${n === 1 ? '' : 'es'}` : `storefront${n === 1 ? '' : 's'}`);
  return h('section', { class: 'card pad stack tight', 'aria-label': 'Resume' },
    h('div', { class: 'row', style: { justifyContent: 'space-between', alignItems: 'flex-start' } },
      h('div', { class: 'stack', style: { gap: '4px' } },
        h('h2', { class: 'card-title', text: `${why} · ${fmt.int(done)} of ${fmt.int(detail.total_storefronts)} ${unit(detail.total_storefronts)} done` }),
        h('p', { class: 'muted', text: `${fmt.int(detail.remaining)} ${unit(detail.remaining)} left, about ${fmt.minutes(detail.remaining_minutes).replace('~', '')}. Resume collects only these and adds them to this research, with the same settings and exchange rates. You can pause again at any time.` })),
      btn),
    h('div', { class: 'progress', role: 'progressbar', 'aria-label': 'Collected so far', 'aria-valuenow': String(pct), 'aria-valuemin': '0', 'aria-valuemax': '100' },
      h('div', { style: { width: `${pct}%` } })));
}

function retryPanel(ctx, failed) {
  const picked = new Set(failed.filter((f) => f.result !== 'Bot check').map((f) => `${f.search_id}|${f.domain}`));
  const btn = h('button', { type: 'button', class: 'btn primary small' });
  const setLabel = () => { btn.textContent = `Retry ${picked.size} storefront${picked.size === 1 ? '' : 's'}`; btn.disabled = !picked.size; };
  btn.addEventListener('click', async () => {
    btn.disabled = true;
    try {
      await api.post(`/api/runs/${enc(ctx.id)}/retry`, { storefronts: [...picked].map((k) => ({ search_id: Number(k.split('|')[0]), domain: k.split('|')[1] })) });
      await ctx.refresh();
      location.reload();
    } catch (err) { toast(err.message, 'bad'); setLabel(); }
  });
  setLabel();
  return h('section', { class: 'card pad stack tight', 'aria-label': 'Retry storefronts' },
    h('div', { class: 'row', style: { justifyContent: 'space-between' } },
      h('h2', { class: 'card-title', text: `${failed.length} storefront${failed.length === 1 ? '' : 's'} returned nothing` }), btn),
    h('p', { class: 'muted', text: 'A retry collects only these storefronts and adds the listings to this research. Bot checks usually persist for a while, so they are not picked.' }),
    h('div', { class: 'stack tight', style: { gap: '4px' } }, failed.map((f) => {
      const key = `${f.search_id}|${f.domain}`;
      return h('label', { class: 'check', style: { alignItems: 'baseline' } },
        h('input', { type: 'checkbox', checked: picked.has(key), onchange: (e) => { if (e.target.checked) picked.add(key); else picked.delete(key); setLabel(); } }),
        h('span', { class: 'mono small', text: f.domain }), h('span', { text: `${f.country} · ${f.result}` }),
        f.problem ? h('span', { class: 'muted small ellipsis', style: { maxWidth: '520px' }, title: f.problem, text: f.problem }) : null);
    })));
}
