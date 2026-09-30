// One-click "copy to clipboard" button. Runs in the app page (no iframe), so the
// clipboard API works directly; a hidden textarea is the fallback.
export default function (component) {
  const { data, parentElement } = component;
  const root = parentElement.querySelector('.pi-copy');
  if (!root) return;
  const d = data || {};
  root.__text = d.text || '';
  if (!root.__button) {
    const button = document.createElement('button');
    button.type = 'button';
    const msg = document.createElement('span');
    msg.className = 'msg';
    msg.setAttribute('role', 'status');
    root.append(button, msg);
    root.__button = button;
    root.__msg = msg;
    button.addEventListener('click', async () => {
      let ok = false;
      try { await navigator.clipboard.writeText(root.__text); ok = true; } catch (e) { ok = false; }
      if (!ok) {
        const area = document.createElement('textarea');
        area.value = root.__text; area.style.position = 'fixed'; area.style.opacity = '0';
        document.body.appendChild(area); area.select();
        try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
        area.remove();
      }
      msg.textContent = ok ? root.__hint : "Copy was blocked by the browser. Open 'Show prompt' and use its copy icon.";
      if (ok) {
        button.textContent = 'Copied';
        setTimeout(() => { button.textContent = root.__label; }, 2500);
      }
    });
  }
  root.__label = d.label || 'Copy';
  root.__hint = d.hint || 'Copied.';
  if (root.__button.textContent !== 'Copied') root.__button.textContent = root.__label;
}
