// Notificações do navegador (Notification API) + som
import { state } from './state.js';

const LAST_KEY = 'copiloto.lastAlertId';
const NOTIFY_KINDS = new Set(['new_signal', 'exit_pending', 'stop_hit', 'target_hit', 'reminder', 'expiry']);

export function permission() {
  return 'Notification' in window ? Notification.permission : 'unsupported';
}

export async function requestPermission() {
  if (!('Notification' in window)) return 'unsupported';
  return Notification.requestPermission();
}

let memLast = null; // fallback quando o localStorage não está disponível
function readLast() {
  try {
    const v = localStorage.getItem(LAST_KEY);
    if (v !== null) return Number(v);
  } catch { /* sem storage */ }
  return memLast;
}
function writeLast(id) {
  memLast = id;
  try { localStorage.setItem(LAST_KEY, String(id)); } catch { /* sem storage */ }
}

let audioCtx;
export function beep(kind = 'new_signal') {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const notes = kind === 'exit_pending' || kind === 'stop_hit' ? [660, 440] : [523, 784];
    notes.forEach((f, i) => {
      const o = audioCtx.createOscillator();
      const g = audioCtx.createGain();
      o.type = 'sine';
      o.frequency.value = f;
      const t = audioCtx.currentTime + i * 0.16;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.18, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.15);
      o.connect(g).connect(audioCtx.destination);
      o.start(t);
      o.stop(t + 0.16);
    });
  } catch { /* áudio indisponível */ }
}

// Chamado quando /api/status indica um last_id maior que o já visto
export function handleNewAlerts(items, { onClick } = {}) {
  const last = readLast() ?? 0;
  const fresh = items.filter((a) => a.id > last).sort((a, b) => a.id - b.id);
  if (!fresh.length) return [];
  writeLast(Math.max(...fresh.map((a) => a.id)));

  const prefs = state.prefs?.alerts || {};
  const important = fresh.filter((a) => NOTIFY_KINDS.has(a.kind));
  if (important.length && prefs.sound !== false) beep(important[important.length - 1].kind);
  if (important.length && prefs.browser !== false && permission() === 'granted') {
    important.slice(-4).forEach((a) => {
      try {
        const n = new Notification(a.title, { body: a.body || '', tag: `copiloto-${a.id}`, icon: document.querySelector('link[rel=icon]')?.href });
        n.onclick = () => { window.focus(); onClick && onClick(a); n.close(); };
      } catch { /* alguns navegadores exigem service worker */ }
    });
  }
  return important;
}

// Na primeira visita, considera vistos os alertas que já existiam (não notifica histórico)
export function initLastSeen(lastId) {
  const cur = readLast();
  if (cur === null || cur > (lastId || 0)) writeLast(lastId || 0); // banco recriado: reinicia a contagem
}
