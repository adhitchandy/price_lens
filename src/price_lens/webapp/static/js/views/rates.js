// Exchange rates: today's ECB rates, the static table, and the analyst's own rates.
import { api, enc } from '../api.js';
import { banner, clear, dialog, fmt, h, icon, toast } from '../dom.js';

let names = null;
try { names = new Intl.DisplayNames(['en'], { type: 'currency' }); } catch (e) { names = null; }
export const currencyName = (code) => { try { return names ? names.of(code) : ''; } catch (e) { return ''; } };

// Rates are stored as "USD per 1 unit"; people think in "1 USD = x units".
export const perUsd = (usdPerUnit) => (usdPerUnit ? 1 / usdPerUnit : null);
export function fmtRate(value) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '–';
  const digits = value >= 1000 ? 2 : value >= 10 ? 3 : value >= 1 ? 4 : 5;
  return new Intl.NumberFormat('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
}
const backHint = (code, usdPerUnit) => (usdPerUnit ? `1 ${code} = ${fmtRate(usdPerUnit)} USD` : '');

export const SOURCE = {
  yours: { label: 'Yours', tone: 'info' },
  once: { label: 'Yours · next run', tone: 'warn' },
  ecb: { label: 'Live', tone: 'ok' },
  ecbcopy: { label: 'ECB copy', tone: 'ok' },
  builtin: { label: 'Static', tone: '' },
};

const srcKey = (data, src) => (src === 'ecb' && data.state !== 'live' ? 'ecbcopy' : src);

function statusCard(data) {
  const day = data.date ? new Date(`${data.date}T12:00:00`).toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' }) : '';
  const checked = data.checked ? `Checked ${fmt.when(data.checked)}.` : '';
  const [pill, text] = {
    live: [h('span', { class: 'pill ok', text: `ECB · ${day}` }), `European Central Bank reference rates, published every working day around 16:00 CET. ${checked}`],
    cached: [h('span', { class: 'pill warn', text: `Offline · copy of ${day}` }), `The ECB could not be reached, so the last saved copy is used. ${checked}`],
    none: [h('span', { class: 'pill bad', text: 'Not available' }), `The ECB could not be reached and there is no saved copy; the static table is used. ${checked}`],
  }[data.state];
  return h('div', { class: 'card pad stack tight' }, h('span', { class: 'muted', text: 'Live rates' }), h('div', {}, pill), h('p', { class: 'hint', text }));
}

