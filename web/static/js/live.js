// Cotações ao vivo: recebe do servidor por SSE (/api/stream), com fallback para consulta periódica,
// e atualiza na hora os elementos marcados com data-l* em qualquer tela:
//   data-lp="TICKER" [data-basis=ask|bid]                       -> preço
//   data-lmeta="TICKER"                                          -> fonte, book (compra × venda), atraso
//   data-lpnl="TICKER" data-qty data-avg data-side=LONG|SHORT [data-invested] [data-fmt=pct] [data-basis]
//   data-ldrift="TICKER" data-entry data-side=BUY|SELL [data-basis] -> variação vs. entrada do analista
//   data-lret="TICKER" data-entry data-side=BUY|SELL               -> retorno do sinal agora
//   data-lsum="pnl|mv"  soma os elementos data-lsum-src (P&L / valor de mercado) da tela
import { get, post } from './api.js';
import * as f from './format.js';
import { emit, state } from './state.js';
import { esc } from './ui.js';

export const quotes = new Map();
let feed = null;
let es = null;
let mode = 'sse';
let lastMsg = 0;
let failures = 0;
let pollTimer = null;
let hiddenTimer = null;
let started = false;

const STALE_MS = 45000;
const POLL_MS = 3000;
const TONES = ['gain', 'loss', 'muted'];

// ---------------------------------------------------------------- conexão
function handle(d) {
  lastMsg = Date.now();
  failures = 0;
  if (d.feed) feed = d.feed;
  if (d.full) quotes.clear();
  Object.entries(d.quotes || {}).forEach(([t, q]) => quotes.set(t, q));
  state.quotesFeed = feed;
  applyLive();
  renderChip();
  emit('quotes', d);
}

function connect() {
  if (es || pollTimer || document.hidden) return;
  if (!('EventSource' in window) || mode === 'poll') { startPolling(); return; }
  es = new EventSource('/api/stream');
  es.addEventListener('quotes', (e) => handle(JSON.parse(e.data)));
  es.addEventListener('ping', (e) => handle({ ...JSON.parse(e.data), quotes: {} }));
  es.onerror = () => {
    // CONNECTING = o servidor encerrou o stream e o navegador reconecta sozinho; CLOSED = recusado (login, proxy...)
    if (es && es.readyState === EventSource.CLOSED) {
      es = null;
      failures += 1;
      if (failures >= 3) startPolling(); else setTimeout(connect, 5000);
    }
  };
}

function startPolling() {
  mode = 'poll';
  if (es) { es.close(); es = null; }
  if (pollTimer || document.hidden) return;
  const poll = () => get('/api/quotes').then(handle).catch(() => {});
  poll();
  pollTimer = setInterval(poll, POLL_MS);
}

function pause() {
  if (es) { es.close(); es = null; }
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

function watchdog() {
  renderChip();
  if (document.hidden || mode !== 'sse' || !es) return;
  if (Date.now() - lastMsg > STALE_MS) { // proxy segurando o stream (buffer): tenta de novo e, depois, consulta periódica
    es.close();
    es = null;
    failures += 1;
    if (failures >= 3) startPolling(); else connect();
  }
}

export function startLive() {
  if (started) return;
  started = true;
  lastMsg = Date.now();
  connect();
  setInterval(watchdog, 10000);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      hiddenTimer = setTimeout(pause, 60000); // libera a conexão do servidor com a aba em segundo plano
    } else {
      clearTimeout(hiddenTimer);
      if (mode === 'poll') startPolling(); else connect();
    }
  });
}

/** Acompanha ativos abertos na tela (boleta, modal) por alguns minutos e busca a cotação na hora. */
export function watch(tickers) {
  const list = (tickers || []).filter(Boolean);
  if (!list.length) return Promise.resolve();
  return post('/api/quotes/watch', { tickers: list }).then(handle).catch(() => {});
}

// ---------------------------------------------------------------- consulta
export function streamOk() {
  return Date.now() - lastMsg < STALE_MS;
}

export function isLive(q) {
  return !!(q && q.live && feed && feed.state === 'live' && streamOk());
}

export function quoteOf(ticker) {
  return quotes.get(ticker) || null;
}

