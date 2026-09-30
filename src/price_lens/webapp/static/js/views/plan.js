// Plan a research: searches, languages, audiences, filters, where to search, collection size.
// The draft saves itself; the server checks the plan and estimates the run on every change.
import { api, enc, getMeta } from '../api.js';
import { banner, clear, confirmDialog, debounce, dialog, download, fmt, h, icon, platformName, stepsNav, toast } from '../dom.js';
import { aiPlanDialog, importPlanDialog } from './shared.js';

const PLATFORMS = ['zalando', 'amazon', 'ebay', 'mediamarkt'];
const AUDIENCES = ['men', 'women', 'kids'];
const STEPS = [
  { key: 'plan', label: 'Plan', sub: 'Editing', state: 'current' },
  { key: 'check', label: 'Storefront check', sub: 'Optional', state: 'locked' },
  { key: 'collect', label: 'Collect', sub: 'Not started', state: 'locked' },
  { key: 'review', label: 'Review', sub: 'Not started', state: 'locked' },
  { key: 'results', label: 'Results', sub: 'Not started', state: 'locked' },
];

function newSearch(n) {
  return { id: `search_${n}`, product_type: '', query: { default: '', translations: {},
    filters: { include: [], exclude: [], min_price: null, max_price: null } }, targets: [] };
}

function normalise(search, n) {
  search.id = search.id || `search_${n}`;
  search.query = search.query || {};
  search.query.translations = search.query.translations || {};
  search.query.filters = Object.assign({ include: [], exclude: [], min_price: null, max_price: null }, search.query.filters || {});
  search.targets = (search.targets || []).filter((t) => PLATFORMS.includes(t.platform));
  // merge duplicate platforms from imported plans
  const merged = {};
  for (const t of search.targets) {
    if (merged[t.platform]) merged[t.platform].countries = [...new Set([...merged[t.platform].countries, ...(t.countries || [])])];
    else merged[t.platform] = { platform: t.platform, countries: [...(t.countries || [])], platform_options: t.platform_options || {} };
  }
  search.targets = Object.values(merged);
  if (!Array.isArray(search.audiences)) search.audiences = [];
  return search;
}

/** Editable list of words shown as chips. */
function wordsEditor(words, onChange, placeholder, label) {
  const box = h('div', { class: 'chips', role: 'group', 'aria-label': label });
  const input = h('input', { class: 'chip-input', placeholder, 'aria-label': `Add: ${label}` });
  const add = () => {
    const parts = input.value.split(',').map((w) => w.trim()).filter(Boolean);
    if (!parts.length) return;
    for (const p of parts) if (!words.some((w) => w.toLowerCase() === p.toLowerCase())) words.push(p);
    input.value = '';
    onChange();
    draw();
    input.focus();
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(); }
    if (e.key === 'Backspace' && !input.value && words.length) { words.pop(); onChange(); draw(); input.focus(); }
  });
  input.addEventListener('blur', add);
  function draw() {
    clear(box, words.map((w, i) => h('span', { class: 'chip' }, w,
      h('button', { type: 'button', class: 'x', 'aria-label': `Remove ${w}`, onclick: () => { words.splice(i, 1); onChange(); draw(); } }, '×'))), input);
  }
  draw();
  box.redraw = draw;
  return box;
}

