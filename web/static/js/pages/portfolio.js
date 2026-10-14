// Tela CARTEIRA — "Como estão minhas posições?" (+ ordens e automação da Fase 6)
import { del, get, post, put } from '../api.js';
import * as f from '../format.js';
import { emit, on, state } from '../state.js';
import { openExecutionForm } from '../components/exec_form.js';
import { openSignalModal } from '../components/signal_modal.js';
import { openExitOrder } from '../components/ticket.js';
import { orderLine, orderStatusLabel } from '../components/order_modal.js';
import { applyLive, livePnlAttrs, quoteMetaHtml, quoteOf, watch } from '../live.js';
import { confirmDialog, copyText, esc, icon, loading, noteList, openModal, toast, toastError } from '../ui.js';

let account = 'real'; // conta exibida nesta tela

function quoteSourceLabel() {
  const fd = state.quotesFeed || state.status?.quotes;
  if (fd && fd.state === 'live') return `cotações ao vivo (${fd.label})`;
  if (fd && fd.state === 'delayed') return 'ações: brapi (~30 min) · opções: TradingFloors';
  return 'cotações do TradingFloors / manual';
}

function canSendExit(p) {
  const mode = state.status?.execution?.mode || 'off';
  return (p.account === 'real' && mode === 'live') || (p.account === 'paper' && mode === 'paper');
}