// MT5 parado: não sobrepõe o que o servidor mostrou (vale a reserva do TradingFloors)
function usable(q) {
  return !!q && (q.realtime ? isLive(q) : true);
}

function priceFor(q, basis) {
  if (!usable(q)) return null;
  if (basis === 'ask' && q.ask && isLive(q)) return q.ask;
  if (basis === 'bid' && q.bid && isLive(q)) return q.bid;
  return q.price;
}

// ---------------------------------------------------------------- apresentação
export function livePnlAttrs(p) {
  return `data-lpnl="${esc(p.ticker)}" data-qty="${p.quantity}" data-avg="${p.avg_price}" data-side="${p.side}" data-invested="${p.invested || ''}"`;
}

export function quoteMetaHtml(q, { fallbackSource = null, fallbackAt = null } = {}) {
  if (!q) {
    if (fallbackSource === 'mt5' || fallbackSource === 'brapi') return `<span class="qmeta"><span class="qdot warn"></span>${esc(fallbackSource === 'mt5' ? 'MT5' : 'brapi')}${fallbackAt ? ` · ${esc(f.ago(fallbackAt))}` : ''}</span>`;
    if (fallbackSource === 'manual') return `<span class="qmeta"><span class="qdot"></span>manual${fallbackAt ? ` · ${esc(f.ago(fallbackAt))}` : ''}</span>`;
    if (fallbackSource === 'tradingfloors') return '<span class="qmeta" title="Preço informado pelo TradingFloors — sem horário, atraso desconhecido"><span class="qdot"></span>preço do TradingFloors (atraso desconhecido)</span>';
    return '';
  }
  const live = isLive(q);
  const book = q.bid || q.ask ? `<span class="qbook" title="Melhor oferta de compra × melhor oferta de venda">${f.price(q.bid)} × ${f.price(q.ask)}</span>` : '';
  let label;
  if (live) label = `<span class="qdot live"></span>ao vivo`;
  else if (q.realtime) return `<span class="qmeta" title="Sem cotação ao vivo — vale o preço do TradingFloors (ou o último conhecido)"><span class="qdot warn"></span>${esc(q.source === 'mt5' ? 'MT5' : q.source)} parado · reserva: TradingFloors</span>`;
  else {
    const when = q.time ? f.time(q.time) : null;
    return `<span class="qmeta" title="Cotação atrasada da ${esc(q.source)} (plano gratuito: renovada a cada ~${q.delay_minutes || 30} min)"><span class="qdot warn"></span>${esc(q.source)}${when ? ` · cotação das ${esc(when)}` : ` · atraso ~${q.delay_minutes || '?'} min`}${q.change_pct !== null && q.change_pct !== undefined ? ` <span class="${f.tone(q.change_pct)}">${f.pct(q.change_pct)} dia</span>` : ''}</span>`;
  }
  const chg = q.change_pct !== null && q.change_pct !== undefined ? ` <span class="${f.tone(q.change_pct)}">${f.pct(q.change_pct)} dia</span>` : '';
  return `<span class="qmeta">${label}${book ? ` · ${book}` : ''}${chg}</span>`;
}

function setText(el, text, tone) {
  if (el.textContent !== text) {
    const prev = Number(el.dataset.n);
    el.textContent = text;
    const now = Number(el.dataset.nNext);
    if (Number.isFinite(prev) && Number.isFinite(now) && prev !== now) {
      el.classList.remove('flash-up', 'flash-down');
      void el.offsetWidth; // reinicia a animação
      el.classList.add(now > prev ? 'flash-up' : 'flash-down');
    }
  }
  if (el.dataset.nNext !== undefined) el.dataset.n = el.dataset.nNext;
  if (tone !== undefined) {
    TONES.forEach((t) => el.classList.remove(t));
    if (tone) el.classList.add(tone);
  }
}