export async function render(view) {
  let data = await api.get('/api/fx');
  const q = { text: '', show: 'storefront' };
  const tableCard = h('section', { class: 'card', style: { overflow: 'hidden' } });
  const top = h('div', { class: 'grid-3' });
  const aside = h('div', { class: 'split half' });

  async function reload(refresh = false) {
    data = await api.get(`/api/fx${refresh ? '?refresh=1' : ''}`);
    draw();
  }

  function drawTop() {
    const own = data.rows.filter((r) => r.own);
    const once = own.filter((r) => !r.own.keep).length;
    const count = (src) => data.rows.filter((r) => r.storefront && (src === 'yours' ? r.own : r.source === src)).length;
    clear(top, statusCard(data),
      h('div', { class: 'card pad stack tight' }, h('span', { class: 'muted', text: 'Your rates' }),
        h('span', { class: 'stat-big', text: String(own.length) }),
        h('p', { class: 'hint', text: own.length ? `${own.length - once} kept for every research${once ? `, ${once} for the next research only` : ''}.` : 'None set. Every research uses the live rates.' })),
      h('div', { class: 'card pad stack tight' }, h('span', { class: 'muted', text: 'The next research uses' }),
        h('div', { class: 'stack', style: { gap: '6px' } },
          [['ecb', 'live rates'], ['builtin', 'static rates'], ['yours', 'your rates']].map(([src, label]) => h('div', { class: 'row', style: { justifyContent: 'space-between' } },
            h('span', { class: `pill ${SOURCE[src].tone}`, text: fmt.cap(label) }), h('span', { class: 'mono', text: String(count(src)) })))),
        h('p', { class: 'hint', text: 'Counted for the currencies of your storefronts.' })));
  }

  function yoursCell(r) {
    if (!r.own) return h('span', { class: 'dim', text: '–' });
    const diff = r.diff_pct;
    return h('div', { class: 'stack', style: { gap: '2px' } },
      h('span', { class: 'num', title: backHint(r.code, r.own.usd_per_unit), text: fmtRate(perUsd(r.own.usd_per_unit)) }),
      h('span', { class: 'hint' }, r.own.keep ? 'Kept' : 'Next research only',
        diff !== null && diff !== undefined ? h('span', { style: { color: Math.abs(diff) >= 10 ? 'var(--warn-fg)' : null }, text: ` · ${fmt.pct(diff)} vs ${r.live ? 'live' : 'static'}` }) : null,
        r.own.note ? ` · ${r.own.note}` : ''));
  }

  function drawTable() {
    const text = q.text.trim().toLowerCase();
    const rows = data.rows.filter((r) => (q.show === 'all' || (q.show === 'storefront' ? r.storefront : r.own))
      && (!text || r.code.toLowerCase().includes(text) || currencyName(r.code).toLowerCase().includes(text)));
    const seg = h('div', { class: 'seg small', role: 'group', 'aria-label': 'Show' },
      [['storefront', 'Storefront currencies'], ['all', 'All'], ['yours', 'Your rates']].map(([key, label]) => h('button', {
        type: 'button', 'aria-pressed': String(q.show === key), onclick: () => { q.show = key; drawTable(); } }, label)));
    const search = h('input', { class: 'field sm', type: 'search', placeholder: 'Find a currency', 'aria-label': 'Find a currency', style: { width: '200px' }, value: q.text,
      oninput: (e) => { q.text = e.target.value; drawTable(); search.focus(); } });
    clear(tableCard,
      h('div', { class: 'card-head bar' }, h('div', { class: 'stack', style: { gap: '4px' } }, h('h2', { class: 'card-title', text: 'Rates' }),
        h('span', { class: 'hint', text: 'Units of each currency per 1 US dollar. Hover a number for the other direction.' })),
      h('div', { class: 'row' }, seg, search)),
      rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
        h('thead', {}, h('tr', {}, h('th', { text: 'Currency' }), h('th', { class: 'r', text: 'Live (ECB)' }), h('th', { class: 'r', text: 'Static' }),
          h('th', { text: 'Your rate' }), h('th', { text: 'Next research uses' }), h('th', { 'aria-label': 'Actions' }))),
        h('tbody', {}, rows.map((r) => h('tr', {},
          h('td', {}, h('div', { class: 'stack', style: { gap: '2px' } }, h('span', { class: 'mono', style: { fontWeight: 600 }, text: r.code }),
            h('span', { class: 'hint', text: currencyName(r.code) }))),
          h('td', { class: 'r num', title: backHint(r.code, r.live), text: fmtRate(perUsd(r.live)) }),
          h('td', { class: 'r num dim', title: backHint(r.code, r.builtin), text: fmtRate(perUsd(r.builtin)) }),
          h('td', {}, yoursCell(r)),
          h('td', {}, h('div', { class: 'row', style: { gap: '10px', flexWrap: 'nowrap' } },
            h('span', { class: `pill ${SOURCE[srcKey(data, r.source)].tone}`, text: SOURCE[srcKey(data, r.source)].label }),
            h('span', { class: 'num', title: backHint(r.code, r.used), text: fmtRate(perUsd(r.used)) }))),
          h('td', { class: 'r nowrap' },
            h('button', { type: 'button', class: 'btn small ghost', onclick: () => editRate(r) }, r.own ? 'Change' : 'Set rate'),
            r.own ? h('button', { type: 'button', class: 'icon-btn', 'aria-label': `Remove your rate for ${r.code}`, title: 'Remove your rate', onclick: async () => {
              try { data = await api.del(`/api/fx/${r.code}`); draw(); toast(`${r.code} uses the ${r.live ? 'live' : 'static'} rate again.`); } catch (err) { toast(err.message, 'bad'); }
            } }, icon('x')) : null))))))
        : h('div', { class: 'empty' }, h('h2', { text: q.show === 'yours' && !text ? 'No rates of your own yet' : 'No currency found' }),
          h('p', { text: q.show === 'yours' && !text ? 'Choose "Set rate" on any currency to use your own rate.' : 'Try another name or code, or add the currency.' })));
  }

  function drawAside() {
    const ACTION = { set: 'set', removed: 'removed', 'used once': 'used by a research, then cleared' };
    clear(aside,
      h('section', { class: 'card pad stack tight' },
        h('h2', { class: 'card-title', text: 'Which rate is used' }),
        h('ol', { class: 'stack', style: { gap: '8px', paddingLeft: '18px', margin: 0, fontSize: '14px' } },
          h('li', {}, h('b', { text: 'Your rate' }), ', if you set one.'),
          h('li', {}, h('b', { text: 'Live' }), ': the ECB rate of the day the research starts.'),
          h('li', {}, h('b', { text: 'Static' }), ': a fixed table, for currencies the ECB does not publish (for example AED, SAR, EGP) or when it cannot be reached.')),
        h('p', { class: 'hint', text: 'Each research keeps the rates it started with, and its Excel report lists them. To recalculate a finished research, open it and choose More, then "Update USD prices".' })),
      h('section', { class: 'card pad stack tight' },
        h('h2', { class: 'card-title', text: 'Recent changes' }),
        data.history.length
          ? h('div', { class: 'stack', style: { gap: '0' } }, data.history.slice(0, 12).map((e) => h('div', { style: { padding: '9px 0', borderBottom: '1px solid var(--line-row)' } },
            h('div', { class: 'row', style: { justifyContent: 'space-between', gap: '8px' } },
              h('span', {}, h('span', { class: 'mono', style: { fontWeight: 600 }, text: e.currency }), ` ${ACTION[e.action] || e.action}`,
                e.action === 'set' ? h('span', { class: 'mono small', text: ` 1 USD = ${fmtRate(perUsd(e.usd_per_unit))}` }) : null),
              h('span', { class: 'hint nowrap', text: fmt.when(e.at) })),
            e.action === 'set' ? h('span', { class: 'hint', text: `${e.keep ? 'Kept for every research' : 'Next research only'}${e.note ? ` · ${e.note}` : ''}` }) : null)))
          : h('p', { class: 'muted', text: 'Nothing changed yet.' })));
  }

  function draw() { drawTop(); drawTable(); drawAside(); }

  function editRate(row) {
    const isNew = !row;
    const state = {
      code: row ? row.code : '',
      value: row && row.own ? fmtRate(perUsd(row.own.usd_per_unit)).replace(/,/g, '') : '',
      keep: row && row.own ? row.own.keep : true,
      note: row && row.own ? row.own.note : '',
    };
    const find = () => data.rows.find((r) => r.code === state.code.toUpperCase());
    const refBox = h('div', { class: 'row', style: { gap: '8px' } });
    const warnBox = h('div');
    const keepHint = h('span', { class: 'hint' });
    const unit = h('span', { class: 'mono', text: state.code || '___' });
    const back = h('span', { class: 'hint' });
    const input = h('input', { class: 'field num', inputmode: 'decimal', 'aria-label': 'Units per 1 US dollar', placeholder: 'e.g. 4.25', value: state.value, style: { width: '180px' },
      oninput: (e) => { state.value = e.target.value; update(); } });
    const number = () => { const n = Number(String(state.value).replace(',', '.').trim()); return Number.isFinite(n) && n > 0 ? n : null; };

    function update() {
      const ref = find();
      const code = state.code.toUpperCase();
      unit.textContent = code || '___';
      const n = number();
      back.textContent = n && code ? `So 1 ${code} = ${fmtRate(1 / n)} USD` : '';
      clear(refBox, ref ? [['Live', ref.live], ['Static', ref.builtin]].filter(([, v]) => v).map(([label, v]) => h('button', {
        type: 'button', class: 'chip toggle', onclick: () => { state.value = fmtRate(perUsd(v)).replace(/,/g, ''); input.value = state.value; update(); },
      }, `${label}: ${fmtRate(perUsd(v))}`)) : null, ref ? h('span', { class: 'hint', text: 'Click to start from one of these.' }) : null);
      const refRate = ref ? (ref.live || ref.builtin) : null;
      const diff = n && refRate ? (1 / n / refRate - 1) * 100 : null;
      clear(warnBox, diff !== null && Math.abs(diff) >= 20 ? banner('warn', `This is ${Math.round(Math.abs(diff))}% ${diff > 0 ? 'above' : 'below'} the ${ref.live ? 'live' : 'static'} rate. Check the direction: type how many ${code} you get for 1 US dollar.`) : null);
      keepHint.textContent = state.keep
        ? 'Used by every new research until you remove it here.'
        : 'Used by the next research only. After that, the live rate is used again.';
    }

    const codeField = isNew ? h('label', { class: 'label' }, 'Currency code',
      h('input', { class: 'field mono', maxlength: 3, placeholder: 'e.g. KRW', 'aria-label': 'Currency code', style: { width: '120px', textTransform: 'uppercase' },
        oninput: (e) => { state.code = e.target.value.replace(/[^A-Za-z]/g, '').toUpperCase(); e.target.value = state.code; update(); } })) : null;
    const body = h('div', { class: 'stack', style: { gap: '16px' } },
      codeField,
      h('div', { class: 'stack tight' },
        h('div', { class: 'row', style: { gap: '10px' } }, h('span', { class: 'mono', text: '1 USD =' }), input, unit),
        back),
      refBox,
      warnBox,
      h('label', { class: 'label' }, 'Where is this rate from? (optional, shown in reports)',
        h('input', { class: 'field', maxlength: 300, placeholder: 'e.g. Client rate, Bloomberg 30 Sep', value: state.note, oninput: (e) => { state.note = e.target.value; } })),
      h('div', { class: 'stack', style: { gap: '4px' } },
        h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: state.keep, onchange: (e) => { state.keep = e.target.checked; update(); } }),
          'Keep this rate for future researches'),
        keepHint),
      data.running.length ? banner('info', 'A research is collecting right now. It keeps the rates it started with; your change applies from the next research.') : null);
    update();
    const title = isNew ? 'Add a currency' : `Your rate for ${row.code}${currencyName(row.code) ? ` · ${currencyName(row.code)}` : ''}`;
    dialog({ title, body, actions: [
      { label: 'Cancel' },
      { label: 'Save rate', primary: true, onclick: async () => {
        const code = state.code.toUpperCase();
        if (!/^[A-Z]{3}$/.test(code)) { toast('Type a three-letter currency code, for example KRW.', 'bad'); return true; }
        if (!number()) { toast('Type the rate as a number greater than 0, for example 4.25.', 'bad'); return true; }
        try {
          data = await api.put(`/api/fx/${enc(code)}`, { per_usd: number(), keep: state.keep, note: state.note });
          draw();
          toast(state.keep ? `${code} saved. Every new research uses your rate.` : `${code} saved for the next research only.`);
          return false;
        } catch (err) { toast(err.message, 'bad'); return true; }
      } },
    ] });
    setTimeout(() => (isNew ? codeField.querySelector('input') : input).focus(), 30);
  }

  clear(view,
    h('div', { class: 'page-head' },
      h('div', { class: 'text' }, h('h1', { class: 'page-title big', text: 'Exchange rates' }),
        h('p', { class: 'page-sub', text: 'Prices are compared in US dollars. See the rates the next research will use, and set your own where you need to.' })),
      h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'btn', onclick: async (e) => {
          const btn = e.currentTarget;
          btn.disabled = true;
          try { await reload(true); toast(data.state === 'live' ? 'Live rates are up to date.' : 'The ECB could not be reached.', data.state === 'live' ? '' : 'bad'); } catch (err) { toast(err.message, 'bad'); }
          btn.disabled = false;
        } }, icon('refresh'), 'Refresh live rates'),
        h('button', { type: 'button', class: 'btn primary', onclick: () => editRate(null) }, icon('plus'), 'Add a currency'))),
    top,
    tableCard, aside);
  draw();
  return null;
}

