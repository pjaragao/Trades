// Shell do Copiloto: navegação, barra superior, polling de status e alertas
import { get, post } from './api.js';
import * as f from './format.js';
import { emit, on, state } from './state.js';
import { handleNewAlerts, initLastSeen } from './notify.js';
import { quotesChipHtml, startLive } from './live.js';
import { closeAllModals, esc, icon, toast, toastError } from './ui.js';
import { openSignalModal } from './components/signal_modal.js';

import today from './pages/today.js';
import signals from './pages/signals.js';
import portfolio from './pages/portfolio.js';
import results from './pages/results.js';
import ir from './pages/ir.js';
import lab from './pages/lab.js';
import robos from './pages/robos.js';
import settings from './pages/settings.js';

const ROUTES = [
  { path: 'hoje', label: 'Hoje', icon: 'today', page: today },
  { path: 'sinais', label: 'Sinais', icon: 'signals', page: signals },
  { path: 'carteira', label: 'Carteira', icon: 'wallet', page: portfolio },
  { path: 'resultados', label: 'Resultados', icon: 'chart', page: results },
  { path: 'ir', label: 'IR', longLabel: 'Notas e IR', icon: 'receipt', page: ir },
  { path: 'laboratorio', label: 'Laboratório', icon: 'flask', page: lab, sep: true, desktopOnly: true },
  { path: 'robos', label: 'Robôs B3', longLabel: 'Robôs & Regimes (YouTube Lab)', icon: 'brain', page: robos, desktopOnly: true },
  { path: 'configuracoes', label: 'Config.', longLabel: 'Configurações', icon: 'settings', page: settings },
];

const STATUS_MS = 15000;
let unmount = null;
let mountToken = 0;

// ---------------------------------------------------------------- navegação
function renderNav() {
  const link = (r) => `<a class="nav-link" href="#/${r.path}" data-route="${r.path}">${icon(r.icon)}<span class="nav-label">${esc(r.longLabel || r.label)}</span><span class="nav-badge" data-badge="${r.path}" hidden></span></a>`;
  document.getElementById('nav-side').innerHTML = ROUTES.map((r) => (r.sep ? '<div class="nav-sep"></div>' : '') + link(r)).join('');
  document.getElementById('nav-bottom').innerHTML = ROUTES.filter((r) => !r.desktopOnly).map((r) => `<a class="nav-link" href="#/${r.path}" data-route="${r.path}" style="position:relative">${icon(r.icon)}<span class="nav-label">${esc(r.label)}</span><span class="nav-badge" data-badge="${r.path}" hidden></span></a>`).join('');
}

