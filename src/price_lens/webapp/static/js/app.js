// App shell: routing (#/…), theme switch, the "running" dot in the sidebar.
import { api, getMeta } from './api.js';
import { clear, h, toast } from './dom.js';
import * as researches from './views/researches.js';
import * as plan from './views/plan.js';
import * as research from './views/research.js';
import * as check from './views/check.js';
import * as storefronts from './views/storefronts.js';
import * as settings from './views/settings.js';
import * as rates from './views/rates.js';

const view = document.getElementById('view');
let cleanup = null;
let routeToken = 0;

const ROUTES = [
  [/^\/?$/, 'researches', () => researches.render(view)],
  [/^\/new$/, 'new', newResearch],
  [/^\/draft\/([\w-]+)$/, 'new', (m) => plan.render(view, m[1])],
  [/^\/r\/([\w-]+)(?:\/(\w+))?$/, 'researches', (m) => research.render(view, m[1], m[2] || null)],
  [/^\/check\/([\w-]+)$/, 'storefronts', (m, q) => check.render(view, m[1], q.get('draft'))],
  [/^\/storefronts$/, 'storefronts', () => storefronts.render(view)],
  [/^\/fx$/, 'fx', () => rates.render(view)],
  [/^\/settings$/, 'settings', () => settings.render(view)],
];

async function newResearch() {
  try {
    const draft = await api.post('/api/drafts', {});
    location.replace(`#/draft/${draft.id}`);
  } catch (err) {
    toast(err.message, 'bad');
  }
  return null;
}

async function route() {
  const token = ++routeToken;
  if (typeof cleanup === 'function') {
    try { await cleanup(); } catch (e) { /* ignore */ }
  }
  cleanup = null;
  const raw = location.hash.replace(/^#/, '') || '/';
  const [path, query] = raw.split('?');
  const params = new URLSearchParams(query || '');
  for (const [pattern, nav, handler] of ROUTES) {
    const match = path.match(pattern);
    if (!match) continue;
    document.querySelectorAll('.nav a').forEach((a) => a.toggleAttribute('aria-current', false));
    const link = document.querySelector(`.nav a[data-nav="${nav}"]`);
    if (link) link.setAttribute('aria-current', 'page');
    view.classList.remove('wide');
    clear(view, h('p', { class: 'loading', text: 'Loading…' }));
    try {
      const result = await handler(match, params);
      if (token === routeToken) cleanup = result; else if (typeof result === 'function') result();
    } catch (err) {
      if (token !== routeToken) return;
      clear(view, h('div', { class: 'empty' }, h('h2', { text: 'Something went wrong' }),
        h('p', { text: err.message }), h('a', { class: 'btn', href: '#/' }, 'Back to researches')));
    }
    view.focus({ preventScroll: true });
    window.scrollTo(0, 0);
    return;
  }
  location.replace('#/');
}

// ---- theme ------------------------------------------------------------------------------------
function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  try { localStorage.setItem('pi-theme', theme); } catch (e) { /* storage blocked */ }
  document.querySelectorAll('[data-theme-set]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.themeSet === theme)));
}
document.querySelectorAll('[data-theme-set]').forEach((b) => b.addEventListener('click', () => setTheme(b.dataset.themeSet)));
setTheme(document.documentElement.getAttribute('data-theme') || 'system');

// ---- running indicator ---------------------------------------------------------------------------
async function pollActive() {
  try {
    const data = await api.get('/api/researches');
    document.getElementById('live-dot').hidden = !data.active.length;
  } catch (e) { /* server may be restarting */ }
}
setInterval(pollActive, 10000);
pollActive();

getMeta().then((meta) => { document.getElementById('output-dir').textContent = meta.output_dir; }).catch(() => {});

window.addEventListener('hashchange', route);
route();
