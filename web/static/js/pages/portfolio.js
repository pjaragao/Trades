// Tela CARTEIRA — "Como estão minhas posições?"
import { del, get, put } from '../api.js';
import * as f from '../format.js';
import { emit, on } from '../state.js';
import { openExecutionForm } from '../components/exec_form.js';
import { openSignalModal } from '../components/signal_modal.js';
import { confirmDialog, copyText, esc, icon, loading, noteList, openModal, toast, toastError } from '../ui.js';

function posCard(p) {
  const s = p.signal;
  const sigLine = s
    ? `${esc(s.trader)} · ${s.status === 'OPEN' ? 'sinal aberto' : `<span class="warn-text">encerrado a ${f.brl(s.preco_saida)}</span>`}${p.signal_guessed ? ' <span class="faint" title="Vinculado automaticamente pelo ativo">(auto)</span>' : ''}`
    : '<span class="faint">sem sinal (manual)</span>';
  const slip = p.entry_slippage_pct;
  return `
  <div class="pos-card ${p.exit_pending ? 'pending' : ''}" data-cycle="${esc(p.cycle_id)}">
    <div class="pos-main">
      <div class="row wrap"><span class="ticker" style="font-size:1.1rem">${esc(p.ticker)}</span>
        <span class="badge ${p.side === 'LONG' ? 'badge-buy' : 'badge-sell'}">${p.side === 'LONG' ? 'Comprado' : 'Vendido'}</span>
        ${p.exit_pending ? '<span class="badge badge-warn">Saída pendente</span>' : ''}${p.exit_kept ? '<span class="badge">Mantida</span>' : ''}</div>
      <div class="muted mt-2" style="font-size:var(--fs-xs)">${sigLine}${s ? ` · <button class="link-btn" data-open-signal="${esc(s.id)}">ver sinal</button>` : ''}</div>
      <div class="faint" style="font-size:var(--fs-xs)">desde ${esc(f.dateTime(p.opened_at))}${s && s.expiration ? ` · vence ${esc(f.date(s.expiration + 'T12:00:00-03:00'))}` : ''}</div>
    </div>
    <div><div class="lbl">Quantidade</div><div class="val">${f.qty(p.quantity)}</div><div class="val-sub faint">${f.brl(p.invested)} investidos</div></div>
    <div><div class="lbl">Meu médio</div><div class="val">${f.brl(p.avg_price)}</div>
      <div class="val-sub ${slip === null || slip === undefined ? 'faint' : slip > 0.05 ? 'loss' : slip < -0.05 ? 'gain' : 'faint'}" title="Diferença do meu preço de entrada para o do analista (positivo = paguei mais caro)">${p.signal_entry ? `analista ${f.brl(p.signal_entry)} (${f.pct(slip)})` : '—'}</div></div>
    <div><div class="lbl">Atual</div>
      <div class="val"><button class="link-btn" data-quote="${esc(p.ticker)}" title="Informar cotação manualmente">${p.last_price === null ? 'informar' : f.brl(p.last_price)}</button></div>
      <div class="val-sub faint">${p.last_price_source === 'manual' ? 'manual · ' : ''}${p.last_price_at ? esc(f.ago(p.last_price_at)) : ''}</div></div>
    <div><div class="lbl">Meu P&L / sinal</div><div class="val ${f.tone(p.unrealized_pnl)}">${f.brl(p.unrealized_pnl, { sign: true })}</div>
      <div class="val-sub"><span class="${f.tone(p.unrealized_pct)}">${f.pct(p.unrealized_pct)}</span> <span class="faint">vs</span> <span class="${f.tone(p.signal_return_pct)}">${f.pct(p.signal_return_pct)}</span></div></div>
    <div class="pos-actions">
      <button class="btn btn-sm ${p.exit_pending ? 'btn-warn' : ''}" data-act="exit">${icon('exit')} Registrar saída</button>
      <button class="btn btn-sm btn-ghost btn-icon" data-act="copy-exit" title="Copiar boleta de saída">${icon('copy')}</button>
      <button class="btn btn-sm btn-ghost btn-icon" data-act="add" title="Registrar nova compra/venda neste ativo">${icon('plus')}</button>
    </div>
    ${p.alerts.length ? `<div class="pos-alerts">${noteList(p.alerts)}</div>` : ''}
  </div>`;
}