function parseHash() {
  const h = location.hash.replace(/^#\/?/, '');
  const [path, query] = h.split('?');
  return { path: path || 'hoje', params: new URLSearchParams(query || '') };
}

async function route() {
  const { path, params } = parseHash();
  const r = ROUTES.find((x) => x.path === path) || ROUTES[0];
  document.querySelectorAll('[data-route]').forEach((a) => a.classList.toggle('active', a.dataset.route === r.path));
  document.getElementById('topbar-title').textContent = r.longLabel || r.label;
  document.title = `${r.longLabel || r.label} · Copiloto de Trades`;
  if (unmount) { try { unmount(); } catch { /* ignore */ } unmount = null; }
  closeAllModals();
  const view = document.getElementById('view');
  const root = document.createElement('div');
  view.replaceChildren(root);
  const token = ++mountToken;
  try {
    const cleanup = await r.page.mount(root, params);
    if (token === mountToken) unmount = typeof cleanup === 'function' ? cleanup : null;
    else if (typeof cleanup === 'function') cleanup();
  } catch (e) {
    console.error(e);
    root.innerHTML = `<div class="banner danger">${icon('alert')}<div class="grow">Erro ao abrir a tela: ${esc(e.message)}</div></div>`;
  }
  view.scrollTop = 0;
  window.scrollTo(0, 0);
}

// ---------------------------------------------------------------- barra superior
function monitorChip(m) {
  const map = {
    live: ['ok pulse', 'Ao vivo', `atualizado ${f.secondsAgo(m.age_seconds)}`],
    degraded: ['warn', 'Instável', m.last_error || ''],
    stale: ['warn', 'Desatualizado', `último dado ${f.secondsAgo(m.age_seconds)}`],
    offline: ['bad', 'Sem conexão', m.last_error || 'TradingFloors indisponível'],
    no_credentials: ['bad', 'Sem credenciais', 'Configure config/.env'],
    starting: ['warn pulse', 'Conectando…', 'sincronizando sinais'],
  };
  const [dot, label, sub] = map[m.state] || map.starting;
  return `<span class="chip chip-button" data-go="configuracoes" title="${esc(m.last_error || sub)}"><span class="dot ${dot}"></span><strong>Sinais: ${esc(label)}</strong><span class="hide-md">${esc(sub)}</span></span>`;
}

function marketChip(mk) {
  const dot = mk.phase === 'open' ? 'ok' : mk.phase === 'closed' ? '' : 'warn';
  return `<span class="chip" title="${esc(mk.detail)}"><span class="dot ${dot}"></span><strong>${esc(mk.label)}</strong><span>${esc(mk.detail)}</span></span>`;
}

function execChip(ex) {
  if (!ex || ex.mode === 'off') return '';
  const live = ex.mode === 'live';
  const dot = !ex.can_send ? 'bad' : ex.armed ? (live ? 'bad pulse' : 'warn pulse') : (live ? 'warn' : 'ok');
  const label = `${live ? 'MT5 real' : 'Simulação'}${ex.armed ? ' · automação armada' : ''}`;
  return `<span class="chip chip-button" data-go="configuracoes" title="${esc(ex.reason || 'Execução de ordens')}"><span class="dot ${dot}"></span><strong>${esc(label)}</strong></span>`;
}

function renderTopbar(st) {
  const p = st.portfolio;
  document.getElementById('topbar-chips').innerHTML = `
    ${marketChip(st.market)}
    ${monitorChip(st.monitor)}
    ${quotesChipHtml(state.quotesFeed || st.quotes)}
    ${execChip(st.execution)}
    <span class="chip chip-button" data-go="carteira" title="Capital livre / total"><span>Capital</span><strong class="mono">${f.brl(p.free, { dec: 0 })}</strong><span class="faint">/ ${f.brl(p.capital, { dec: 0 })}</span></span>
    <span class="chip chip-button" data-go="resultados" title="Resultado realizado hoje · P&L em aberto"><span>Hoje</span><strong class="mono ${f.tone(p.realized_today)}">${f.brl(p.realized_today, { sign: true, dec: 0 })}</strong><span class="faint">aberto</span><strong class="mono ${f.tone(p.unrealized_pnl)}">${f.brl(p.unrealized_pnl, { sign: true, dec: 0 })}</strong></span>`;
  const mon = st.monitor.state;
  const monDot = mon === 'live' ? 'ok' : (mon === 'offline' || mon === 'no_credentials') ? 'bad' : 'warn';
  document.getElementById('topbar-mini').innerHTML = `<span class="dot ${monDot}" title="Monitor de sinais"></span><span>${mon === 'live' ? 'ao vivo' : 'sinais: ' + esc(mon)}</span><span class="faint">·</span><span class="dot ${st.market.phase === 'open' ? 'ok' : st.market.phase === 'closed' ? '' : 'warn'}"></span><span>${esc(st.market.label)}</span>`;
  const bell = document.getElementById('btn-bell');
  bell.innerHTML = `${icon('bell', 'icon-lg')}${st.alerts.unread ? `<span class="count">${st.alerts.unread > 99 ? '99+' : st.alerts.unread}</span>` : ''}`;
  const foot = document.getElementById('sidebar-foot');
  foot.innerHTML = `<div class="row"><span class="dot ${st.monitor.state === 'live' ? 'ok' : st.monitor.state === 'offline' || st.monitor.state === 'no_credentials' ? 'bad' : 'warn'}"></span><strong>Monitor ${st.monitor.state === 'live' ? 'ativo' : 'com problema'}</strong></div>
    <div class="mt-2">Execução manual no Home Broker. MT5 ${st.execution.enabled ? '<span class="warn-text">ligado</span>' : 'desligado'}.</div>`;
}

function setBadge(path, n, warn = false) {
  document.querySelectorAll(`[data-badge="${path}"]`).forEach((b) => {
    b.hidden = !n;
    b.textContent = n > 99 ? '99+' : String(n);
    b.classList.toggle('warn', warn);
  });
}

// ---------------------------------------------------------------- alertas
const KIND_ICON = {
  new_signal: ['zap', 'action'], exit_pending: ['exit', 'warn'], reminder: ['snooze', 'action'], stop_hit: ['alert', 'danger'],
  target_hit: ['check', 'action'], expiry: ['clock', 'danger'], signal_closed: ['info', ''], order_filled: ['check', 'action'],
  signal_executed: ['check', 'action'],
  order_rejected: ['alert', 'danger'], order_problem: ['alert', 'danger'], auto_order: ['zap', 'warn'], auto_blocked: ['shield', ''],
};

async function openAlerts() {
  const pop = document.getElementById('alerts-popover');
  if (!pop.hidden) { pop.hidden = true; return; }
  pop.hidden = false;
  pop.innerHTML = '<div class="loading-block"><span class="spinner"></span></div>';
  try {
    const data = await get('/api/alerts?limit=40');
    pop.innerHTML = `
      <div class="card-head"><h3>Alertas</h3>${data.unread ? '<button class="btn btn-sm btn-ghost" data-read-all>Marcar todos como lidos</button>' : ''}</div>
      ${data.items.length ? data.items.map((a) => {
        const [ic, cls] = KIND_ICON[a.kind] || ['info', ''];
        return `<div class="alert-item ${a.read_at ? '' : 'unread'}" data-alert="${a.id}" data-signal="${esc(a.signal_id || '')}" data-kind="${esc(a.kind)}">
          <div class="alert-icon ${cls}">${icon(ic)}</div>
          <div><div class="alert-title">${esc(a.title)}</div><div class="alert-body">${esc(a.body || '')}</div><div class="alert-time">${esc(f.ago(a.created_at))}</div></div></div>`;
      }).join('') : '<div class="empty compact"><p>Nenhum alerta ainda.</p></div>'}`;
  } catch (e) {
    pop.innerHTML = `<div class="card-body"><div class="note danger">${esc(e.message)}</div></div>`;
  }
}

function goToAlert(a) {
  if (['exit_pending', 'stop_hit', 'target_hit', 'expiry', 'order_filled', 'order_rejected', 'order_problem', 'auto_order', 'auto_blocked'].includes(a.kind)) location.hash = '#/carteira';
  else if (a.signal_id) { location.hash = '#/hoje'; openSignalModal(a.signal_id); }
}

// ---------------------------------------------------------------- polling
let lastAlertId = null;
let polling = false;
async function pollStatus() {
  if (polling) return;
  polling = true;
  try {
    const st = await get('/api/status');
    state.status = st;
    renderTopbar(st);
    setBadge('carteira', st.portfolio.exit_pending, true);
    const prev = lastAlertId;
    lastAlertId = st.alerts.last_id;
    if (prev === null) {
      initLastSeen(st.alerts.last_id);
    } else if (st.alerts.last_id > prev) {
      const fresh = await get(`/api/alerts?after_id=${prev}&limit=20`);
      const important = handleNewAlerts(fresh.items, { onClick: goToAlert });
      important.forEach((a) => toast(`${a.title}${a.body ? ' — ' + a.body : ''}`, a.kind === 'exit_pending' || a.kind === 'stop_hit' ? 'warning' : 'info', 8000));
      if (fresh.items.length) setTimeout(() => emit('data-changed'), 0);
    }
    emit('status-tick', st);
  } catch (e) {
    document.getElementById('topbar-chips').innerHTML = `<span class="chip"><span class="dot bad"></span><strong>Servidor local fora do ar</strong><span>${esc(e.message)}</span></span>`;
  } finally {
    polling = false;
  }
}

async function pollTodayBadge() {
  try {
    const t = await get('/api/today');
    setBadge('hoje', t.exits_pending.length + t.new_signals.length + t.reminders.length, t.exits_pending.length > 0);
  } catch { /* silencioso */ }
}

// ---------------------------------------------------------------- boot
async function boot() {
  renderNav();
  document.getElementById('btn-sync').innerHTML = icon('refresh', 'icon-lg');
  try {
    const s = await get('/api/settings');
    state.prefs = s.prefs;
    state.system = s.system;
  } catch (e) { toastError(e); }

  window.addEventListener('hashchange', route);
  document.addEventListener('click', async (e) => {
    const go = e.target.closest('[data-go]');
    if (go) { location.hash = `#/${go.dataset.go}`; return; }
    const pop = document.getElementById('alerts-popover');
    const item = e.target.closest('[data-alert]');
    if (item) {
      pop.hidden = true;
      post('/api/alerts/read', { ids: [Number(item.dataset.alert)] }).then(pollStatus);
      goToAlert({ kind: item.dataset.kind, signal_id: item.dataset.signal });
      return;
    }
    if (e.target.closest('[data-read-all]')) {
      await post('/api/alerts/read', {});
      pop.hidden = true;
      pollStatus();
      return;
    }
    if (!e.target.closest('#alerts-popover') && !e.target.closest('#btn-bell')) pop.hidden = true;
  });
  document.getElementById('btn-bell').addEventListener('click', openAlerts);
  document.getElementById('btn-sync').addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>';
    try {
      const r = await post('/api/sync');
      toast(r.monitor.state === 'live' ? 'Sinais atualizados' : (r.monitor.last_error || 'Falha ao sincronizar'), r.monitor.state === 'live' ? 'success' : 'warning');
      emit('data-changed');
      pollStatus();
    } catch (err) { toastError(err); }
    btn.disabled = false;
    btn.innerHTML = icon('refresh', 'icon-lg');
  });
  on('data-changed', () => { pollTodayBadge(); pollStatus(); });

  if (!location.hash) history.replaceState(null, '', '#/hoje');
  await pollStatus();
  startLive();
  await Promise.all([route(), pollTodayBadge()]);
  setInterval(pollStatus, STATUS_MS);
  setInterval(pollTodayBadge, STATUS_MS * 2);
}

boot();