export async function render(view, draftId) {
  const [meta, loaded] = await Promise.all([getMeta(), api.get(`/api/drafts/${enc(draftId)}`)]);
  const draft = loaded;
  let plan = draft.plan;
  plan.searches = (plan.searches || []).map((s, i) => normalise(s, i + 1));
  if (!plan.searches.length) plan.searches.push(newSearch(1));
  plan.execution = Object.assign({}, meta.settings.execution, plan.execution || {});
  let validation = null;
  let saveState = 'Saved';
  let stopped = false;
  const byDomain = {};
  for (const [platform, stores] of Object.entries(meta.platforms)) for (const s of stores) byDomain[s.domain] = { ...s, platform };

  const saveLine = h('span', { class: 'muted small', 'aria-live': 'polite' });
  const searchesBox = h('div', { class: 'stack' });
  const summary = h('aside', { class: 'card pad stack sticky', 'aria-label': 'Run summary' });
  const dyn = [];

  // ---- saving and checking -------------------------------------------------------------------
  const save = debounce(async () => {
    if (stopped) return;
    try {
      await api.put(`/api/drafts/${enc(draftId)}`, { plan, goal: draft.goal });
      saveState = 'Saved';
    } catch (err) {
      saveState = `Not saved: ${err.message}`;
    }
    saveLine.textContent = saveState;
  }, 600);
  const validate = debounce(async () => {
    try {
      validation = await api.post('/api/plan/validate', { plan });
      drawSummary();
      plan.searches.forEach((_, i) => drawDynamic(i));
    } catch (err) { /* keep the last result */ }
  }, 350);
  function changed({ check = true } = {}) {
    saveState = 'Saving…';
    saveLine.textContent = saveState;
    save();
    if (check) validate();
  }

  // ---- header -----------------------------------------------------------------------------------
  const titleInput = h('input', { class: 'title-input', value: plan.research_question || '', placeholder: 'Name this research',
    'aria-label': 'Research name', oninput: (e) => { plan.research_question = e.target.value; changed({ check: false }); } });

  async function replacePlan(newPlan) {
    if (!newPlan) return;
    const hasContent = plan.searches.some((s) => s.query.default || s.targets.length);
    if (hasContent && !(await confirmDialog('Replace this plan?', 'The imported plan replaces the searches you have set up here.', 'Replace', false))) return;
    plan = newPlan;
    plan.searches = (plan.searches || []).map((s, i) => normalise(s, i + 1));
    plan.execution = Object.assign({}, meta.settings.execution, plan.execution || {});
    titleInput.value = plan.research_question || '';
    drawAll();
    changed();
  }

  const more = h('details', { class: 'pop-anchor' },
    h('summary', { class: 'btn', 'aria-label': 'More actions', style: { listStyle: 'none' } }, icon('more')),
    h('div', { class: 'popover', style: { right: 0, width: '220px' } },
      h('button', { type: 'button', class: 'btn ghost block', style: { justifyContent: 'flex-start' }, onclick: () => {
        download(new Blob([JSON.stringify(plan, null, 2)], { type: 'application/json' }), 'analyst_plan.json');
      } }, icon('download'), 'Export plan (JSON)'),
      h('button', { type: 'button', class: 'btn ghost block danger', style: { justifyContent: 'flex-start' }, onclick: async () => {
        if (!(await confirmDialog('Delete this draft?', 'The plan is removed. Researches you already ran are not affected.'))) return;
        save.cancel();
        stopped = true;
        await api.del(`/api/drafts/${enc(draftId)}`);
        location.hash = '#/';
      } }, icon('x'), 'Delete draft')));

  clear(view,
    h('nav', { class: 'crumbs', 'aria-label': 'Breadcrumb' }, h('a', { href: '#/' }, 'Researches'), h('span', { 'aria-hidden': 'true', text: '/' }),
      h('span', { text: 'New research' })),
    h('div', { class: 'page-head' },
      h('label', { class: 'text', style: { flex: '1' } }, h('span', { class: 'stat-label', text: 'Research name' }), titleInput),
      h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'btn', onclick: async () => replacePlan(await importPlanDialog()) }, 'Import plan'),
        h('button', { type: 'button', class: 'btn', onclick: async () => replacePlan(await aiPlanDialog()) }, icon('spark'), 'Plan with an AI chat'),
        more)),
    stepsNav(STEPS, null, 'plan'),
    h('div', { class: 'split' },
      h('div', { class: 'stack' },
        h('section', { class: 'card pad stack tight', 'aria-label': 'Goal' },
          h('label', { for: 'goal', class: 'card-title', text: 'What do you want to find out?' }),
          h('textarea', { id: 'goal', class: 'field', rows: 2, value: draft.goal || '',
            placeholder: 'e.g. Compare running-shoe prices for men and women across Zalando, Amazon and eBay in six European countries.',
            oninput: (e) => { draft.goal = e.target.value; changed({ check: false }); } }),
          h('span', { class: 'hint', text: 'Optional. It is shown with the results and helps the relevance review.' })),
        searchesBox,
        h('button', { type: 'button', class: 'btn block', style: { height: '56px', borderStyle: 'dashed', color: 'var(--accent)' }, onclick: () => {
          plan.searches.push(newSearch(plan.searches.length + 1));
          drawAll();
          changed();
        } }, icon('plus'), 'Add another search')),
      summary));

  document.addEventListener('click', closePopovers);
  function closePopovers(e) {
    view.querySelectorAll('details.pop-anchor[open]').forEach((d) => { if (!d.contains(e.target)) d.open = false; });
  }

  // ---- one search ---------------------------------------------------------------------------------
  function drawAll() {
    dyn.length = 0;
    clear(searchesBox, plan.searches.map((s, i) => searchCard(s, i)));
    drawSummary();
    validate();
  }

  function searchCard(search, idx) {
    const q = search.query;
    const f = q.filters;
    const title = h('h2', { class: 'card-title' });
    const setTitle = () => { title.textContent = `Search ${idx + 1} · ${search.product_type || q.default || 'Untitled'}`; };
    setTitle();
    const refs = { langBox: h('div', { class: 'stack tight' }), probBox: h('div'), langKey: null, suggestBox: h('div') };
    dyn[idx] = refs;

    const presetSel = h('select', { class: 'field sm', 'aria-label': 'Product type preset' }, h('option', { value: '' }, 'Product type…'),
      Object.keys(meta.product_presets).map((p) => h('option', { value: p }, p)));
    const groupSel = h('select', { class: 'field sm', 'aria-label': 'Country group' }, h('option', { value: '' }, 'Countries…'),
      Object.keys(meta.country_groups).map((g) => h('option', { value: g }, g)));
    const quick = h('div', { class: 'row' },
      h('span', { class: 'muted small', text: 'Quick setup' }),
      h('div', { style: { width: '200px' } }, presetSel), h('div', { style: { width: '220px' } }, groupSel),
      h('button', { type: 'button', class: 'btn small', onclick: async () => {
        if (!presetSel.value && !groupSel.value) { toast('Pick a product type or a country group first.'); return; }
        try {
          const res = await api.post('/api/plan/quick-setup', { search, preset: presetSel.value, group: groupSel.value });
          plan.searches[idx] = normalise(res.search, idx + 1);
          drawAll();
          changed();
          toast(res.notes.length ? `Applied. ${res.notes.join(' · ')}` : 'Quick setup applied.');
        } catch (err) { toast(err.message, 'bad'); }
      } }, 'Apply'));

    const whereBox = h('div', { class: 'where-table' });
    function drawWhere() {
      clear(whereBox, PLATFORMS.map((platform) => platformRow(platform)));
    }
    function platformRow(platform) {
      const target = search.targets.find((t) => t.platform === platform);
      const stores = meta.platforms[platform] || [];
      const row = h('div', { class: `where-row ${target ? '' : 'off'}` });
      const use = h('input', { type: 'checkbox', checked: !!target, 'aria-label': `Search on ${platformName(platform)}`, onchange: () => {
        if (use.checked) search.targets.push({ platform, countries: [], platform_options: {} });
        else search.targets = search.targets.filter((t) => t.platform !== platform);
        drawWhere(); changed();
      } });
      const name = h('label', { class: 'name' }, use, platformName(platform));
      if (!target) { row.append(name, h('span', { class: 'muted small', text: 'Not used' })); return row; }
      const problems = (validation && validation.searches[idx] && validation.searches[idx].problems) || {};
      const chips = h('div', { class: 'chips' });
      const all = target.countries.includes('all');
      const selected = all ? [] : target.countries;
      if (all) chips.append(h('span', { class: 'chip store' }, h('span', { class: 'dot' }), `All countries (${stores.length})`,
        h('button', { type: 'button', class: 'x', 'aria-label': 'Remove all countries', onclick: () => { target.countries = []; drawWhere(); changed(); } }, '×')));
      for (const country of selected) {
        const store = stores.find((s) => s.country === country);
        const bad = store && problems[store.domain];
        const tone = bad ? (bad.result === 'Partial' ? 'warn' : 'bad') : '';
        chips.append(h('span', { class: `chip store ${tone}`, title: bad ? `${store.domain}: ${bad.result} last time` : (store ? store.domain : '') },
          h('span', { class: `dot ${tone}` }), country,
          h('button', { type: 'button', class: 'x', 'aria-label': `Remove ${country}`, onclick: () => {
            target.countries = target.countries.filter((c) => c !== country); drawWhere(); changed();
          } }, '×')));
      }
      chips.append(countryPicker(platform, target, stores));
      if (!target.countries.length) chips.append(h('span', { class: 'hint', style: { color: 'var(--bad-fg)' }, text: 'Pick at least one country' }));
      row.append(name, chips);
      return row;
    }
    function countryPicker(platform, target, stores) {
      const details = h('details', { class: 'pop-anchor' });
      const list = h('div', { class: 'stack tight', style: { gap: '0' } });
      const filter = h('input', { class: 'field sm', placeholder: 'Find a country', 'aria-label': 'Find a country', style: { marginBottom: '6px' } });
      const draw = () => {
        const term = filter.value.toLowerCase();
        const all = target.countries.includes('all');
        clear(list,
          h('label', { class: 'opt' }, h('input', { type: 'checkbox', checked: all, onchange: (e) => {
            target.countries = e.target.checked ? ['all'] : []; draw(); drawWhere(); changed();
          } }), h('b', { text: 'All countries' })),
          stores.filter((s) => !term || s.country.toLowerCase().includes(term)).map((s) => h('label', { class: 'opt' },
            h('input', { type: 'checkbox', checked: all || target.countries.includes(s.country), disabled: all, onchange: (e) => {
              if (e.target.checked) target.countries.push(s.country);
              else target.countries = target.countries.filter((c) => c !== s.country);
              drawWhereKeepOpen(platform); changed();
            } }), s.country, h('span', { class: 'domain', text: s.domain }))));
      };
      filter.addEventListener('input', draw);
      details.append(h('summary', { class: 'btn small', style: { listStyle: 'none', borderStyle: 'dashed', color: 'var(--accent)' } }, icon('plus', 14), 'Country'),
        h('div', { class: 'popover' }, stores.length > 10 ? filter : null, list));
      details.addEventListener('toggle', () => { if (details.open) { draw(); if (stores.length > 10) filter.focus(); } });
      return details;
    }
    function drawWhereKeepOpen(platform) {
      // redraw the chips of one platform without closing its open country list
      const rows = [...whereBox.children];
      const index = PLATFORMS.indexOf(platform);
      const openDetails = rows[index] && rows[index].querySelector('details[open]');
      const fresh = platformRow(platform);
      if (openDetails) {
        const slot = fresh.querySelector('details');
        slot.replaceWith(openDetails);
      }
      rows[index].replaceWith(fresh);
    }
    drawWhere();
    refs.redrawWhere = drawWhere;
    refs.whereBox = whereBox;

    // audiences
    const others = () => search.targets.some((t) => t.platform !== 'zalando');
    const audBox = h('div', { class: 'stack tight' });
    function drawAudiences() {
      clear(audBox, h('span', { class: 'section-title', text: 'Audiences' }),
        h('div', { class: 'chips' }, AUDIENCES.map((a) => h('button', {
          type: 'button', class: 'chip toggle', 'aria-pressed': String(search.audiences.includes(a)), onclick: () => {
            search.audiences = search.audiences.includes(a) ? search.audiences.filter((x) => x !== a) : AUDIENCES.filter((x) => x === a || search.audiences.includes(x));
            drawAudiences(); changed();
          },
        }, fmt.cap(a)))),
        search.audiences.length && others() ? h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: search.split_audiences !== false,
          onchange: (e) => { search.split_audiences = e.target.checked; changed(); } }),
        `One query per audience on ${search.targets.filter((t) => t.platform !== 'zalando').map((t) => platformName(t.platform)).join(', ')}`) : null,
        h('span', { class: 'hint', text: search.targets.some((t) => t.platform === 'zalando')
          ? 'Zalando searches its men/women/kids shops (all three if none is picked); other platforms get one query per audience.'
          : 'Each audience becomes its own query in the local language, e.g. "Herren Laufschuhe".' }));
    }
    drawAudiences();
    refs.drawAudiences = drawAudiences;

    const price = (key, label) => h('input', { class: 'field sm num', type: 'number', min: '0', step: '1', style: { width: '120px' },
      value: f[key] ?? '', placeholder: key === 'min_price' ? 'none' : 'no limit', 'aria-label': label,
      oninput: (e) => { const v = parseFloat(e.target.value); f[key] = Number.isFinite(v) && v > 0 ? v : null; changed(); } });

    const excludes = wordsEditor(f.exclude, () => { changed(); }, 'Add a word', 'Leave out listings that mention');
    const includes = wordsEditor(f.include, () => { changed(); }, 'Add a word', 'Only keep listings that mention');

    const card = h('section', { class: 'card', 'aria-label': `Search ${idx + 1}` },
      h('div', { class: 'search-card-head' }, title,
        h('div', { class: 'row', style: { gap: '6px' } },
          h('button', { type: 'button', class: 'btn small', onclick: () => {
            const copy = JSON.parse(JSON.stringify(search));
            copy.id = `search_${plan.searches.length + 1}`;
            plan.searches.splice(idx + 1, 0, copy); drawAll(); changed();
          } }, 'Duplicate'),
          h('button', { type: 'button', class: 'btn small danger', onclick: async () => {
            if ((search.query.default || search.targets.length) && !(await confirmDialog('Remove this search?', `Search ${idx + 1} and its settings are removed from the plan.`, 'Remove'))) return;
            plan.searches.splice(idx, 1);
            if (!plan.searches.length) plan.searches.push(newSearch(1));
            drawAll(); changed();
          } }, 'Remove'))),
      h('div', { class: 'search-card-body' },
        quick,
        h('div', { class: 'grid-2' },
          h('label', { class: 'label' }, 'Search for', h('input', { class: 'field', value: q.default || '', placeholder: 'e.g. running shoes',
            oninput: (e) => { q.default = e.target.value.trim() ? e.target.value : ''; setTitle(); changed(); } })),
          h('label', { class: 'label' }, 'Product group (label in reports)', h('input', { class: 'field', value: search.product_type || '',
            placeholder: 'e.g. Running shoes', oninput: (e) => { search.product_type = e.target.value; setTitle(); changed(); } }))),
        h('div', { class: 'stack tight' }, h('span', { class: 'section-title', text: 'Where to search' }), whereBox, refs.probBox),
        h('div', { class: 'grid-2', style: { alignItems: 'start' } }, audBox,
          h('div', { class: 'stack tight' }, h('span', { class: 'section-title', text: 'Price range (USD)' }),
            h('div', { class: 'row' }, price('min_price', 'Lowest price in USD'), h('span', { class: 'muted', text: 'to' }), price('max_price', 'Highest price in USD')),
            h('span', { class: 'hint', text: 'Compared after conversion to USD, so it works across currencies.' }))),
        refs.langBox,
        h('div', { class: 'stack tight' },
          h('div', { class: 'row', style: { justifyContent: 'space-between' } }, h('span', { class: 'section-title', text: 'Leave out listings that mention' }),
            h('button', { type: 'button', class: 'link', onclick: () => suggest(search, idx, refs, excludes) }, 'Suggest translations')),
          excludes, refs.suggestBox,
          h('span', { class: 'hint', text: 'Matched anywhere in the listing title. Add words in each language you search in (Suggest translations helps).' })),
        h('details', { class: 'adv' }, h('summary', {}, 'Only keep listings that mention…'),
          h('div', { class: 'body' }, includes, h('span', { class: 'hint', text: 'Every word must appear in the title. Leave empty to keep all.' })))));
    return card;
  }

  async function suggest(search, idx, refs, excludes) {
    const langs = ((validation && validation.searches[idx]) ? validation.searches[idx].languages : []).map((l) => l.lang);
    if (!search.query.filters.exclude.length) { toast('Add a word to leave out first.'); return; }
    if (!langs.length) { toast('Pick where to search first, so the languages are known.'); return; }
    try {
      const res = await api.post('/api/plan/suggest-excludes', { words: search.query.filters.exclude, languages: langs });
      if (!res.words.length) {
        clear(refs.suggestBox, h('span', { class: 'hint', text: `No new translations known${res.unknown.length ? ` for: ${res.unknown.join(', ')}` : ''}.` }));
        return;
      }
      const picked = new Set(res.words);
      const chips = h('div', { class: 'chips' }, res.words.map((w) => h('button', { type: 'button', class: 'chip toggle', 'aria-pressed': 'true',
        onclick: (e) => { const on = e.currentTarget.getAttribute('aria-pressed') === 'true'; e.currentTarget.setAttribute('aria-pressed', String(!on)); if (on) picked.delete(w); else picked.add(w); } }, w)));
      clear(refs.suggestBox, h('div', { class: 'banner info' }, h('div', { class: 'grow stack tight' },
        h('span', { text: 'Suggested words in the other languages (click to leave one out):' }), chips,
        res.unknown.length ? h('span', { class: 'small', text: `No offline translation known for: ${res.unknown.join(', ')}` }) : null,
        h('div', { class: 'row' },
          h('button', { type: 'button', class: 'btn small primary', onclick: () => {
            for (const w of picked) if (!search.query.filters.exclude.includes(w)) search.query.filters.exclude.push(w);
            excludes.redraw(); clear(refs.suggestBox); changed();
          } }, 'Add these'),
          h('button', { type: 'button', class: 'btn small', onclick: () => clear(refs.suggestBox) }, 'Dismiss')))));
    } catch (err) { toast(err.message, 'bad'); }
  }

  // ---- parts that depend on the server check -------------------------------------------------------
  function drawDynamic(idx) {
    const refs = dyn[idx];
    const search = plan.searches[idx];
    const info = validation && validation.searches[idx];
    if (!refs || !search || !info) return;
    // storefronts that failed last time
    const problems = Object.entries(info.problems || {});
    clear(refs.probBox, problems.length ? banner('warn',
      h('div', { class: 'stack tight' },
        h('span', { text: 'These storefronts failed last time:' }),
        h('span', { class: 'small', text: problems.map(([d, p]) => `${d}: ${p.result}`).join(' · ') }),
        h('div', {}, h('button', { type: 'button', class: 'btn small', onclick: () => {
          for (const [domain] of problems) {
            const store = byDomain[domain];
            const target = store && search.targets.find((t) => t.platform === store.platform);
            if (!target) continue;
            if (target.countries.includes('all')) target.countries = meta.platforms[store.platform].map((s) => s.country);
            target.countries = target.countries.filter((c) => c !== store.country);
          }
          refs.redrawWhere(); changed();
        } }, 'Leave these out')))) : null);
    const probKey = JSON.stringify(info.problems || {});
    if (probKey !== refs.probKey && !refs.whereBox.querySelector('details[open]') && !refs.whereBox.contains(document.activeElement)) {
      refs.probKey = probKey;
      refs.redrawWhere();
    }
    // languages (never redrawn while you type in them)
    const langs = info.languages || [];
    const key = JSON.stringify(langs.map((l) => [l.lang, Object.keys(l.audience_phrases || {})])) + (search.query.default || '');
    if (key === refs.langKey || refs.langBox.contains(document.activeElement)) { updateLangHints(refs, langs); return; }
    refs.langKey = key;
    if (!langs.length) { clear(refs.langBox); return; }
    const q = search.query;
    const missing = langs.filter((l) => l.needed);
    const withAud = langs.filter((l) => Object.keys(l.audience_phrases || {}).length);
    clear(refs.langBox,
      h('div', { class: 'row', style: { justifyContent: 'space-between' } },
        h('span', { class: 'section-title', text: 'Search words in each language' }),
        missing.length ? h('button', { type: 'button', class: 'link', onclick: () => {
          for (const l of missing) setTranslation(q, l.lang, q.default || '');
          refs.langKey = null; changed();
        } }, `Use "${q.default || '…'}" as typed where missing`) : null),
      h('div', { class: 'lang-table' }, langs.map((l) => h('div', { class: `lang-row ${l.needed ? 'needed' : ''}`, dataset: { lang: l.lang } },
        h('span', {}, l.name, h('span', { class: 'small need-note', hidden: !l.needed, style: { display: 'block', color: 'var(--warn-fg)' }, text: 'needs a local word' })),
        h('input', { class: 'field sm', value: l.term || '', placeholder: q.default || '', 'aria-label': `${l.name} search words`,
          oninput: (e) => { setTranslation(q, l.lang, e.target.value); changed(); } }),
        h('span', { class: 'where', title: l.domains.join(', '), text: l.lang === 'en' && !l.term ? `${l.domains.join(', ')} · uses "Search for"` : l.domains.join(', ') })))),
      missing.length ? h('span', { class: 'hint', style: { color: 'var(--warn-fg)' },
        text: 'Storefronts search the words exactly as typed. Without a local word they may return the wrong products.' }) : null,
      withAud.length ? h('details', { class: 'adv' }, h('summary', {}, 'Audience phrases per language'),
        h('div', { class: 'body' }, h('span', { class: 'hint', text: 'Used on Amazon, eBay and MediaMarkt. Leave a box empty to use the suggestion shown.' }),
          h('div', { class: 'lang-table' }, withAud.map((l) => h('div', { class: 'lang-row', style: { gridTemplateColumns: `150px repeat(${Object.keys(l.audience_phrases).length}, minmax(0, 1fr))` } },
            h('span', { text: l.name }),
            Object.entries(l.audience_phrases).map(([aud, phrase]) => {
              const override = ((q.audience_queries || {})[l.lang] || {})[aud] || '';
              return h('input', { class: 'field sm', value: override, placeholder: phrase, 'aria-label': `${l.name}, ${aud}`,
                oninput: (e) => {
                  q.audience_queries = q.audience_queries || {};
                  q.audience_queries[l.lang] = q.audience_queries[l.lang] || {};
                  if (e.target.value.trim()) q.audience_queries[l.lang][aud] = e.target.value.trim();
                  else delete q.audience_queries[l.lang][aud];
                  if (!Object.keys(q.audience_queries[l.lang]).length) delete q.audience_queries[l.lang];
                  if (!Object.keys(q.audience_queries).length) delete q.audience_queries;
                  changed();
                } });
            })))))) : null);
  }

  function updateLangHints(refs, langs) {
    for (const l of langs) {
      const row = refs.langBox.querySelector(`.lang-row[data-lang="${l.lang}"]`);
      if (!row) continue;
      row.classList.toggle('needed', !!l.needed);
      const note = row.querySelector('.need-note');
      if (note) note.hidden = !l.needed;
    }
  }

  function setTranslation(q, lang, value) {
    const previous = q.translations[lang];
    const text = String(value || '').trim();
    if (previous && typeof previous === 'object') {
      if (text) q.translations[lang] = { ...previous, search_term: text };
      else delete q.translations[lang];
    } else if (text) q.translations[lang] = text;
    else delete q.translations[lang];
  }

  // ---- summary ---------------------------------------------------------------------------------------
  function drawSummary() {
    const ex = plan.execution;
    const v = validation;
    const pagesMode = !ex.products_per_storefront;
    const ok = v && v.ok;
    const problems = v ? Object.keys(v.problems || {}) : [];
    const setEx = (k, val) => { ex[k] = val; changed(); };
    const numberField = (label, key, { min = 0, max = 10000, step = 1 } = {}) => h('label', { class: 'label' }, label,
      h('input', { class: 'field sm num', type: 'number', min, max, step, value: ex[key] ?? '',
        onchange: (e) => { const n = Number(e.target.value); if (Number.isFinite(n)) setEx(key, Math.min(max, Math.max(min, n))); } }));
    const ppsf = h('input', { type: 'text', inputmode: 'numeric', value: ex.products_per_storefront || 100, 'aria-label': 'Products per storefront',
      onchange: (e) => { const n = parseInt(e.target.value, 10); setEx('products_per_storefront', Number.isFinite(n) && n > 0 ? Math.min(5000, n) : 100); drawSummary(); } });
    const stepBy = (d) => { setEx('products_per_storefront', Math.max(10, Math.min(5000, (ex.products_per_storefront || 100) + d))); drawSummary(); };
    const delays = ex.delay_seconds || [2.5, 4.5];
    const target = v && ok && !pagesMode ? (ex.products_per_storefront || 0) * v.queries : null;
    clear(summary,
      h('h2', { class: 'card-title', text: ok ? 'Ready to collect' : 'Not ready yet' }),
      h('div', { class: 'stat-grid' },
        h('div', {}, h('span', { class: 'muted small', text: 'Storefronts' }), h('span', { class: 'v', text: v ? String(v.storefronts) : '–' })),
        h('div', {}, h('span', { class: 'muted small', text: 'Queries' }), h('span', { class: 'v', text: v ? fmt.int(v.queries) : '–' })),
        h('div', {}, h('span', { class: 'muted small', text: 'Estimated time' }), h('span', { class: 'v', text: ok ? fmt.minutes(v.estimate_minutes) : '–' })),
        h('div', {}, h('span', { class: 'muted small', text: 'Listings target' }), h('span', { class: 'v', text: target ? fmt.int(target) : '–' }))),
      pagesMode
        ? h('p', { class: 'muted', text: `Collecting ${ex.pages || 1} result page(s) per query (see Collection settings).` })
        : h('div', { class: 'label' }, 'Products per storefront',
          h('div', { class: 'stepper' },
            h('button', { type: 'button', 'aria-label': 'Fewer', onclick: () => stepBy(-10) }, '−'), ppsf,
            h('button', { type: 'button', 'aria-label': 'More', onclick: () => stepBy(10) }, '+')),
          h('span', { class: 'hint', text: 'Per storefront and query; the scraper keeps paging (up to 20 pages) until it has this many.' })),
      v && v.error ? banner('bad', v.error) : null,
      problems.length ? banner('warn', `${problems.length} storefront(s) failed last time: ${problems.slice(0, 4).join(', ')}${problems.length > 4 ? '…' : ''}. Test them first or leave them out.`) : null,
      h('div', { class: 'stack tight' },
        h('button', { type: 'button', class: 'btn primary block', disabled: !ok, onclick: () => start('scrape') }, 'Start collecting'),
        h('button', { type: 'button', class: 'btn block', disabled: !ok, onclick: () => start('check') },
          `Test the ${v && v.storefronts ? v.storefronts : ''} storefronts first`),
        ok ? h('button', { type: 'button', class: 'link', onclick: showPreview }, 'What will be searched') : null),
      h('details', { class: 'adv' }, h('summary', {}, 'Collection settings'),
        h('div', { class: 'body' },
          h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: pagesMode, onchange: (e) => {
            if (e.target.checked) { delete ex.products_per_storefront; ex.pages = ex.pages || 1; } else ex.products_per_storefront = 100;
            changed(); drawSummary();
          } }), 'Use a fixed number of result pages instead'),
          pagesMode ? numberField('Pages per query', 'pages', { min: 1, max: 20 }) : null,
          numberField('Retries on failure', 'retries', { min: 0, max: 5 }),
          h('div', { class: 'grid-2' },
            h('label', { class: 'label' }, 'Min pause (s)', h('input', { class: 'field sm num', type: 'number', min: 0.5, max: 60, step: 0.5, value: delays[0],
              onchange: (e) => { const n = Math.max(0.5, Number(e.target.value) || 2.5); setEx('delay_seconds', [n, Math.max(n, delays[1])]); } })),
            h('label', { class: 'label' }, 'Max pause (s)', h('input', { class: 'field sm num', type: 'number', min: 0.5, max: 60, step: 0.5, value: delays[1],
              onchange: (e) => { const n = Math.max(0.5, Number(e.target.value) || 4.5); setEx('delay_seconds', [Math.min(delays[0], n), n]); } }))),
          h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!ex.headless, onchange: (e) => setEx('headless', e.target.checked) }),
            'Hide the browser window'),
          h('span', { class: 'hint', text: 'Visible browsers are blocked less often by bot checks.' }),
          h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: !!ex.enrich_details, onchange: (e) => { setEx('enrich_details', e.target.checked); drawSummary(); } }),
            'Open product pages for extra details (Zalando, MediaMarkt)'),
          ex.enrich_details ? numberField('Max product pages per storefront', 'max_detail_products', { min: 1, max: 10000 }) : null)),
      saveLine);
    saveLine.textContent = saveState;
  }

  function showPreview() {
    const rows = (validation && validation.preview) || [];
    dialog({ title: 'What will be searched', wide: true, body: h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
      h('thead', {}, h('tr', {}, ['Search', 'Platform', 'Country', 'Storefront', 'Language', 'Audience', 'Search words', 'Left out'].map((t) => h('th', { text: t })))),
      h('tbody', {}, rows.map((r) => h('tr', {},
        h('td', { class: 'num', text: r.search_id }), h('td', { text: platformName(r.platform) }), h('td', { text: r.country }),
        h('td', { class: 'store', text: r.domain }), h('td', { text: r.language }), h('td', { class: 'dim', text: r.audience || '–' }),
        h('td', { text: r.query }), h('td', { class: 'dim small', text: r.exclude || '–' })))))) });
  }

  async function start(kind) {
    save.flush();
    try {
      await api.put(`/api/drafts/${enc(draftId)}`, { plan, goal: draft.goal });
      const res = await api.post('/api/start', { draft: draftId, kind });
      if (kind === 'scrape') stopped = true;
      location.hash = kind === 'check' ? `#/check/${res.run}?draft=${enc(draftId)}` : `#/r/${res.run}/collect`;
    } catch (err) {
      toast(err.message, 'bad');
    }
  }

  drawAll();
  return () => {
    document.removeEventListener('click', closePopovers);
    save.flush();
  };
}