function execTable(execs) {
  if (!execs.length) return '<div class="empty compact"><p>Nenhuma execução registrada ainda.</p></div>';
  return `<div class="table-wrap"><table class="table">
    <thead><tr><th>Data</th><th>Ativo</th><th>Lado</th><th class="r">Qtd</th><th class="r">Preço</th><th class="r">Custos</th><th class="r">Total</th><th>Obs.</th><th></th></tr></thead>
    <tbody>${execs.map((e) => `
      <tr>
        <td class="nowrap">${esc(f.dateTime(e.executed_at))}</td>
        <td><span class="ticker">${esc(e.ticker)}</span>${e.signal_id ? '' : ' <span class="faint">manual</span>'}</td>
        <td><span class="badge ${e.side === 'BUY' ? 'badge-buy' : 'badge-sell'}">${e.side === 'BUY' ? 'Compra' : 'Venda'}</span></td>
        <td class="num r">${f.qty(e.quantity)}</td>
        <td class="num r">${f.brl(e.price)}</td>
        <td class="num r">${f.brl(e.fees)}</td>
        <td class="num r">${f.brl(e.side === 'BUY' ? e.quantity * e.price + e.fees : e.quantity * e.price - e.fees)}</td>
        <td class="muted" style="max-width:220px">${esc(e.note || '')}</td>
        <td class="r nowrap"><button class="btn btn-sm btn-ghost btn-icon" data-edit="${e.id}" title="Editar">${icon('edit')}</button>
          <button class="btn btn-sm btn-ghost btn-icon" data-del="${e.id}" title="Excluir">${icon('trash')}</button></td>
      </tr>`).join('')}</tbody></table></div>`;
}