export function applyLive(root = document) {
  if (!quotes.size) return;
  root.querySelectorAll('[data-lp]').forEach((el) => {
    const px = priceFor(quotes.get(el.dataset.lp), el.dataset.basis);
    if (px === null || px === undefined) return;
    el.dataset.nNext = px;
    setText(el, f.brl(px));
  });
  root.querySelectorAll('[data-lmeta]').forEach((el) => {
    const q = quotes.get(el.dataset.lmeta);
    if (q) el.innerHTML = quoteMetaHtml(q);
  });
  root.querySelectorAll('[data-lpnl]').forEach((el) => {
    const px = priceFor(quotes.get(el.dataset.lpnl), el.dataset.basis);
    if (px === null || px === undefined) return;
    const qty = Number(el.dataset.qty);
    const avg = Number(el.dataset.avg);
    const pnl = (el.dataset.side === 'SHORT' ? avg - px : px - avg) * qty;
    el.dataset.v = pnl;
    el.dataset.mv = px * qty;
    if (el.dataset.fmt === 'pct') {
      const inv = Number(el.dataset.invested) || avg * qty;
      const pct = inv ? (pnl / inv) * 100 : null;
      setText(el, f.pct(pct), f.tone(pct));
    } else {
      el.dataset.nNext = pnl;
      setText(el, f.brl(pnl, { sign: true }), f.tone(pnl));
    }
  });
  root.querySelectorAll('[data-ldrift]').forEach((el) => {
    const px = priceFor(quotes.get(el.dataset.ldrift), el.dataset.basis);
    const entry = Number(el.dataset.entry);
    if (!px || !entry) return;
    const drift = (px / entry - 1) * 100;
    const adverse = el.dataset.side === 'SELL' ? -drift : drift;
    setText(el, f.pct(drift), adverse > 0.5 ? 'loss' : adverse < -0.5 ? 'gain' : 'muted');
  });
  root.querySelectorAll('[data-lret]').forEach((el) => {
    const q = quotes.get(el.dataset.lret);
    const entry = Number(el.dataset.entry);
    if (!usable(q) || !entry) return;
    const ret = (el.dataset.side === 'SELL' ? -1 : 1) * (q.price / entry - 1) * 100;
    setText(el, f.pct(ret), f.tone(ret));
  });
  root.querySelectorAll('[data-lsum]').forEach((el) => {
    const key = el.dataset.lsum === 'mv' ? 'mv' : 'v';
    let total = 0;
    let any = false;
    root.querySelectorAll('[data-lsum-src]').forEach((src) => {
      const v = Number(src.dataset[key]);
      if (Number.isFinite(v)) { total += v; any = true; }
    });
    if (!any) return;
    el.dataset.nNext = total;
    setText(el, f.brl(total, { sign: key === 'v' }), key === 'v' ? f.tone(total) : undefined);
  });
}

// ---------------------------------------------------------------- chip da barra superior
export function quotesChipHtml(fd = feed || state.status?.quotes) {
  if (!fd) return '';
  const stale = started && !streamOk();
  let dot = '';
  let label = 'TradingFloors';
  let sub = 'atraso desconhecido';
  if (stale && fd.provider !== 'off') { dot = 'warn pulse'; label = 'reconectando…'; sub = ''; }
  else if (fd.state === 'live') { dot = 'ok pulse'; label = `ao vivo`; sub = `${fd.label} · ${fd.watching} ativo(s)`; }
  else if (fd.state === 'delayed') { dot = 'warn'; label = 'atrasadas'; sub = 'brapi (ações, ~30 min) · TradingFloors (opções)'; }
  else if (fd.state === 'error' && fd.realtime) { dot = 'warn'; label = 'reserva'; sub = `${fd.label} indisponível · ${fd.brapi ? 'brapi + ' : ''}TradingFloors`; }
  else if (fd.state === 'error') { dot = 'warn'; label = 'TradingFloors'; sub = `${fd.label} indisponível`; }
  else if (fd.state === 'starting') { dot = 'warn pulse'; label = 'conectando…'; sub = fd.label; }
  return `<span class="chip chip-button" data-go="configuracoes" data-qchip title="${esc(fd.message || 'Cotações')}"><span class="dot ${dot}"></span><strong>Cotações: ${esc(label)}</strong>${sub ? `<span class="hide-md">${esc(sub)}</span>` : ''}</span>`;
}

function renderChip() {
  const el = document.querySelector('[data-qchip]');
  if (el) el.outerHTML = quotesChipHtml();
}
