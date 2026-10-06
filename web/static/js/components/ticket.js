// Cartão "Boleta pronta" (novo sinal / lembrete) e cartão de "Saída pendente"
import { get, post, qs } from '../api.js';
import * as f from '../format.js';
import { emit, on } from '../state.js';
import { applyLive, quoteMetaHtml, quoteOf } from '../live.js';
import { avatar, copyText, copyableBadge, debounce, esc, icon, noteList, showMenu, closeMenus, toast, toastError } from '../ui.js';
import { openExecutionForm } from './exec_form.js';
import { executionMode, openOrderModal, orderLine, orderStatusLabel, sendLabel } from './order_modal.js';

function openOrdersHtml(list) {
  if (!list || !list.length) return '';
  return `<div class="ticket-orders">${list.map((o) => `<div class="row-between"><span>${icon('clock')} ${orderLine(o)} ${orderStatusLabel(o)}</span>
    <button class="btn btn-sm btn-ghost" data-action="cancel-order" data-order="${o.id}">Cancelar</button></div>`).join('')}</div>`;
}

const registry = new Map(); // signal_id -> {sig, ticket}

export function optionDesc(sig) {
  const parts = [];
  if (sig.asset_class === 'OPCAO') {
    const kind = sig.opcao_tipo ? String(sig.opcao_tipo).toUpperCase() : 'Opção';
    parts.push(`${kind}${sig.underlying ? ` de ${sig.underlying}` : ''}`);
    if (sig.strike) parts.push(`strike ${f.num(sig.strike)}`);
    if (sig.expiration) {
      const d = sig.days_to_expiration;
      parts.push(`vence ${f.date(sig.expiration + 'T12:00:00-03:00')}${d !== null && d !== undefined ? ` (${d} dia${d === 1 ? '' : 's'})` : ''}`);
    }
  } else {
    parts.push(f.ASSET_LABELS[sig.asset_class] || sig.tipo_ativo || '');
    if (sig.underlying && sig.underlying !== sig.ticker) parts.push(sig.underlying);
  }
  return parts.filter(Boolean).join(' · ');
}

function driftTone(ticket) {
  if (ticket.drift_pct === null || ticket.drift_pct === undefined) return 'muted';
  const adverse = ticket.side === 'BUY' ? ticket.drift_pct : -ticket.drift_pct;
  if (adverse > 0.5) return 'loss';
  if (adverse < -0.5) return 'gain';
  return 'muted';
}

const SIMILAR_HEAD = {
  same_ticker: 'Você já tem este ativo em aberto', same_direction: 'Trade semelhante em aberto', opposite: 'Posição contrária em aberto',
};

// Posição parecida (mesmo ativo-objeto): o sinal aparece, mas com o aviso de qual trade já está aberto
export function similarHtml(sig) {
  const list = sig.similar || [];
  if (!list.length) return '';
  return `<div class="ticket-similar">${list.slice(0, 3).map((x) => {
    const what = [x.kind ? `${x.kind} de ${x.underlying}` : x.underlying, x.expiration ? `vence ${f.date(x.expiration + 'T12:00:00-03:00')}` : '']
      .filter(Boolean).join(' · ');
    const who = x.trader ? `sinal de ${esc(x.trader)}${x.signal_guessed ? ' (auto)' : ''}` : 'manual';
    const pnl = x.unrealized_pct !== null && x.unrealized_pct !== undefined ? ` · <span class="${f.tone(x.unrealized_pct)}">${f.pct(x.unrealized_pct)}</span>` : '';
    const tail = x.relation === 'same_direction' ? ` Mesmo ativo-objeto e mesma direção: entrar aumenta sua exposição a ${esc(x.underlying || '')}.`
      : x.relation === 'opposite' ? ' Este sinal vai na direção oposta à sua posição.' : '';
    return `<div class="note ${x.relation === 'opposite' ? 'info' : 'warning'}">${icon(x.relation === 'opposite' ? 'info' : 'alert')}<span>
      <strong>${SIMILAR_HEAD[x.relation]}:</strong> <a href="#/carteira">${esc(x.ticker)}</a>${what ? ` (${esc(what)})` : ''}, ${who} —
      ${f.qty(x.quantity)} un · médio ${f.brl(x.avg_price)}${pnl}.${tail}
      ${x.relation === 'same_ticker' ? ` <button class="link-btn" data-action="link-position" data-position="${esc(x.cycle_id)}">É este trade — vincular</button>` : ''}</span></div>`;
  }).join('')}</div>`;
}

