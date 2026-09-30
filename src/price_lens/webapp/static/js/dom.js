// Small DOM toolkit: element builder, icons, formatting, toasts, dialogs, clipboard.
// Text always goes in as text, never parsed as HTML (listing titles come from websites).

export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'text') el.textContent = value;
    else if (key === 'style') Object.assign(el.style, value);
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'value') el.value = value;
    else if (key === 'checked') el.checked = !!value;
    else if (key === 'selected') el.selected = !!value;
    else el.setAttribute(key, value === true ? '' : String(value));
  }
  append(el, kids);
  return el;
}

function append(el, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
}

export function clear(el, ...kids) { el.replaceChildren(); append(el, kids); return el; }

const PATHS = {
  plus: ['M12 5v14M5 12h14'],
  download: ['M12 4v11', 'M7 10l5 5 5-5', 'M5 20h14'],
  down: ['M6 9l6 6 6-6'],
  x: ['M6 6l12 12M18 6L6 18'],
  search: ['M20 20l-3.5-3.5', 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z'],
  spark: ['M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z'],
  warn: ['M12 3l9.5 17h-19z', 'M12 10v4', 'M12 17.5v.01'],
  check: ['M5 12l5 5L20 7'],
  copy: ['M8 8h11v11H8z', 'M5 16V5h11'],
  more: ['M5 12h.01M12 12h.01M19 12h.01'],
  back: ['M19 12H5M11 6l-6 6 6 6'],
  upload: ['M12 20V9', 'M7 14l5-5 5 5', 'M5 4h14'],
  refresh: ['M20 11a8 8 0 1 0-2.3 5.7', 'M20 5v6h-6'],
  swap: ['M4 8h14l-4-4', 'M20 16H6l4 4'],
};

export function icon(name, size = 16) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  for (const [k, v] of Object.entries({ width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    'stroke-width': '2.1', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true' })) svg.setAttribute(k, v);
  for (const d of PATHS[name] || []) { const p = document.createElementNS(ns, 'path'); p.setAttribute('d', d); svg.append(p); }
  return svg;
}

// ---- formatting -------------------------------------------------------------------------
const USD = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' });
const NUM2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const INT = new Intl.NumberFormat('en-US');
export const fmt = {
  usd: (v) => (v === null || v === undefined ? '–' : USD.format(v)),
  usd0: (v) => (v === null || v === undefined ? '–' : USD.format(v).replace(/\.00$/, '')),
  local: (v, cur) => (v === null || v === undefined ? '–' : `${NUM2.format(v)} ${cur || ''}`.trim()),
  int: (v) => (v === null || v === undefined ? '–' : INT.format(v)),
  pct: (v) => `${v > 0 ? '+' : v < 0 ? '−' : '±'}${Math.abs(v)}%`,
  cap: (v) => { const t = String(v || ''); return t.charAt(0).toUpperCase() + t.slice(1); },
  when(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    const yesterday = new Date(now.getTime() - 864e5).toDateString() === d.toDateString();
    const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (sameDay) return `Today ${time}`;
    if (yesterday) return `Yesterday ${time}`;
    return d.toLocaleDateString([], { day: 'numeric', month: 'short' });
  },
  date(iso) {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleString([], { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  },
  minutes(m) {
    if (!m) return '–';
    const hrs = Math.floor(m / 60);
    if (hrs >= 10) return `~${Math.round(m / 60)} h`; // long runs: minutes are noise and do not fit
    return hrs ? `~${hrs} h ${m % 60} m` : `~${m} min`;
  },
};
export const safeUrl = (u) => (typeof u === 'string' && /^https?:\/\//i.test(u) ? u : null);
export const PLATFORM_NAMES = { amazon: 'Amazon', ebay: 'eBay', zalando: 'Zalando', mediamarkt: 'MediaMarkt' };
export const platformName = (p) => PLATFORM_NAMES[p] || fmt.cap(p);

export function median(values) {
  if (!values.length) return null;
  const s = values.slice().sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export function debounce(fn, ms) {
  let t = null;
  const wrapped = (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  wrapped.flush = (...args) => { clearTimeout(t); fn(...args); };
  wrapped.cancel = () => clearTimeout(t);
  return wrapped;
}

// ---- toasts, dialogs -----------------------------------------------------------------------
export function toast(message, kind = '') {
  const box = document.getElementById('toasts');
  const el = h('div', { class: `toast ${kind}`, text: message });
  box.append(el);
  setTimeout(() => el.remove(), kind === 'bad' ? 7000 : 3500);
}

export function dialog({ title, body, actions = [], wide = false }) {
  const dlg = h('dialog', { 'aria-label': title });
  if (wide) dlg.style.width = 'min(1100px, calc(100vw - 32px))';
  const close = () => { dlg.close(); dlg.remove(); };
  const foot = actions.length ? h('div', { class: 'dlg-foot' }, actions.map((a) => h('button', {
    type: 'button', class: `btn ${a.primary ? 'primary' : ''} ${a.danger ? 'danger' : ''}`,
    onclick: async (e) => { if (a.onclick) { const keep = await a.onclick(e, close); if (keep === true) return; } close(); },
  }, a.label))) : null;
  dlg.append(h('div', { class: 'dlg' },
    h('div', { class: 'dlg-head' }, h('h2', { class: 'card-title', text: title }),
      h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Close', onclick: close }, icon('x'))),
    h('div', { class: 'dlg-body' }, body), foot));
  dlg.addEventListener('cancel', (e) => { e.preventDefault(); close(); });
  document.body.append(dlg);
  dlg.showModal();
  return { dlg, close };
}

export function confirmDialog(title, message, confirmLabel = 'Delete', danger = true) {
  return new Promise((resolve) => {
    let answered = false;
    const { dlg } = dialog({ title, body: h('p', { text: message }), actions: [
      { label: 'Cancel', onclick: () => { answered = true; resolve(false); } },
      { label: confirmLabel, primary: !danger, danger, onclick: () => { answered = true; resolve(true); } },
    ] });
    dlg.addEventListener('close', () => { if (!answered) resolve(false); });
  });
}

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall back below */ }
  const area = h('textarea', { style: { position: 'fixed', opacity: '0' } });
  area.value = text;
  document.body.append(area);
  area.select();
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  area.remove();
  return ok;
}

// ---- shared pieces ---------------------------------------------------------------------------
export const STATUS_PILL = {
  running: 'info', paused: 'info', completed: 'ok', reviewed: 'ok', attention: 'warn', draft: '', failed: 'bad',
};

export function stepsNav(steps, base, current) {
  return h('nav', { class: 'steps', 'aria-label': 'Research steps' }, steps.map((s, i) => {
    const isCurrent = s.key === current;
    const done = s.state === 'done';
    const locked = s.state === 'locked';
    const inner = [
      h('span', { class: `step-dot ${isCurrent ? 'current' : done ? 'done' : ''}` }, done && !isCurrent ? '✓' : String(i + 1)),
      h('span', { class: 'step-text' }, h('b', { text: s.label }), h('span', { text: s.sub || '' })),
    ];
    if (locked || !base) return h('span', { class: `step ${locked ? 'locked' : ''}`, 'aria-current': isCurrent ? 'step' : null, 'aria-disabled': 'true' }, inner);
    return h('a', { href: `${base}/${s.key}`, 'aria-current': isCurrent ? 'step' : null }, inner);
  }));
}

export function banner(kind, ...content) {
  return h('div', { class: `banner ${kind}`, role: kind === 'bad' ? 'alert' : null }, kind === 'warn' || kind === 'bad' ? icon('warn', 18) : null,
    h('div', { class: 'grow' }, content));
}

export function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = h('a', { href: url, download: name, style: { display: 'none' } });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
