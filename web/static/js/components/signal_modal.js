// Detalhe de um sinal: boleta, fatos do sinal, minhas execuções e decisão
import { get, post } from '../api.js';
import * as f from '../format.js';
import { emit } from '../state.js';
import { esc, icon, loading, openModal, toastError, copyableBadge } from '../ui.js';
import { bindTickets, optionDesc, ticketCard } from './ticket.js';
import { quoteMetaHtml, quoteOf, watch } from '../live.js';
import { openExecutionForm } from './exec_form.js';

const DECISION_LABEL = { executed: ['badge-ok', 'Executado'], ignored: ['', 'Ignorado'], snoozed: ['badge-info', 'Adiado'] };

export function decisionBadge(d) {
  if (!d) return '<span class="badge badge-warn">Sem decisão</span>';
  const [cls, label] = DECISION_LABEL[d.status] || ['', d.status];
  return `<span class="badge ${cls}" title="${esc(d.reason || '')}">${esc(label)}</span>`;
}

export async function openSignalModal(id) {
  const m = openModal({ title: 'Sinal', body: loading(), wide: true });
  let sig;
  try {
    sig = await get(`/api/signals/${encodeURIComponent(id)}`);
  } catch (e) {
    m.setBody(`<div class="note danger">${esc(e.message)}</div>`);
    return;
  }
  const p = sig.profile;
  const execs = sig.executions || [];
  const ret = sig.status === 'CLOSED' ? sig.return_final_pct : sig.return_now_pct;
  m.el.querySelector('.modal-head h2').innerHTML = `${esc(sig.trader)} · <span class="ticker">${esc(sig.ticker)}</span>`;
  m.setBody(`
    <div class="grid grid-2">
      <div>${sig.status === 'OPEN' && !sig.position ? ticketCard(sig, { kind: 'detail' }) : `
        <div class="card card-pad">
          <div class="row wrap"><span class="ticker" style="font-size:1.3rem">${esc(sig.ticker)}</span>
          <span class="badge ${sig.lado === 'SELL' ? 'badge-sell' : 'badge-buy'}">${sig.lado === 'SELL' ? 'Venda' : 'Compra'}</span>
          <span class="badge ${sig.status === 'OPEN' ? 'badge-info' : ''}">${sig.status === 'OPEN' ? 'Aberto' : 'Encerrado'}</span></div>
          <p class="muted mt-2">${esc(optionDesc(sig))}</p>
          ${sig.position ? `<div class="banner info mt-4">${icon('wallet')}<div class="grow">Você tem ${f.qty(sig.position.quantity)} un a ${f.brl(sig.position.avg_price)} (médio).</div></div>` : ''}
        </div>`}
      </div>
      <div class="stack">
        <div class="card card-pad">
          <h3 class="mb-2">Sinal</h3>
          <dl class="kv mt-3">
            <dt>Status</dt><dd>${sig.status === 'OPEN' ? 'Aberto' : 'Encerrado'}</dd>
            <dt>Entrada</dt><dd>${f.brl(sig.preco_entrada)} · ${esc(f.dateTime(sig.timestamp_entrada))}</dd>
            ${sig.status === 'OPEN' ? `<dt>Preço atual</dt><dd><span data-lp="${esc(sig.ticker)}">${f.brl(sig.preco_atual)}</span>
              <div data-lmeta="${esc(sig.ticker)}">${quoteMetaHtml(quoteOf(sig.ticker) || sig.quote, { fallbackSource: sig.preco_atual != null ? 'tradingfloors' : null })}</div></dd>` : `<dt>Saída</dt><dd>${f.brl(sig.preco_saida)} · ${esc(f.dateTime(sig.timestamp_saida))}</dd>`}
            <dt>Retorno do sinal</dt><dd><span class="${f.tone(ret)}" ${sig.status === 'OPEN' ? `data-lret="${esc(sig.ticker)}" data-entry="${sig.preco_entrada || ''}" data-side="${esc(sig.lado)}"` : ''}>${f.pct(ret)}</span></dd>
            <dt>Stop / Alvo</dt><dd>${sig.stop_loss ? f.brl(sig.stop_loss) : '—'} / ${sig.take_profit ? f.brl(sig.take_profit) : '—'}</dd>
            <dt>Qtd. do analista</dt><dd>${f.qty(sig.quantidade)}</dd>
            <dt>Produto</dt><dd>${esc(sig.produto || '—')}</dd>
            <dt>Minha decisão</dt><dd>${decisionBadge(sig.decision)}${sig.decision?.reason ? ` <span class="faint">${esc(sig.decision.reason)}</span>` : ''}</dd>
          </dl>
          ${sig.decision && sig.decision.status !== 'executed' ? `<button class="btn btn-sm btn-ghost mt-3" data-clear>${icon('refresh')} Desfazer decisão</button>` : ''}
        </div>
        ${p ? `<div class="card card-pad">
          <div class="row-between"><h3>${esc(sig.trader)} em ${esc(p.asset_label)}</h3>${copyableBadge(p)}</div>
          <dl class="kv mt-3">
            <dt>Operações encerradas</dt><dd>${p.closed}</dd>
            <dt>Taxa de acerto</dt><dd>${p.win_rate === null ? '—' : f.pct(p.win_rate, { sign: false })}</dd>
            <dt>Retorno médio</dt><dd class="${f.tone(p.avg_return_pct)}">${f.pct(p.avg_return_pct)}</dd>
            <dt>Permanência mediana</dt><dd>${p.median_hold_days === null ? '—' : `${f.num(p.median_hold_days, 1)} dia(s)`}</dd>
            <dt>Fecha no mesmo dia</dt><dd>${p.same_day_share === null ? '—' : f.pct(p.same_day_share, { sign: false })}</dd>
          </dl>
          <p class="hint mt-3">Histórico do analista no TradingFloors, sem custos.</p>
        </div>` : ''}
      </div>
    </div>
    <div class="section mt-5">
      <div class="section-title"><h2>Minhas execuções neste sinal</h2>
        <button class="btn btn-sm" data-add-exec>${icon('plus')} Registrar execução</button></div>
      ${execs.length ? `<div class="card table-wrap"><table class="table"><thead><tr><th>Data</th><th>Lado</th><th class="r">Qtd</th><th class="r">Preço</th><th class="r">Custos</th></tr></thead><tbody>
        ${execs.map((e) => `<tr><td>${esc(f.dateTime(e.executed_at))}</td><td>${e.side === 'BUY' ? 'Compra' : 'Venda'}</td><td class="num r">${f.qty(e.quantity)}</td><td class="num r">${f.brl(e.price)}</td><td class="num r">${f.brl(e.fees)}</td></tr>`).join('')}
      </tbody></table></div>` : '<p class="muted">Nenhuma execução registrada.</p>'}
    </div>`);

  bindTickets(m.el);
  // os menus (Ignorar/Depois) abrem no fundo do modal, fora de m.el
  m.el.parentElement.addEventListener('click', (e) => {
    if (e.target.closest('.menu [data-reason], .menu [data-min]')) setTimeout(m.close, 50);
  });
  if (sig.status === 'OPEN') watch([sig.ticker]); // sinal de analista não seguido: passa a ser acompanhado
  m.el.addEventListener('click', async (e) => {
    if (e.target.closest('[data-action=executed], [data-action=send]')) m.close();
    if (e.target.closest('[data-clear]')) {
      try {
        await post(`/api/signals/${encodeURIComponent(id)}/decision`, { status: 'clear' });
        m.close();
        emit('data-changed');
        openSignalModal(id);
      } catch (err) { toastError(err); }
    }
    if (e.target.closest('[data-add-exec]')) {
      m.close();
      openExecutionForm({ mode: 'add', signal: sig, ticket: sig.ticket, onSaved: () => emit('data-changed') });
    }
  });
}