function totalsHtml(t) {
  return `
    <div><div class="t-lbl">Total ≈</div><div class="t-val">${f.brl(t.total)}</div></div>
    <div><div class="t-lbl">% do capital</div><div class="t-val">${t.pct_capital === null ? '—' : f.pct(t.pct_capital, { sign: false })}</div></div>
    <div><div class="t-lbl" title="${esc(t.max_loss_note || '')}">Perda máx.</div><div class="t-val ${t.max_loss ? 'loss' : 'muted'}">${t.max_loss ? f.brl(t.max_loss) : 'sem stop'}</div></div>`;
}

// Fonte do preço "agora": ao vivo (MT5/brapi) ou TradingFloors
export function quoteLine(ticker, quote, { tfPrice = null, source = null, at = null } = {}) {
  const fallbackSource = source || (tfPrice !== null && tfPrice !== undefined ? 'tradingfloors' : null);
  return `<div class="ticket-quote" data-lmeta="${esc(ticker)}">${quoteMetaHtml(quote, { fallbackSource, fallbackAt: at })}</div>`;
}

export function ticketCard(sig, { kind = 'new', isNew = false, compact = false } = {}) {
  const t = sig.ticket;
  registry.set(sig.id, { sig, ticket: t });
  const basis = sig.lado === 'SELL' ? 'bid' : 'ask';
  const sideCls = sig.lado === 'SELL' ? 'sell' : '';
  const kindLabel = { new: 'Novo sinal', reminder: 'Lembrete', detail: 'Boleta pronta' }[kind] || 'Sinal';
  const when = sig.timestamp_entrada ? `${f.ago(sig.timestamp_entrada)}` : '';
  return `
  <article class="card ticket ${sideCls} ${kind === 'reminder' ? 'reminder' : ''} ${isNew ? 'is-new' : ''}" data-sid="${esc(sig.id)}">
    <div class="ticket-head">
      ${avatar(sig.trader)}
      <div class="who">
        <div class="who-name">${esc(sig.trader)} ${copyableBadge(sig.profile)}</div>
        <div class="who-sub">${esc(sig.produto || '')}${when ? ` · ${esc(when)}` : ''}</div>
      </div>
      <span class="ticket-kind">${esc(kindLabel)}</span>
    </div>
    <div class="ticket-asset">
      <span class="ticker">${esc(sig.ticker)}</span>
      <span class="badge ${sig.lado === 'SELL' ? 'badge-sell' : 'badge-buy'}">${sig.lado === 'SELL' ? 'Venda' : 'Compra'}</span>
      ${sig.status === 'CLOSED' ? '<span class="badge badge-warn">Encerrado pelo analista</span>' : ''}
    </div>
    <div class="ticket-desc">${esc(optionDesc(sig))}</div>
    ${similarHtml(sig)}
    <div class="ticket-prices">
      <div class="price-stat"><div class="lbl">Entrada analista</div><div class="val">${f.brl(t.entry_price, { dec: 2 })}</div><div class="sub muted">${esc(f.dateTime(sig.timestamp_entrada))}</div></div>
      <div class="price-stat"><div class="lbl" title="Com MT5 ao vivo: melhor oferta de ${sig.lado === 'SELL' ? 'compra (o que você receberia)' : 'venda (o que você pagaria)'}">Agora</div><div class="val" data-lp="${esc(sig.ticker)}" data-basis="${basis}">${t.current_price === null ? '—' : f.brl(t.current_price)}</div><div class="sub ${driftTone(t)}" data-ldrift="${esc(sig.ticker)}" data-entry="${t.entry_price || ''}" data-side="${esc(sig.lado)}" data-basis="${basis}" title="Diferença em relação à entrada do analista">${t.drift_pct === null ? 'sem cotação' : f.pct(t.drift_pct)}</div></div>
      <div class="price-stat"><div class="lbl">Máx. aceitável</div><div class="val">${t.worst_price ? f.brl(t.worst_price) : '—'}</div><div class="sub muted">limite de slippage</div></div>
    </div>
    ${quoteLine(sig.ticker, quoteOf(sig.ticker) || t.quote, { tfPrice: sig.preco_atual })}
    <div class="ticket-form">
      <div class="field"><label for="q-${esc(sig.id)}">Quantidade <span class="faint">(lote ${f.qty(t.lot)})</span></label>
        <input id="q-${esc(sig.id)}" class="input num" data-field="quantity" inputmode="numeric" value="${f.qty(t.quantity)}"></div>
      <div class="field"><label for="p-${esc(sig.id)}">Preço limite (R$)</label>
        <input id="p-${esc(sig.id)}" class="input num" data-field="limit_price" inputmode="decimal" value="${f.num(t.limit_price, 2)}"></div>
    </div>
    <div class="ticket-totals" data-slot="totals">${totalsHtml(t)}</div>
    <div data-slot="warnings">${noteList(t.warnings)}</div>
    ${openOrdersHtml(sig.open_orders)}
    <div class="ticket-actions">
      ${executionMode().mode !== 'off' && !(sig.open_orders && sig.open_orders.length) ? `<button class="btn btn-primary" data-action="send" ${t.can_execute ? '' : 'disabled'} title="Envia a ordem com confirmação">${icon('zap')} ${sendLabel()}</button>` : ''}
      <button class="btn ${executionMode().mode !== 'off' ? '' : 'btn-primary'}" data-action="executed" ${t.can_execute ? '' : 'disabled'} title="Registrar o que você executou no Home Broker">${icon('check')} Executei</button>
      <button class="btn" data-action="copy" title="Copia o texto da ordem para colar no Home Broker">${icon('copy')} Copiar boleta</button>
      ${compact ? '' : `
      <div class="menu-wrap"><button class="btn btn-ghost" data-action="snooze" data-menu title="Lembrar depois">${icon('snooze')}<span class="hide-sm">Depois</span></button></div>
      <div class="menu-wrap"><button class="btn btn-ghost" data-action="ignore" data-menu>${icon('x')} Ignorar</button></div>`}
    </div>
  </article>`;
}

