// Confirmação de envio de ordem (MT5 ou conta simulada) — um clique, você aprova.
import { post } from '../api.js';
import * as f from '../format.js';
import { emit, state } from '../state.js';
import { applyLive, quoteMetaHtml, quoteOf, watch } from '../live.js';
import { esc, icon, loading, noteList, openModal, toast } from '../ui.js';

export function executionMode() {
  return state.status?.execution || { mode: 'off', can_send: false };
}

export function sendLabel() {
  const ex = executionMode();
  return ex.mode === 'paper' ? 'Enviar (simulação)' : 'Enviar ao MT5';
}

/**
 * order: { ticker, side, quantity, limit_price, order_type, purpose: 'entry'|'exit', signal_id, cycle_id, context }
 */
export async function openOrderModal(order) {
  const m = openModal({ title: order.purpose === 'exit' ? 'Enviar ordem de saída' : 'Enviar ordem', body: loading('Conferindo conexão e riscos…') });
  let check;
  watch([order.ticker]);
  try {
    check = await post('/api/orders/check', order);
  } catch (e) {
    m.setBody(`<div class="note danger">${esc(e.message)}</div>`);
    return;
  }
  const st = check.state;
  const risk = check.risk;
  const live = st.mode === 'live';
  const health = st.health || {};
  const acct = health.account;
  const side = order.side === 'BUY' ? 'COMPRA' : 'VENDA';
  const total = (order.quantity || 0) * (order.limit_price || 0);
  const notes = [
    ...risk.blocks.map((t) => ({ level: 'danger', text: t })),
    ...risk.warnings.map((t) => ({ level: 'warning', text: t })),
  ];
  if (!st.can_send) notes.unshift({ level: 'danger', text: st.reason || 'Envio indisponível.' });

  m.setBody(`
    <div class="banner ${live ? 'danger' : 'info'}">${icon(live ? 'alert' : 'info')}<div class="grow">
      ${live ? `<strong>Ordem REAL</strong> no MetaTrader 5${acct ? ` · conta ${esc(acct.login)} (${esc(acct.company || '')})` : ''}.`
             : '<strong>Conta simulada.</strong> Nada vai para a corretora; o preenchimento usa as cotações conhecidas.'}
    </div></div>
    <div class="copy-box" style="font-size:1rem">${side} ${f.qty(order.quantity)} ${esc(order.ticker)}
${order.order_type === 'market' ? 'A MERCADO' : `LIMITE ${f.brl(order.limit_price)}`} · validade: dia
Total ≈ ${f.brl(total)}</div>
    <div class="row-between mt-3"><span class="muted">Agora: <strong data-lp="${esc(order.ticker)}" data-basis="${order.side === 'BUY' ? 'ask' : 'bid'}">—</strong></span>
      <span data-lmeta="${esc(order.ticker)}">${quoteMetaHtml(quoteOf(order.ticker))}</span></div>
    ${order.context ? `<p class="muted mt-3">${esc(order.context)}</p>` : ''}
    <div class="mt-4">${noteList(notes)}</div>
    ${health.message && !health.ok ? '' : (live && health.ok ? `<p class="hint mt-3">Conector: ${esc(health.message)}${acct && acct.balance != null ? ` · saldo ${f.brl(acct.balance)}` : ''}</p>` : '')}
  `);
  applyLive(m.el);
  const canConfirm = st.can_send && risk.ok;
  const foot = document.createElement('div');
  foot.className = 'modal-foot';
  foot.innerHTML = `<button class="btn btn-ghost" data-cancel>Cancelar</button>
    <button class="btn ${live ? 'btn-danger' : 'btn-primary'}" data-confirm ${canConfirm ? '' : 'disabled'}>${icon('check')} ${live ? 'Confirmar ordem real' : 'Confirmar simulação'}</button>`;
  m.el.appendChild(foot);
  foot.querySelector('[data-cancel]').onclick = m.close;
  foot.querySelector('[data-confirm]').onclick = async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Enviando…';
    try {
      const o = await post('/api/orders', order);
      m.close();
      const msg = o.status === 'filled' ? `Ordem executada: ${side} ${f.qty(o.filled_qty)} ${o.ticker} a ${f.brl(o.avg_fill_price)}`
        : o.status === 'rejected' ? `Ordem recusada: ${o.message || ''}` : `Ordem enviada (${o.status}). Acompanhe na Carteira.`;
      toast(msg, o.status === 'rejected' ? 'error' : 'success', 7000);
      emit('data-changed');
    } catch (err) {
      btn.disabled = false;
      btn.innerHTML = `${icon('check')} Tentar de novo`;
      m.setBody(`<div class="note danger">${icon('alert')}<span>${esc(err.message)}</span></div>`);
    }
  };
}

export function orderStatusLabel(o) {
  const map = {
    sending: ['badge-info', 'Enviando'], open: ['badge-info', 'Aberta'], partial: ['badge-warn', 'Parcial'],
    filled: ['badge-ok', 'Executada'], cancelled: ['', 'Cancelada'], rejected: ['badge-bad', 'Recusada'],
    expired: ['', 'Expirada'], error: ['badge-bad', 'Erro'], unknown: ['badge-bad', 'Sem confirmação'],
  };
  const [cls, label] = map[o.status] || ['', o.status];
  return `<span class="badge ${cls}" title="${esc(o.message || '')}">${esc(label)}</span>`;
}

export function orderLine(o) {
  return `${o.side === 'BUY' ? 'Compra' : 'Venda'} ${f.qty(o.quantity)} ${esc(o.ticker)} ${o.order_type === 'market' ? 'a mercado' : `lim. ${f.brl(o.limit_price)}`}${o.account === 'paper' ? ' · simulação' : ''}`;
}
