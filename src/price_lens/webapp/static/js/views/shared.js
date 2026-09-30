// Dialogs used on more than one screen: import a plan, plan with an AI chat.
import { api } from '../api.js';
import { banner, copyText, dialog, fmt, h, icon, platformName, toast } from '../dom.js';

/** Paste or choose a plan file. Resolves with the imported plan (or null). */
export function importPlanDialog() {
  return new Promise((resolve) => {
    let done = false;
    const area = h('textarea', { class: 'field mono', rows: 12, placeholder: '{ "schema_version": "analyst-v2", … }', 'aria-label': 'Plan JSON',
      style: { fontSize: '12px' } });
    const file = h('input', { type: 'file', accept: '.json,.txt,application/json', class: 'sr-only', id: 'plan-file' });
    const fileName = h('span', { class: 'muted small' });
    const error = h('div');
    file.addEventListener('change', async () => {
      const chosen = file.files[0];
      if (!chosen) return;
      area.value = await chosen.text();
      fileName.textContent = chosen.name;
    });
    const { dlg } = dialog({
      title: 'Import a plan',
      body: [
        h('p', { class: 'muted', text: 'Paste a plan (for example one an AI chat wrote for you), or choose a saved plan file.' }),
        h('div', { class: 'row' }, h('label', { for: 'plan-file', class: 'btn small' }, icon('upload'), 'Choose file'), fileName, file),
        area, error,
      ],
      actions: [
        { label: 'Cancel' },
        { label: 'Import', primary: true, onclick: async () => {
          try {
            const result = await api.post('/api/plan/import', { text: area.value });
            done = true;
            resolve(result.plan);
            return false;
          } catch (err) {
            error.replaceChildren(banner('bad', err.message));
            return true;
          }
        } },
      ],
    });
    dlg.addEventListener('close', () => { if (!done) resolve(null); });
  });
}

/** Describe the research, copy the prompt into any AI chat, paste its plan back. */
export function aiPlanDialog() {
  return new Promise((resolve) => {
    let done = false;
    const request = h('textarea', { class: 'field', rows: 4, 'aria-label': 'Describe your research',
      placeholder: "e.g. Men's and women's sneaker prices in Germany, France and the UK on Zalando, Amazon and eBay, about 50 per shop, no socks or laces." });
    const note = h('span', { class: 'hint' });
    const answer = h('textarea', { class: 'field mono', rows: 8, 'aria-label': 'The plan the AI wrote', placeholder: 'Paste the JSON plan here',
      style: { fontSize: '12px' } });
    const error = h('div');
    const copy = h('button', { type: 'button', class: 'btn', onclick: async () => {
      try {
        const { prompt } = await api.post('/api/plan/prompt', { request: request.value });
        const ok = await copyText(prompt);
        note.textContent = ok ? 'Copied. Paste it into your AI chat (Ctrl+V), answer its questions, then paste the plan below.'
          : 'Copy was blocked by the browser.';
      } catch (err) { note.textContent = err.message; }
    } }, icon('copy'), 'Copy prompt');
    const { dlg } = dialog({
      title: 'Plan with an AI chat',
      body: [
        h('p', { class: 'muted', text: 'The prompt holds the planning rules. The AI first asks a few questions (product scope, brands, audiences, local search words), then writes the plan.' }),
        h('label', { class: 'label' }, '1. Describe your research', request),
        h('div', { class: 'row' }, copy, note),
        h('label', { class: 'label' }, '2. Paste the plan the AI returns', answer), error,
      ],
      actions: [
        { label: 'Cancel' },
        { label: 'Use this plan', primary: true, onclick: async () => {
          try {
            const result = await api.post('/api/plan/import', { text: answer.value });
            done = true;
            resolve(result.plan);
            toast('Plan imported. Check it, then start collecting.');
            return false;
          } catch (err) {
            error.replaceChildren(banner('bad', err.message));
            return true;
          }
        } },
      ],
    });
    dlg.addEventListener('close', () => { if (!done) resolve(null); });
  });
}

/** Table of what each storefront returned (storefront check or collection). */
export function checkTable(rows, title) {
  const tone = { OK: 'ok', Partial: 'warn', Network: '', 'Cookie wall': 'bad', Redirect: 'bad', 'Bot check': 'bad', 'No products loaded': 'bad', 'Not collected yet': '' };
  return h('section', { class: 'card', style: { overflow: 'hidden' } },
    h('div', { class: 'card-head bar' }, h('h2', { class: 'card-title', text: title })),
    h('div', { class: 'table-wrap' }, h('table', { class: 'table' },
      h('thead', {}, h('tr', {}, ['Storefront', 'Country', 'Platform', 'Products', 'Result', 'Details'].map((t, i) => h('th', { class: i === 3 ? 'r' : '', text: t })))),
      h('tbody', {}, rows.map((r) => h('tr', {},
        h('td', { class: 'store', text: r.storefront }), h('td', { text: r.country || '' }), h('td', { text: platformName(r.platform) }),
        h('td', { class: 'num r', text: fmt.int(r.products_found) }),
        h('td', {}, h('span', { class: `pill ${tone[r.result] ?? 'bad'}`, text: r.result })),
        h('td', { class: 'dim small', style: { maxWidth: '520px' } }, h('span', { class: 'ellipsis', title: r.problem || '', text: r.problem || '' }))))))));
}