export function exitCard(p) {
  const s = p.signal || {};
  const ret = s.return_final_pct;
  // sem cotação atual: estima o resultado se eu sair no preço de saída do analista
  let pnl = p.unrealized_pnl;
  let pnlPct = p.unrealized_pct;
  let pnlNote = p.last_price_at ? f.ago(p.last_price_at) : '';
  const basis = p.side === 'LONG' ? 'bid' : 'ask';
  const live = `data-qty="${p.quantity}" data-avg="${p.avg_price}" data-side="${p.side}" data-invested="${p.invested || ''}" data-basis="${basis}"`;
  if ((pnl === null || pnl === undefined) && s.preco_saida != null) {
    pnl = (p.side === 'LONG' ? s.preco_saida - p.avg_price : p.avg_price - s.preco_saida) * p.quantity;
    pnlPct = p.invested ? (pnl / p.invested) * 100 : null;
    pnlNote = 'saindo no preço do analista';
  }
  return `
  <article class="card ticket exit" data-cycle="${esc(p.cycle_id)}" data-ticker="${esc(p.ticker)}">
    <div class="ticket-head">
      ${avatar(s.trader || '?')}
      <div class="who">
        <div class="who-name">${esc(s.trader || 'Analista')} encerrou</div>
        <div class="who-sub">${s.timestamp_saida ? `encerrou ${esc(f.ago(s.timestamp_saida))} · ${esc(f.dateTime(s.timestamp_saida))}` : ''}</div>
      </div>
      <span class="ticket-kind">Saída pendente</span>
    </div>
    <div class="ticket-asset">
      <span class="ticker">${esc(p.ticker)}</span>
      <span class="badge ${p.side === 'LONG' ? 'badge-sell' : 'badge-buy'}">${p.side === 'LONG' ? 'Vender' : 'Comprar'} ${f.qty(p.quantity)}</span>
    </div>
    <div class="ticket-desc">Você tem ${f.qty(p.quantity)} un · preço médio ${f.brl(p.avg_price, { dec: 2 })}</div>
    <div class="ticket-prices">
      <div class="price-stat"><div class="lbl">Saída analista</div><div class="val">${f.brl(s.preco_saida)}</div><div class="sub ${f.tone(ret)}">${ret === null || ret === undefined ? '—' : f.pct(ret)} no sinal</div></div>
      <div class="price-stat"><div class="lbl" title="Com MT5 ao vivo: melhor oferta de ${p.side === 'LONG' ? 'compra (o que você receberia vendendo)' : 'venda (o que você pagaria comprando)'}">Agora</div><div class="val" data-lp="${esc(p.ticker)}" data-basis="${basis}">${p.last_price === null ? '—' : f.brl(p.last_price)}</div><div class="sub muted">${p.last_price === null ? 'sem cotação' : ''}</div></div>
      <div class="price-stat"><div class="lbl">Seu P&L ≈</div><div class="val ${f.tone(pnl)}" data-lpnl="${esc(p.ticker)}" ${live}>${f.brl(pnl, { sign: true })}</div><div class="sub ${f.tone(pnlPct)}" data-lpnl="${esc(p.ticker)}" data-fmt="pct" ${live} title="${esc(pnlNote)}">${f.pct(pnlPct)}</div></div>
    </div>
    ${quoteLine(p.ticker, quoteOf(p.ticker), { source: p.last_price_source, at: p.last_price_at })}
    ${openOrdersHtml(p.open_orders)}
    <div class="ticket-actions">
      ${executionMode().mode === 'live' && !(p.open_orders && p.open_orders.length) ? `<button class="btn btn-warn" data-action="send-exit">${icon('zap')} Enviar saída ao MT5</button>` : ''}
      <button class="btn ${executionMode().mode === 'live' ? '' : 'btn-warn'}" data-action="register-exit">${icon('exit')} Registrar saída</button>
      <button class="btn" data-action="copy-exit">${icon('copy')} Copiar boleta</button>
      <button class="btn btn-ghost" data-action="keep" title="Não vou seguir a saída do analista agora">Manter</button>
    </div>
  </article>`;
}

