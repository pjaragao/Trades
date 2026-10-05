// Cartão "Boleta pronta" (novo sinal / lembrete) e cartão de "Saída pendente"
import { get, post, qs } from '../api.js';
import * as f from '../format.js';
import { emit } from '../state.js';
import { avatar, copyText, copyableBadge, debounce, esc, icon, noteList, showMenu, closeMenus, toast, toastError } from '../ui.js';
import { openExecutionForm } from './exec_form.js';

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

function totalsHtml(t) {
  return `
    <div><div class="t-lbl">Total ≈</div><div class="t-val">${f.brl(t.total)}</div></div>
    <div><div class="t-lbl">% do capital</div><div class="t-val">${t.pct_capital === null ? '—' : f.pct(t.pct_capital, { sign: false })}</div></div>
    <div><div class="t-lbl" title="${esc(t.max_loss_note || '')}">Perda máx.</div><div class="t-val ${t.max_loss ? 'loss' : 'muted'}">${t.max_loss ? f.brl(t.max_loss) : 'sem stop'}</div></div>`;
}

export function ticketCard(sig, { kind = 'new', isNew = false, compact = false } = {}) {
  const t = sig.ticket;
  registry.set(sig.id, { sig, ticket: t });
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
    <div class="ticket-prices">
      <div class="price-stat"><div class="lbl">Entrada analista</div><div class="val">${f.brl(t.entry_price, { dec: 2 })}</div><div class="sub muted">${esc(f.dateTime(sig.timestamp_entrada))}</div></div>
      <div class="price-stat"><div class="lbl">Agora</div><div class="val">${t.current_price === null ? '—' : f.brl(t.current_price)}</div><div class="sub ${driftTone(t)}" title="Diferença em relação à entrada do analista">${t.drift_pct === null ? 'sem cotação' : f.pct(t.drift_pct)}</div></div>
      <div class="price-stat"><div class="lbl">Máx. aceitável</div><div class="val">${t.worst_price ? f.brl(t.worst_price) : '—'}</div><div class="sub muted">limite de slippage</div></div>
    </div>
    <div class="ticket-form">
      <div class="field"><label for="q-${esc(sig.id)}">Quantidade <span class="faint">(lote ${f.qty(t.lot)})</span></label>
        <input id="q-${esc(sig.id)}" class="input num" data-field="quantity" inputmode="numeric" value="${f.qty(t.quantity)}"></div>
      <div class="field"><label for="p-${esc(sig.id)}">Preço limite (R$)</label>
        <input id="p-${esc(sig.id)}" class="input num" data-field="limit_price" inputmode="decimal" value="${f.num(t.limit_price, 2)}"></div>
    </div>
    <div class="ticket-totals" data-slot="totals">${totalsHtml(t)}</div>
    <div data-slot="warnings">${noteList(t.warnings)}</div>
    <div class="ticket-actions">
      <button class="btn btn-primary" data-action="executed" ${t.can_execute ? '' : 'disabled'}>${icon('check')} Executei</button>
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
      <div class="price-stat"><div class="lbl">Agora</div><div class="val">${p.last_price === null ? '—' : f.brl(p.last_price)}</div><div class="sub muted">${p.last_price === null ? 'sem cotação' : ''}</div></div>
      <div class="price-stat"><div class="lbl">Seu P&L ≈</div><div class="val ${f.tone(pnl)}">${f.brl(pnl, { sign: true })}</div><div class="sub ${f.tone(pnlPct)}" title="${esc(pnlNote)}">${f.pct(pnlPct)}</div></div>
    </div>
    <div class="ticket-actions">
      <button class="btn btn-warn" data-action="register-exit">${icon('exit')} Registrar saída</button>
      <button class="btn" data-action="copy-exit">${icon('copy')} Copiar boleta</button>
      <button class="btn btn-ghost" data-action="keep" title="Não vou seguir a saída do analista agora">Manter</button>
    </div>
  </article>`;
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

export function bindTickets(root, { getPositions = () => [] } = {}) {
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

    if (card.dataset.sid) {
      const entry = registry.get(card.dataset.sid);
      if (!entry) return;
      const { sig } = entry;
      if (action === 'copy') return copyText(entry.ticket.copy_text, 'Boleta copiada — cole no Home Broker');
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