export default {
  title: 'Carteira',
  async mount(root) {
    root.innerHTML = loading();
    let data = null;
    let execs = [];

    const render = () => {
      const s = data.summary;
      const mv = data.positions.reduce((acc, p) => acc + (p.market_value || 0), 0);
      root.innerHTML = `
        <div class="page-head"><div><h1>Carteira</h1><p class="sub">Suas posições reais (do que você registrou), marcadas a mercado e comparadas ao sinal.</p></div>
          <button class="btn" data-act="manual">${icon('plus')} Registrar operação</button></div>
        <div class="grid grid-4 section">
          <div class="card tile"><div class="tile-label">Investido</div><div class="tile-value">${f.brl(s.invested)}</div><div class="tile-sub">${s.open_positions} posição(ões)</div></div>
          <div class="card tile"><div class="tile-label">Valor de mercado</div><div class="tile-value">${f.brl(mv)}</div><div class="tile-sub">${s.unpriced_positions ? `${s.unpriced_positions} sem cotação` : 'cotações do TradingFloors'}</div></div>
          <div class="card tile"><div class="tile-label">P&L em aberto</div><div class="tile-value ${f.tone(s.unrealized_pnl)}">${f.brl(s.unrealized_pnl, { sign: true })}</div><div class="tile-sub">sem custos de saída</div></div>
          <div class="card tile"><div class="tile-label">Capital livre</div><div class="tile-value">${f.brl(s.free)}</div><div class="tile-sub">de ${f.brl(s.capital)}</div></div>
        </div>
        <section class="section">
          <div class="section-title"><h2>${icon('wallet')} Posições abertas <span class="count">${data.positions.length}</span></h2></div>
          <div class="card">${data.positions.length ? data.positions.map(posCard).join('') : `<div class="empty"><div class="empty-icon">${icon('wallet', 'icon-lg')}</div><h3>Sem posições abertas</h3><p>Use "Executei" na boleta de um sinal, ou registre uma operação manual.</p></div>`}</div>
        </section>
        <section class="section">
          <div class="section-title"><h2>${icon('clock')} Execuções registradas <span class="count">${execs.length}</span></h2>
            <a class="btn btn-sm btn-ghost" href="/api/export/execucoes.csv">${icon('download')} CSV</a></div>
          <div class="card">${execTable(execs.slice().reverse())}</div>
        </section>`;
    };

    const load = async () => {
      try {
        [data, execs] = await Promise.all([get('/api/portfolio'), get('/api/executions')]);
        render();
      } catch (e) {
        root.innerHTML = `<div class="banner danger">${icon('alert')}<div class="grow">${esc(e.message)}</div></div>`;
      }
    };

    const findPos = (el) => data.positions.find((p) => p.cycle_id === el.closest('[data-cycle]')?.dataset.cycle);

    root.addEventListener('click', async (e) => {
      const act = e.target.closest('[data-act]');
      if (act) {
        const a = act.dataset.act;
        if (a === 'manual') return openExecutionForm({ mode: 'manual', onSaved: () => emit('data-changed') });
        const p = findPos(act);
        if (!p) return;
        if (a === 'exit') return openExecutionForm({ mode: 'exit', position: p, signal: p.signal, onSaved: () => emit('data-changed') });
        if (a === 'copy-exit') return copyText(p.exit_ticket.copy_text, 'Boleta de saída copiada');
        if (a === 'add') return openExecutionForm({ mode: 'add', position: p, signal: p.signal, onSaved: () => emit('data-changed') });
      }
      const sigBtn = e.target.closest('[data-open-signal]');
      if (sigBtn) return openSignalModal(sigBtn.dataset.openSignal);
      const q = e.target.closest('[data-quote]');
      if (q) {
        const ticker = q.dataset.quote;
        const m = openModal({
          title: `Cotação de ${ticker}`,
          body: `<div class="field"><label for="qv">Último preço (R$)</label><input id="qv" class="input num" inputmode="decimal" autofocus></div>
                 <p class="hint mt-3">Use quando o TradingFloors não informar o preço atual. Será substituído pela próxima cotação do TF.</p>`,
          foot: '<button class="btn btn-ghost" data-close>Cancelar</button><button class="btn btn-primary" id="qv-save">Salvar</button>',
        });
        m.el.querySelector('.modal-foot [data-close]').onclick = m.close;
        m.el.querySelector('#qv-save').onclick = async () => {
          const v = f.parseNum(m.el.querySelector('#qv').value);
          if (v === null) return;
          try { await put(`/api/quotes/${encodeURIComponent(ticker)}`, { price: v }); m.close(); emit('data-changed'); } catch (err) { toastError(err); }
        };
        return;
      }
      const ed = e.target.closest('[data-edit]');
      if (ed) {
        const ex = execs.find((x) => String(x.id) === ed.dataset.edit);
        return openExecutionForm({ mode: 'edit', execution: ex, onSaved: () => emit('data-changed') });
      }
      const dl = e.target.closest('[data-del]');
      if (dl) {
        const ex = execs.find((x) => String(x.id) === dl.dataset.del);
        const ok = await confirmDialog({ title: 'Excluir execução', message: `Excluir ${ex.side === 'BUY' ? 'compra' : 'venda'} de ${f.qty(ex.quantity)} ${esc(ex.ticker)} a ${f.brl(ex.price)}? Posições e resultados serão recalculados.`, confirmText: 'Excluir', danger: true });
        if (!ok) return;
        try { await del(`/api/executions/${ex.id}`); toast('Execução excluída', 'info'); emit('data-changed'); } catch (err) { toastError(err); }
      }
    });

    await load();
    const off = on('data-changed', load);
    return () => off();
  },
};