// ---- One research: recalculate its USD prices ------------------------------------------------
export async function repriceDialog(id, onDone) {
  let state;
  try { state = await api.get(`/api/runs/${enc(id)}/fx`); } catch (err) { toast(err.message, 'bad'); return; }
  const chosen = new Set(state.rows.filter((r) => r.changed && (r.now_source === 'yours' || r.was_source === 'yours')).map((r) => r.code));
  const label = { yours: 'your rate', ecb: 'ECB', builtin: 'static' };
  const nowLabel = { yours: 'your rate', ecb: state.current_state === 'live' ? 'live ECB' : 'saved ECB copy', builtin: 'static' };
  const foot = h('span', { class: 'hint' });
  const table = state.rows.length ? h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
    h('thead', {}, h('tr', {}, h('th', { 'aria-label': 'Update' }), h('th', { text: 'Currency' }), h('th', { class: 'r', text: 'Listings' }),
      h('th', { text: 'Collected with' }), h('th', { text: 'Rate now' }))),
    h('tbody', {}, state.rows.map((r) => h('tr', {},
      h('td', {}, h('input', { type: 'checkbox', 'aria-label': `Update ${r.code}`, checked: chosen.has(r.code), disabled: !r.changed,
        onchange: (e) => { if (e.target.checked) chosen.add(r.code); else chosen.delete(r.code); count(); } })),
      h('td', {}, h('span', { class: 'mono', style: { fontWeight: 600 }, text: r.code }), h('span', { class: 'hint', text: ` ${currencyName(r.code)}` })),
      h('td', { class: 'r num', text: fmt.int(r.listings) }),
      h('td', {}, h('span', { class: 'num', text: `1 USD = ${fmtRate(perUsd(r.was))}` }), h('span', { class: 'hint', text: ` ${label[r.was_source]}${r.was_note ? ` · ${r.was_note}` : ''}` })),
      h('td', {}, r.changed
        ? [h('span', { class: 'num', text: `1 USD = ${fmtRate(perUsd(r.now))}` }), h('span', { class: 'hint', text: ` ${nowLabel[r.now_source]}${r.was ? ` · USD prices ${fmt.pct(Math.round((r.now / r.was - 1) * 1000) / 10)}` : ''}` })]
        : h('span', { class: 'hint', text: 'No change' })))))))
    : h('p', { class: 'muted', text: 'This research has no listings in other currencies than US dollars.' });
  function count() {
    foot.textContent = chosen.size ? `${chosen.size} ${chosen.size === 1 ? 'currency' : 'currencies'} will be recalculated.` : 'Nothing chosen.';
  }
  count();
  const body = h('div', { class: 'stack', style: { gap: '14px' } },
    h('p', { text: `Collected with: ${state.fx}. Tick the currencies to recalculate with today's rates.` }),
    state.busy ? banner('warn', 'This research is still collecting. Update its prices when it has finished.') : null,
    table,
    h('p', { class: 'hint', text: 'The US-dollar prices of the chosen currencies are recalculated in the research, its review and its files. Local prices do not change, and listings are not filtered again by the plan\'s price range.' }),
    h('div', { class: 'row', style: { justifyContent: 'space-between' } }, foot, h('a', { href: '#/fx', text: 'Change rates first' })),
    (state.repriced || []).length ? h('p', { class: 'hint', text: `Updated before: ${state.repriced.map((c) => `${fmt.date(c.at)} (${Object.keys(c.currencies).join(', ')})`).join('; ')}` }) : null);
  dialog({ title: 'Update USD prices', body, wide: true, actions: [
    { label: 'Cancel' },
    { label: 'Recalculate', primary: true, onclick: async () => {
      if (!chosen.size) { toast('Choose at least one currency.', 'bad'); return true; }
      try {
        const res = await api.post(`/api/runs/${enc(id)}/fx`, { currencies: [...chosen] });
        toast(`USD prices updated for ${res.updated.join(', ')}.`);
        if (onDone) onDone();
        return false;
      } catch (err) { toast(err.message, 'bad'); return true; }
    } },
  ] });
}