export function openExitOrder(pos) {
  const t = pos.exit_ticket || {};
  return openOrderModal({
    ticker: pos.ticker, side: t.side || (pos.side === 'LONG' ? 'SELL' : 'BUY'), quantity: pos.quantity,
    limit_price: t.reference_price || pos.last_price, order_type: 'limit', purpose: 'exit',
    cycle_id: pos.cycle_id, signal_id: pos.signal ? pos.signal.id : null,
    context: pos.signal && pos.signal.preco_saida ? `${pos.signal.trader} saiu a ${f.brl(pos.signal.preco_saida)}` : 'Zerar posição',
  });
}

// ---------- Interações (delegação de eventos)
const IGNORE_REASONS = ['Preço já andou demais', 'Sem capital livre', 'Não gosto do ativo', 'Perdi o horário', 'Outro motivo'];
const SNOOZE = [[30, '30 minutos'], [60, '1 hora'], [180, '3 horas'], [60 * 18, 'Amanhã cedo']];

async function refreshTicket(card) {
  const id = card.dataset.sid;
  const entry = registry.get(id);
  if (!entry) return;
  const qtyV = f.parseNum(card.querySelector('[data-field=quantity]').value);
  const limV = f.parseNum(card.querySelector('[data-field=limit_price]').value);
  try {
    const t = await get(`/api/signals/${encodeURIComponent(id)}/ticket${qs({ quantity: qtyV, limit_price: limV })}`);
    entry.ticket = t;
    card.querySelector('[data-slot=totals]').innerHTML = totalsHtml(t);
    card.querySelector('[data-slot=warnings]').innerHTML = noteList(t.warnings);
    const btn = card.querySelector('[data-action=executed]');
    if (btn) btn.disabled = !t.can_execute;
  } catch (e) { /* mantém valores anteriores */ }
}
const refreshDebounced = new Map();
const LIVE_REFRESH_MS = 4000;

// Cotação mudou: atualiza avisos/totais da boleta (sem mexer no que o usuário digitou)
function watchQuotes(root) {
  const last = new WeakMap();
  const off = on('quotes', (d) => {
    if (!root.isConnected) { off(); return; }
    const changed = new Set(Object.keys(d.quotes || {}));
    if (!changed.size) return;
    root.querySelectorAll('.ticket[data-sid]').forEach((card) => {
      const entry = registry.get(card.dataset.sid);
      if (!entry || !changed.has(entry.sig.ticker)) return;
      if (card.contains(document.activeElement) && document.activeElement.matches('input')) return;
      const now = Date.now();
      if (now - (last.get(card) || 0) < LIVE_REFRESH_MS) return;
      last.set(card, now);
      refreshTicket(card);
    });
  });
  applyLive(root);
}

