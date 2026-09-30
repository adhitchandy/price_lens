// Talks to the local server. Every change carries the X-PI-App header (see server.py).
import { download } from './dom.js';

async function request(method, path, body) {
  const options = { method, headers: { 'X-PI-App': '1' } };
  if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, options);
  } catch (err) {
    throw new Error('The app server is not running. Start it again with start_app.bat.');
  }
  const type = res.headers.get('Content-Type') || '';
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    if (type.includes('json')) {
      try { message = (await res.json()).error || message; } catch (e) { /* keep status text */ }
    }
    const err = new Error(message);
    err.status = res.status;
    throw err;
  }
  if (type.includes('json')) return res.json();
  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
  return { blob, name: match ? decodeURIComponent(match[1]) : 'download' };
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body = {}) => request('POST', path, body),
  put: (path, body = {}) => request('PUT', path, body),
  del: (path) => request('DELETE', path),
  async file(method, path, body) {
    const result = await request(method, path, body);
    download(result.blob, result.name);
    return result;
  },
};

export const enc = encodeURIComponent;

let metaPromise = null;
export function getMeta(fresh = false) {
  if (!metaPromise || fresh) metaPromise = api.get('/api/meta').catch((err) => { metaPromise = null; throw err; });
  return metaPromise;
}
