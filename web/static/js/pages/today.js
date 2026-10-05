// Tela HOJE — "O que preciso fazer agora?"
import { get } from '../api.js';
import * as f from '../format.js';
import { on } from '../state.js';
import { bindTickets, exitCard, ticketCard } from '../components/ticket.js';
import { openSignalModal } from '../components/signal_modal.js';
import { openExecutionForm } from '../components/exec_form.js';
import { emit } from '../state.js';
import { esc, icon, loading, modalOpen, toastError } from '../ui.js';

const seen = new Set(); // sinais já exibidos nesta sessão (para animar só os novos)

function tiles(s) {
  return `
  <div class="grid grid-4 section">
    <div class="card tile"><div class="tile-label">Resultado hoje</div><div class="tile-value ${f.tone(s.realized_today)}">${f.brl(s.realized_today, { sign: true })}</div><div class="tile-sub">realizado</div></div>
    <div class="card tile"><div class="tile-label">Em aberto</div><div class="tile-value ${f.tone(s.unrealized_pnl)}">${f.brl(s.unrealized_pnl, { sign: true })}</div><div class="tile-sub">${s.open_positions} posição(ões)${s.unpriced_positions ? ` · ${s.unpriced_positions} sem cotação` : ''}</div></div>
    <div class="card tile"><div class="tile-label">Resultado do mês</div><div class="tile-value ${f.tone(s.realized_month)}">${f.brl(s.realized_month, { sign: true })}</div><div class="tile-sub">realizado, com custos</div></div>
    <div class="card tile"><div class="tile-label">Capital livre</div><div class="tile-value">${f.brl(s.free)}</div><div class="tile-sub">de ${f.brl(s.capital)} · investido ${f.brl(s.invested)}</div></div>
  </div>`;
}

function positionsTable(positions) {
  if (!positions.length) {
    return `<div class="card"><div class="empty compact"><p>Nenhuma posição aberta. Quando você registrar uma execução, ela aparece aqui.</p></div></div>`;
  }
  return `<div class="card table-wrap"><table class="table">
    <thead><tr><th>Ativo</th><th>Sinal</th><th class="r">Qtd</th><th class="r">Médio</th><th class="r">Atual</th><th class="r">P&L</th><th class="r">Sinal</th></tr></thead>
    <tbody>${positions.map((p) => `
      <tr class="clickable" data-href="#/carteira">
        <td><span class="ticker">${esc(p.ticker)}</span>${p.exit_pending ? ' <span class="badge badge-warn">Saída pendente</span>' : ''}</td>
        <td>${p.signal ? `${esc(p.signal.trader)}<span class="cell-sub">${p.signal.status === 'OPEN' ? 'aberto' : 'encerrado'}</span>` : '<span class="faint">manual</span>'}</td>
        <td class="num r">${f.qty(p.quantity)}</td>
        <td class="num r">${f.brl(p.avg_price)}</td>
        <td class="num r">${p.last_price === null ? '—' : f.brl(p.last_price)}</td>
        <td class="num r ${f.tone(p.unrealized_pnl)}">${f.brl(p.unrealized_pnl, { sign: true })}<span class="cell-sub ${f.tone(p.unrealized_pct)}">${f.pct(p.unrealized_pct)}</span></td>
        <td class="num r ${f.tone(p.signal_return_pct)}">${f.pct(p.signal_return_pct)}</td>
      </tr>`).join('')}</tbody></table></div>`;
}

export default {
  title: 'Hoje',
  async mount(root) {
    root.innerHTML = loading();
    let data = null;
    let lastJson = '';

    const render = () => {
      const actions = data.exits_pending.length + data.new_signals.length + data.reminders.length;
      const newIds = data.new_signals.map((s) => s.id);
      root.innerHTML = `
        <div class="hero">
          <div><h1>${esc(f.longToday())}</h1>
            <p class="sub">${actions ? `${actions} ${actions === 1 ? 'item precisa' : 'itens precisam'} de você agora.` : 'Nada pendente agora.'} ${esc(data.market.label)} · ${esc(data.market.detail)}</p></div>
          <div class="row wrap">
            <button class="btn" data-act="manual">${icon('plus')} Registrar operação</button>
          </div>
        </div>

        ${tiles(data.summary)}

        <section class="section">
          <div class="section-title"><h2>${icon('zap')} Precisa de você${actions ? ` <span class="count">${actions}</span>` : ''}</h2></div>
          ${actions ? `<div class="action-grid">
            ${data.exits_pending.map((p) => exitCard(p)).join('')}
            ${data.reminders.map((s) => ticketCard(s, { kind: 'reminder' })).join('')}
            ${data.new_signals.map((s) => ticketCard(s, { kind: 'new', isNew: seen.size > 0 && !seen.has(s.id) })).join('')}
          </div>` : `
          <div class="card allclear">
            <div class="big-icon">${icon('check', 'icon-lg')}</div>
            <div><h3>Tudo em dia</h3>
              <p class="muted">O monitor está acompanhando os analistas que você segue. Quando alguém abrir ou encerrar uma operação, aparece aqui com a boleta pronta.</p></div>
          </div>`}
          ${data.inbox_count ? `<p class="mt-3 muted">${icon('inbox')} ${data.inbox_count} sinal(is) aberto(s) há mais de ${data.fresh_hours} h sem decisão — <a href="#/sinais?decision=none">ver na caixa de Sinais</a>.</p>` : ''}
        </section>

        <section class="section">
          <div class="section-title"><h2>${icon('wallet')} Minhas posições <span class="count">${data.positions.length}</span></h2>
            <a class="btn btn-sm btn-ghost" href="#/carteira">Abrir Carteira</a></div>
          ${positionsTable(data.positions)}
        </section>`;
      newIds.forEach((id) => seen.add(id));
      if (!seen.size) seen.add('__init__');
    };

    const load = async (force = false) => {
      try {
        const fresh = await get('/api/today');
        const json = JSON.stringify(fresh);
        if (!force && json === lastJson) return;
        // não atrapalha quem está digitando ou com modal aberto
        if (!force && data && (modalOpen() || root.contains(document.activeElement) && document.activeElement.matches('input'))) return;
        lastJson = json;
        data = fresh;
        render();
      } catch (e) {
        if (!data) root.innerHTML = `<div class="banner danger">${icon('alert')}<div class="grow">${esc(e.message)}</div></div>`;
      }
    };

    bindTickets(root, { getPositions: () => (data ? data.exits_pending : []) });
    root.addEventListener('click', (e) => {
      const tr = e.target.closest('tr[data-href]');
      if (tr) location.hash = tr.dataset.href;
      const head = e.target.closest('.ticket .ticker, .ticket .who-name');
      if (head) {
        const card = head.closest('.ticket');
        if (card.dataset.sid) openSignalModal(card.dataset.sid);
      }
      if (e.target.closest('[data-act=manual]')) openExecutionForm({ mode: 'manual', onSaved: () => emit('data-changed') });
    });

    await load(true);
    const off1 = on('data-changed', () => load(true));
    const off2 = on('status-tick', () => load(false));
    return () => { off1(); off2(); };
  },
};