export function bindTickets(root, { getPositions = () => [] } = {}) {
  watchQuotes(root);
  root.addEventListener('input', (e) => {
    const input = e.target.closest('.ticket [data-field]');
    if (!input) return;
    const card = input.closest('.ticket');
    if (!refreshDebounced.has(card)) refreshDebounced.set(card, debounce(() => refreshTicket(card), 350));
    refreshDebounced.get(card)();
  });

  root.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-action]');
    if (!btn || !root.contains(btn)) return;
    const card = btn.closest('.ticket');
    if (!card) return;
    const action = btn.dataset.action;
    if (action === 'cancel-order') {
      try {
        await post(`/api/orders/${btn.dataset.order}/cancel`, {});
        toast('Ordem cancelada', 'info');
        emit('data-changed');
      } catch (err) { toastError(err); }
      return;
    }

    if (card.dataset.sid) {
      const entry = registry.get(card.dataset.sid);
      if (!entry) return;
      const { sig } = entry;
      if (action === 'copy') return copyText(entry.ticket.copy_text, 'Boleta copiada — cole no Home Broker');
      if (action === 'link-position') {
        try {
          await post(`/api/signals/${encodeURIComponent(sig.id)}/link-position`, { cycle_id: btn.dataset.position });
          toast(`Sinal de ${sig.trader} vinculado à sua posição em ${sig.ticker} e marcado como executado.`, 'success');
          emit('data-changed');
        } catch (err) { toastError(err); }
        return;
      }
      if (action === 'send') {
        const t = entry.ticket;
        return openOrderModal({
          ticker: sig.ticker, side: sig.lado, quantity: t.quantity, limit_price: t.limit_price,
          order_type: executionMode().order_type || 'limit', purpose: 'entry', signal_id: sig.id,
          context: `Sinal de ${sig.trader}: entrada ${f.brl(t.entry_price)}${t.current_price != null ? ` · agora ${f.brl(t.current_price)}` : ''}`,
        });
      }
      if (action === 'executed') {
        return openExecutionForm({ mode: 'entry', signal: sig, ticket: entry.ticket, onSaved: () => emit('data-changed') });
      }
      if (action === 'ignore') {
        const m = showMenu(btn, `<div class="menu-title">Motivo</div>${IGNORE_REASONS.map((r) => `<button data-reason="${esc(r)}">${esc(r)}</button>`).join('')}`);
        m.addEventListener('click', async (ev) => {
          const b = ev.target.closest('[data-reason]');
          if (!b) return;
          closeMenus();
          try {
            await post(`/api/signals/${encodeURIComponent(sig.id)}/decision`, { status: 'ignored', reason: b.dataset.reason });
            toast(`${sig.ticker} ignorado`, 'info');
            emit('data-changed');
          } catch (err) { toastError(err); }
        });
        return;
      }
      if (action === 'snooze') {
        const m = showMenu(btn, `<div class="menu-title">Lembrar em</div>${SNOOZE.map(([min, l]) => `<button data-min="${min}">${esc(l)}</button>`).join('')}`);
        m.addEventListener('click', async (ev) => {
          const b = ev.target.closest('[data-min]');
          if (!b) return;
          closeMenus();
          try {
            await post(`/api/signals/${encodeURIComponent(sig.id)}/decision`, { status: 'snoozed', remind_minutes: Number(b.dataset.min) });
            toast(`Vou lembrar de ${sig.ticker}`, 'info');
            emit('data-changed');
          } catch (err) { toastError(err); }
        });
      }
      return;
    }

    if (card.dataset.cycle) {
      const pos = getPositions().find((p) => p.cycle_id === card.dataset.cycle);
      if (!pos) return;
      if (action === 'copy-exit') return copyText(pos.exit_ticket.copy_text, 'Boleta de saída copiada');
      if (action === 'send-exit') return openExitOrder(pos);
      if (action === 'register-exit') return openExecutionForm({ mode: 'exit', position: pos, signal: pos.signal, onSaved: () => emit('data-changed') });
      if (action === 'keep') {
        try {
          await post(`/api/positions/${encodeURIComponent(pos.cycle_id)}/keep`, {});
          toast('Ok, posição mantida. Ela continua na Carteira.', 'info');
          emit('data-changed');
        } catch (err) { toastError(err); }
      }
    }
  });
}