function posCard(p) {
  const s = p.signal;
  const sigLine = s
    ? `${esc(s.trader)} · ${s.status === 'OPEN' ? 'sinal aberto' : `<span class="warn-text">encerrado a ${f.brl(s.preco_saida)}</span>`}${p.signal_guessed ? ' <span class="faint" title="Vinculado automaticamente pelo ativo">(auto)</span>' : ''}`
    : '<span class="faint">sem sinal (manual)</span>';
  const slip = p.entry_slippage_pct;
  const orders = p.open_orders || [];
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
      <div class="val"><button class="link-btn" data-quote="${esc(p.ticker)}" data-lp="${esc(p.ticker)}" title="Informar cotação manualmente">${p.last_price === null ? 'informar' : f.brl(p.last_price)}</button></div>
      <div class="val-sub" data-lmeta="${esc(p.ticker)}">${quoteMetaHtml(quoteOf(p.ticker), { fallbackSource: p.last_price_source, fallbackAt: p.last_price_at })}</div></div>
    <div><div class="lbl">Meu P&L / sinal</div><div class="val ${f.tone(p.unrealized_pnl)}" ${livePnlAttrs(p)} data-lsum-src data-v="${p.unrealized_pnl ?? ''}" data-mv="${p.market_value ?? ''}">${f.brl(p.unrealized_pnl, { sign: true })}</div>
      <div class="val-sub"><span class="${f.tone(p.unrealized_pct)}" ${livePnlAttrs(p)} data-fmt="pct">${f.pct(p.unrealized_pct)}</span> <span class="faint">vs</span> <span class="${f.tone(p.signal_return_pct)}" ${p.signal && p.signal.status === 'OPEN' ? `data-lret="${esc(p.ticker)}" data-entry="${p.signal.preco_entrada || ''}" data-side="${esc(p.signal.lado)}"` : ''}>${f.pct(p.signal_return_pct)}</span></div></div>
    <div class="pos-actions">
      ${canSendExit(p) && !orders.length ? `<button class="btn btn-sm ${p.exit_pending ? 'btn-warn' : ''}" data-act="send-exit">${icon('zap')} ${p.account === 'paper' ? 'Sair (simulação)' : 'Enviar saída'}</button>` : ''}
      ${p.account === 'real' ? `<button class="btn btn-sm ${p.exit_pending && !canSendExit(p) ? 'btn-warn' : ''}" data-act="exit">${icon('exit')} Registrar saída</button>` : ''}
      <button class="btn btn-sm btn-ghost btn-icon" data-act="copy-exit" title="Copiar boleta de saída">${icon('copy')}</button>
      ${p.account === 'real' ? `<button class="btn btn-sm btn-ghost btn-icon" data-act="add" title="Registrar nova compra/venda neste ativo">${icon('plus')}</button>` : ''}
    </div>
    ${orders.length ? `<div class="pos-alerts">${orders.map((o) => `<div class="note info">${icon('clock')}<span class="row-between" style="flex:1">${orderLine(o)} ${orderStatusLabel(o)}
      <button class="btn btn-sm btn-ghost" data-cancel-order="${o.id}">Cancelar</button></span></div>`).join('')}</div>` : ''}
    ${p.alerts.length ? `<div class="pos-alerts">${noteList(p.alerts)}</div>` : ''}
  </div>`;
}

function execTable(execs) {
  if (!execs.length) return '<div class="empty compact"><p>Nenhuma execução registrada ainda.</p></div>';
  const srcLabel = { manual: '', broker: 'MT5', note: 'nota' };
  return `<div class="table-wrap"><table class="table">
    <thead><tr><th>Data</th><th>Ativo</th><th>Lado</th><th class="r">Qtd</th><th class="r">Preço</th><th class="r">Custos</th><th class="r">Total</th><th>Obs.</th><th></th></tr></thead>
    <tbody>${execs.map((e) => `
      <tr>
        <td class="nowrap">${esc(f.dateTime(e.executed_at))}</td>
        <td><span class="ticker">${esc(e.ticker)}</span>${e.signal_id ? '' : ' <span class="faint">manual</span>'}${srcLabel[e.source] ? ` <span class="badge badge-plain">${srcLabel[e.source]}</span>` : ''}</td>
        <td><span class="badge ${e.side === 'BUY' ? 'badge-buy' : 'badge-sell'}">${e.side === 'BUY' ? 'Compra' : 'Venda'}</span></td>
        <td class="num r">${f.qty(e.quantity)}</td>
        <td class="num r">${f.brl(e.price)}</td>
        <td class="num r">${f.brl(e.fees)}${e.fees_source === 'estimate' ? '<span class="cell-sub warn-text" title="Estimado — importe a nota de corretagem para o valor real">estimado</span>' : e.fees_source === 'note' ? '<span class="cell-sub gain">nota</span>' : ''}</td>
        <td class="num r">${f.brl(e.side === 'BUY' ? e.quantity * e.price + e.fees : e.quantity * e.price - e.fees)}</td>
        <td class="muted" style="max-width:220px">${esc(e.note || '')}</td>
        <td class="r nowrap"><button class="btn btn-sm btn-ghost btn-icon" data-edit="${e.id}" title="Editar">${icon('edit')}</button>
          <button class="btn btn-sm btn-ghost btn-icon" data-del="${e.id}" title="Excluir">${icon('trash')}</button></td>
      </tr>`).join('')}</tbody></table></div>`;
}

function ordersSection(ex) {
  const list = ex.orders.filter((o) => o.account === account);
  const log = ex.automation_log.filter((l) => l.account === account).slice(0, 12);
  if (!list.length && !log.length) return '';
  return `
    <section class="section grid grid-2-1">
      <div class="card"><div class="card-head"><h3>${icon('zap')} Ordens ${account === 'paper' ? 'simuladas' : 'enviadas'}</h3>
        <button class="btn btn-sm btn-ghost" data-act="sync-orders">${icon('refresh')} Atualizar</button></div>
        ${list.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>Quando</th><th>Ordem</th><th>Origem</th><th class="r">Executado</th><th>Status</th><th></th></tr></thead><tbody>
        ${list.slice(0, 20).map((o) => `<tr><td class="nowrap">${esc(f.dateTime(o.created_at))}</td><td class="nowrap">${orderLine(o)}</td>
          <td>${o.origin === 'auto' ? '<span class="badge badge-warn badge-plain">automação</span>' : 'você'}</td>
          <td class="num r">${f.qty(o.filled_qty)}${o.avg_fill_price ? `<span class="cell-sub">${f.brl(o.avg_fill_price)}</span>` : ''}</td>
          <td>${orderStatusLabel(o)}</td>
          <td class="r">${o.is_open ? `<button class="btn btn-sm btn-ghost" data-cancel-order="${o.id}">Cancelar</button>` : ''}</td></tr>`).join('')}
        </tbody></table></div>` : '<div class="empty compact"><p>Nenhuma ordem.</p></div>'}</div>
      <div class="card"><div class="card-head"><h3>${icon('shield')} Decisões da automação</h3></div>
        ${log.length ? log.map((l) => `<div class="alert-item" style="cursor:default"><div class="alert-icon ${l.decision === 'sent' ? 'action' : ''}">${icon(l.decision === 'sent' ? 'check' : 'x')}</div>
          <div><div class="alert-title">${esc(l.action)} ${esc(l.ticker || '')} · ${l.decision === 'sent' ? 'enviada' : 'não enviada'}</div><div class="alert-body">${esc(l.reason || '')}</div><div class="alert-time">${esc(f.ago(l.at))}</div></div></div>`).join('')
          : '<div class="empty compact"><p>A automação ainda não tomou decisões.</p></div>'}</div>
    </section>`;
}

export default {
  title: 'Carteira',
  async mount(root, params) {
    account = params.get('conta') === 'simulacao' ? 'paper' : (state.status?.execution?.mode === 'paper' && !params.get('conta') ? 'paper' : 'real');
    root.innerHTML = loading();
    let data = null;
    let execs = [];
    let ex = { orders: [], automation_log: [] };

    const render = () => {
      const s = data.summary;
      const mv = data.positions.reduce((acc, p) => acc + (p.market_value || 0), 0);
      const showToggle = data.has_paper || state.status?.execution?.mode === 'paper' || account === 'paper';
      const unnoted = account === 'real' ? execs.filter((e) => e.fees_source !== 'note' && !e.note_id).length : 0;
      root.innerHTML = `
        <div class="page-head"><div><h1>Carteira</h1><p class="sub">${account === 'paper' ? 'Conta <strong>simulada</strong>: ordens enviadas no modo simulação. Não afeta seus resultados reais.' : 'Suas posições reais (do que você registrou ou o MT5 executou), marcadas a mercado e comparadas ao sinal.'}</p></div>
          <div class="row wrap">
            ${showToggle ? `<div class="segmented" id="acct"><button data-a="real" class="${account === 'real' ? 'active' : ''}">Real</button><button data-a="paper" class="${account === 'paper' ? 'active' : ''}">Simulação</button></div>` : ''}
            ${account === 'real' ? `<button class="btn" data-act="manual">${icon('plus')} Registrar operação</button>` : ''}
          </div></div>
        <div class="grid grid-4 section">
          <div class="card tile"><div class="tile-label">Investido</div><div class="tile-value">${f.brl(s.invested)}</div><div class="tile-sub">${s.open_positions} posição(ões)</div></div>
          <div class="card tile"><div class="tile-label">Valor de mercado</div><div class="tile-value" data-lsum="mv">${f.brl(mv)}</div><div class="tile-sub">${s.unpriced_positions ? `${s.unpriced_positions} sem cotação` : quoteSourceLabel()}</div></div>
          <div class="card tile"><div class="tile-label">P&L em aberto</div><div class="tile-value ${f.tone(s.unrealized_pnl)}" data-lsum="pnl">${f.brl(s.unrealized_pnl, { sign: true })}</div><div class="tile-sub">sem custos de saída</div></div>
          <div class="card tile"><div class="tile-label">Capital livre</div><div class="tile-value">${f.brl(s.free)}</div><div class="tile-sub">de ${f.brl(s.capital)}</div></div>
        </div>
        <section class="section">
          <div class="section-title"><h2>${icon('wallet')} Posições abertas <span class="count">${data.positions.length}</span></h2></div>
          <div class="card">${data.positions.length ? data.positions.map(posCard).join('') : `<div class="empty"><div class="empty-icon">${icon('wallet', 'icon-lg')}</div><h3>Sem posições abertas</h3><p>${account === 'paper' ? 'Use "Enviar (simulação)" numa boleta ou arme a automação no modo simulação.' : 'Use "Executei" na boleta de um sinal, envie pelo MT5 ou registre uma operação manual.'}</p></div>`}</div>
        </section>
        ${ordersSection(ex)}
        <section class="section">
          <div class="section-title"><h2>${icon('clock')} Execuções registradas <span class="count">${execs.length}</span></h2>
            <div class="row">${account === 'real' ? `<button class="btn btn-sm" data-act="notes">${icon('download')} Importar nota de corretagem${unnoted ? ` <span class="badge badge-warn badge-plain" style="height:18px;padding:0 5px">${unnoted} sem nota</span>` : ''}</button>` : ''}
            <a class="btn btn-sm btn-ghost" href="/api/export/execucoes.csv?account=${account}">${icon('download')} CSV</a></div></div>
          <div class="card">${execTable(execs.slice().reverse())}</div>
        </section>`;
      applyLive(root);
    };

    const load = async () => {
      try {
        [data, execs, ex] = await Promise.all([
          get(`/api/portfolio?account=${account}`), get(`/api/executions?account=${account}`),
          get('/api/execution?health=0').catch(() => ({ orders: [], automation_log: [] })),
        ]);
        render();
        watch(data.positions.map((p) => p.ticker).filter((t) => !quoteOf(t)));
      } catch (e) {
        root.innerHTML = `<div class="banner danger">${icon('alert')}<div class="grow">${esc(e.message)}</div></div>`;
      }
    };

    const findPos = (el) => data.positions.find((p) => p.cycle_id === el.closest('[data-cycle]')?.dataset.cycle);

    root.addEventListener('click', async (e) => {
      const acc = e.target.closest('#acct [data-a]');
      if (acc) { account = acc.dataset.a; history.replaceState(null, '', `#/carteira${account === 'paper' ? '?conta=simulacao' : '?conta=real'}`); root.innerHTML = loading(); return load(); }
      const co = e.target.closest('[data-cancel-order]');
      if (co) {
        try { await post(`/api/orders/${co.dataset.cancelOrder}/cancel`, {}); toast('Ordem cancelada', 'info'); emit('data-changed'); } catch (err) { toastError(err); }
        return;
      }
      const act = e.target.closest('[data-act]');
      if (act) {
        const a = act.dataset.act;
        if (a === 'manual') return openExecutionForm({ mode: 'manual', onSaved: () => emit('data-changed') });
        if (a === 'notes') { const { openNotesImport } = await import('../components/notes_import.js'); return openNotesImport(); }
        if (a === 'sync-orders') { try { await post('/api/orders/sync', {}); } catch (err) { toastError(err); } return load(); }
        const p = findPos(act);
        if (!p) return;
        if (a === 'exit') return openExecutionForm({ mode: 'exit', position: p, signal: p.signal, onSaved: () => emit('data-changed') });
        if (a === 'send-exit') return openExitOrder(p);
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
                 <p class="hint mt-3">Use quando não houver cotação automática. Com o MT5 ao vivo, a próxima cotação substitui este valor; o preço do TradingFloors só volta a valer depois de 30 min.</p>`,
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
        const exn = execs.find((x) => String(x.id) === ed.dataset.edit);
        return openExecutionForm({ mode: 'edit', execution: exn, onSaved: () => emit('data-changed') });
      }
      const dl = e.target.closest('[data-del]');
      if (dl) {
        const exn = execs.find((x) => String(x.id) === dl.dataset.del);
        const ok = await confirmDialog({ title: 'Excluir execução', message: `Excluir ${exn.side === 'BUY' ? 'compra' : 'venda'} de ${f.qty(exn.quantity)} ${esc(exn.ticker)} a ${f.brl(exn.price)}? Posições e resultados serão recalculados.`, confirmText: 'Excluir', danger: true });
        if (!ok) return;
        try { await del(`/api/executions/${exn.id}`); toast('Execução excluída', 'info'); emit('data-changed'); } catch (err) { toastError(err); }
      }
    });

    await load();
    const off = on('data-changed', load);
    // com ordens abertas, atualiza a cada 10 s
    const timer = setInterval(() => {
      if (ex.orders.some((o) => o.is_open)) post('/api/orders/sync', {}).then(load).catch(() => {});
    }, 10000);
    return () => { off(); clearInterval(timer); };
  },
};
