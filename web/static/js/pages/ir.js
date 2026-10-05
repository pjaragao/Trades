// Tela NOTAS E IR — "Quanto devo de imposto? Minhas notas estão em dia? E se eu encerrar tudo agora?"
import { get } from '../api.js';
import * as f from '../format.js';
import { on } from '../state.js';
import { esc, icon, loading, noteList } from '../ui.js';

const MONTHS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
const monthLabel = (m) => `${MONTHS[Number(m.slice(5, 7)) - 1]}/${m.slice(0, 4)}`;
const day = (iso) => f.date(`${iso}T12:00:00-03:00`);
const dayY = (iso) => f.date(`${iso}T12:00:00-03:00`, { year: true });

function statusBadge(m) {
  if (m.status === 'fechado') return `<span class="badge badge-ok" title="Todos os pregões do mês têm nota de corretagem importada">${icon('check')} Fechado com notas</span>`;
  if (m.status === 'sem_operacoes') return '<span class="badge">Sem operações</span>';
  const miss = m.missing_days?.length || 0;
  return `<span class="badge badge-est" title="Sem nota de corretagem em ${miss} pregão(ões): preços, custos e IRRF podem estar estimados">Estimado${miss ? ` · faltam ${miss} nota(s)` : ''}</span>`;
}

function tiles(rep, sim) {
  const nd = rep.next_darf;
  const cov = rep.coverage;
  const add = sim ? sim.additional_tax : null;
  return `
  <div class="grid grid-4 section">
    <div class="card tile"><div class="tile-label">Próximo DARF</div>
      <div class="tile-value ${nd ? 'warn-text' : ''}">${nd ? f.brl(nd.value) : f.brl(0)}</div>
      <div class="tile-sub">${nd ? `${esc(monthLabel(nd.month))} · vence ${esc(dayY(nd.due_date))} · ${nd.status === 'fechado' ? 'fechado' : 'estimado'}` : 'nada a pagar'}</div></div>
    <div class="card tile"><div class="tile-label">Se encerrar tudo agora</div>
      <div class="tile-value ${add > 0 ? 'warn-text' : add < 0 ? 'gain' : ''}">${sim ? f.brl(add, { sign: add !== 0 }) : '—'}</div>
      <div class="tile-sub">${sim ? `de IR no mês · resultado ${f.brl(sim.totals.pnl, { sign: true })}` : 'calculando…'}</div></div>
    <div class="card tile"><div class="tile-label">Prejuízo a compensar</div>
      <div class="tile-value">${f.brl(rep.loss_carry.swing + rep.loss_carry.day)}</div>
      <div class="tile-sub">swing ${f.brl(rep.loss_carry.swing)} · day trade ${f.brl(rep.loss_carry.day)}</div></div>
    <div class="card tile"><div class="tile-label">Notas de corretagem</div>
      <div class="tile-value">${cov.days_covered}<span class="faint" style="font-size:.6em"> / ${cov.days_total}</span></div>
      <div class="tile-sub">${cov.days_total ? (cov.missing.length ? `pregões com nota · faltam ${cov.missing.length}` : 'todos os pregões com nota') : 'nenhuma operação ainda'}</div></div>
  </div>`;
}

function simSection(sim) {
  if (!sim) return `<div class="card card-pad">${loading()}</div>`;
  const b = sim.before;
  const a = sim.after;
  if (!sim.positions.length && !sim.missing_quotes.length) {
    return '<div class="card"><div class="empty compact"><p>Sem posições abertas na conta real.</p></div></div>';
  }
  const kind = { swing: 'swing', day: '<span class="badge badge-warn">day trade</span>', misto: '<span class="badge badge-warn">swing + day trade</span>' };
  return `
  <div class="card">
    <div class="card-body">
      <div class="grid grid-3 ir-sim">
        <div><div class="lbl muted">Vendendo/zerando tudo agora</div><div class="val mono ${f.tone(sim.totals.pnl)}" style="font-size:1.3rem">${f.brl(sim.totals.pnl, { sign: true })}</div>
          <div class="hint">resultado após custos estimados (${f.brl(sim.totals.fees)}) · valor ${f.brl(sim.totals.gross)}</div></div>
        <div><div class="lbl muted">IR de ${esc(monthLabel(sim.month))}</div><div class="val mono" style="font-size:1.3rem">${f.brl(b.tax_due)} → <span class="${sim.additional_tax > 0 ? 'warn-text' : ''}">${f.brl(a.tax_due)}</span></div>
          <div class="hint">${sim.additional_tax > 0 ? `+${f.brl(sim.additional_tax)} por encerrar` : sim.additional_tax < 0 ? `${f.brl(sim.additional_tax)} (o prejuízo reduz o IR)` : 'sem IR adicional'} · DARF vence ${esc(dayY(sim.due_date))}</div></div>
        <div><div class="lbl muted">Vendas de ações no mês</div><div class="val mono" style="font-size:1.3rem">${f.brl(b.stock_sales, { dec: 0 })} → ${f.brl(a.stock_sales, { dec: 0 })}</div>
          <div class="hint">${a.stock_sales > 20000 ? '<span class="loss">acima de R$ 20 mil: lucro com ações tributado</span>' : 'até R$ 20 mil: lucro com ações isento'}</div></div>
      </div>
      ${sim.warnings.length ? `<div class="mt-4">${noteList(sim.warnings)}</div>` : ''}
    </div>
    <div class="table-wrap"><table class="table">
      <thead><tr><th>Ativo</th><th>Ordem</th><th class="r">Qtd</th><th class="r">Médio</th><th class="r">Preço</th><th class="r">Custos est.</th><th class="r">Resultado</th><th>Tipo</th></tr></thead>
      <tbody>${sim.positions.map((p) => `<tr>
        <td><span class="ticker">${esc(p.ticker)}</span><span class="cell-sub">${esc(f.ASSET_LABELS[p.asset_class] || '')}</span></td>
        <td><span class="badge ${p.side === 'SELL' ? 'badge-sell' : 'badge-buy'}">${p.side === 'SELL' ? 'Vender' : 'Recomprar'}</span></td>
        <td class="num r">${f.qty(p.quantity)}</td><td class="num r">${f.brl(p.avg_price)}</td>
        <td class="num r">${f.brl(p.price)}<span class="cell-sub">${esc(p.price_source)}</span></td>
        <td class="num r">${f.brl(p.fees)}</td>
        <td class="num r ${f.tone(p.pnl)}">${f.brl(p.pnl, { sign: true })}</td>
        <td>${kind[p.kind] || esc(p.kind)}</td></tr>`).join('')}</tbody></table></div>
    <div class="card-foot hint">Simulação com o preço atual de cada posição e custos estimados; o valor real depende do preço executado e da nota.</div>
  </div>`;
}

function detail(m) {
  const line = (label, value, cls = '') => `<dt>${label}</dt><dd class="mono ${cls}">${value}</dd>`;
  return `<div class="grid grid-3 ir-detail">
    <div><h4>Swing trade (15%)</h4><dl class="kv">
      ${line('Ações: vendas no mês', f.brl(m.stock_sales))}
      ${line('Ações: resultado', `${f.brl(m.stock_swing_pnl, { sign: true })}${m.stock_exempt ? ' <span class="badge badge-ok">isento</span>' : ''}`)}
      ${line('Opções e outros', f.brl(m.other_swing_pnl, { sign: true }))}
      ${line('Resultado tributável', f.brl(m.swing_taxable, { sign: true }))}
      ${line('Prejuízo anterior usado', f.brl(-m.swing_loss_used))}
      ${line('Base de cálculo', f.brl(m.swing_base))}
      ${line('IR (15%)', f.brl(m.swing_tax))}</dl></div>
    <div><h4>Day trade (20%)</h4><dl class="kv">
      ${line('Resultado', f.brl(m.day_trade_pnl, { sign: true }))}
      ${line('Prejuízo anterior usado', f.brl(-m.day_loss_used))}
      ${line('Base de cálculo', f.brl(m.day_base))}
      ${line('IR (20%)', f.brl(m.day_tax))}</dl></div>
    <div><h4>DARF 6015</h4><dl class="kv">
      ${line(`IRRF (${m.irrf_source === 'nota' ? 'das notas' : m.irrf_source === 'parcial' ? 'notas + estimado' : 'estimado'})`, f.brl(m.irrf_estimate))}
      ${line('IRRF abatido', f.brl(-m.irrf_used))}
      ${m.carried_from_previous ? line('Acumulado (< R$ 10)', f.brl(m.carried_from_previous)) : ''}
      ${line('IR devido', f.brl(m.tax_due), 'warn-text')}
      ${line('DARF', m.darf_value ? f.brl(m.darf_value) : (m.carried_to_next ? `acumula ${f.brl(m.carried_to_next)}` : '—'))}
      ${line('Vencimento', esc(dayY(m.due_date)))}
      ${line('Prejuízo a compensar depois', `swing ${f.brl(m.swing_loss_carry)} · DT ${f.brl(m.day_loss_carry)}`)}
      ${m.irrf_carry ? line('Saldo de IRRF', f.brl(m.irrf_carry)) : ''}</dl></div>
  </div>
  ${m.missing_days.length ? `<div class="note warning mt-3">${icon('alert')}<span>Sem nota de corretagem: ${m.missing_days.map((d) => `<strong>${esc(day(d.date))}</strong> (${esc(d.tickers.join(', '))})`).join(' · ')}.
    <button class="link-btn" data-act="notes">Importar notas</button></span></div>` : ''}`;
}

function monthsTable(rows, selected) {
  const list = rows.filter((m) => m.status !== 'sem_operacoes' || m.darf_value || m.carried_from_previous).slice().reverse();
  if (!list.length) return '<div class="empty compact"><p>Nenhuma operação encerrada ainda.</p></div>';
  return `<div class="table-wrap"><table class="table ir-table">
    <thead><tr><th>Mês</th><th>Situação</th><th class="r">Vendas ações</th><th class="r">Ações</th><th class="r">Opções/outros</th><th class="r">Day trade</th><th class="r">IR devido</th><th class="r">IRRF</th><th class="r">DARF</th><th>Vence</th></tr></thead>
    <tbody>${list.map((m) => `
      <tr class="clickable ${selected === m.month ? 'open' : ''}" data-month="${m.month}">
        <td class="nowrap">${icon('chevron')} <strong>${esc(monthLabel(m.month))}</strong>${m.in_progress ? '<span class="cell-sub">em andamento</span>' : ''}</td>
        <td>${statusBadge(m)}</td>
        <td class="num r">${f.brl(m.stock_sales, { dec: 0 })}</td>
        <td class="num r ${f.tone(m.stock_swing_pnl)}">${f.brl(m.stock_swing_pnl, { sign: true })}${m.stock_exempt ? '<span class="cell-sub gain">isento</span>' : ''}</td>
        <td class="num r ${f.tone(m.other_swing_pnl)}">${f.brl(m.other_swing_pnl, { sign: true })}</td>
        <td class="num r ${f.tone(m.day_trade_pnl)}">${f.brl(m.day_trade_pnl, { sign: true })}</td>
        <td class="num r">${f.brl(m.tax_due)}</td>
        <td class="num r">${f.brl(m.irrf_used)}</td>
        <td class="num r ${m.darf_value ? 'warn-text' : 'faint'}"><strong>${m.darf_value ? f.brl(m.darf_value) : '—'}</strong></td>
        <td class="nowrap">${m.darf_value ? esc(dayY(m.due_date)) : '—'}</td>
      </tr>`).join('')}</tbody></table></div>`;
}

function yearsSection(years) {
  if (!years.length) return '';
  return `<div class="grid grid-2">${years.map((y) => `
    <div class="card">
      <div class="card-head"><h3>${y.year}</h3>${y.status === 'fechado' ? '<span class="badge badge-ok">Fechado com notas</span>' : '<span class="badge badge-est">Estimado</span>'}</div>
      <div class="card-body"><dl class="kv">
        <dt>Lucro isento com ações (vendas até R$ 20 mil/mês)</dt><dd class="mono gain">${f.brl(y.exempt_gains)}</dd>
        <dt>Ações tributadas (swing)</dt><dd class="mono ${f.tone(y.stock_swing)}">${f.brl(y.stock_swing, { sign: true })}</dd>
        <dt>Opções e outros (swing)</dt><dd class="mono ${f.tone(y.other_swing)}">${f.brl(y.other_swing, { sign: true })}</dd>
        <dt>Day trade</dt><dd class="mono ${f.tone(y.day_trade)}">${f.brl(y.day_trade, { sign: true })}</dd>
        <dt>DARF (IR pago/a pagar)</dt><dd class="mono">${f.brl(y.darf)}</dd>
        <dt>IRRF retido</dt><dd class="mono">${f.brl(y.irrf)}</dd>
        <dt>Prejuízo a compensar no fim do ano</dt><dd class="mono">swing ${f.brl(y.swing_loss_end || 0)} · DT ${f.brl(y.day_loss_end || 0)}</dd>
      </dl>
      <p class="hint mt-3">Na declaração: o lucro isento vai em Rendimentos Isentos e Não Tributáveis; os resultados mensais e o IR pago, em Renda Variável (Operações Comuns/Day Trade).</p></div>
    </div>`).join('')}</div>`;
}

export default {
  title: 'Notas e IR',
  async mount(root) {
    root.innerHTML = loading();
    let rep = null;
    let sim = null;
    let selected = null; // mês com a memória de cálculo aberta

    const render = () => {
      root.innerHTML = `
        <div class="page-head"><div><h1>Notas e IR</h1>
          <p class="sub">Imposto de renda das suas operações reais. O mês só fica <strong>fechado</strong> com as notas de corretagem de todos os pregões; sem elas, o valor é <strong>estimado</strong>.</p></div>
          <div class="row wrap"><button class="btn btn-primary" data-act="notes">${icon('download')} Importar notas de corretagem</button></div></div>
        ${rep.coverage.missing.length ? `<div class="banner warning">${icon('alert')}<div class="grow"><strong>${rep.coverage.missing.length} pregão(ões) sem nota:</strong>
          ${rep.coverage.missing.slice(-8).map((d) => esc(dayY(d.date))).join(', ')}${rep.coverage.missing.length > 8 ? '…' : ''}. Importe as notas para fechar o IR com os valores reais.</div>
          <button class="btn btn-sm" data-act="notes">Importar</button></div>` : ''}
        ${tiles(rep, sim)}
        <section class="section">
          <div class="section-title"><h2>${icon('exit')} Se eu encerrar todas as posições agora</h2>
            <button class="btn btn-sm btn-ghost" data-act="resim">${icon('refresh')} Recalcular</button></div>
          ${simSection(sim)}
        </section>
        <section class="section">
          <div class="section-title"><h2>${icon('book')} Apuração mensal</h2><span class="hint">clique no mês para ver a memória de cálculo</span></div>
          <div class="card">${monthsTable(rep.months, selected)}</div>
          ${(() => {
            const m = selected && rep.months.find((x) => x.month === selected);
            return m ? `<div class="card mt-4" id="ir-detail"><div class="card-head"><h3>Memória de cálculo · ${esc(monthLabel(m.month))}</h3>
              <span class="row">${statusBadge(m)}<button class="btn btn-sm btn-ghost btn-icon" data-act="close-detail" title="Fechar">${icon('x')}</button></span></div>
              <div class="card-body">${detail(m)}</div></div>` : '';
          })()}
        </section>
        <section class="section">
          <div class="section-title"><h2>${icon('shield')} Resumo para a declaração anual</h2></div>
          ${yearsSection(rep.years)}
        </section>
        <ul class="notes section">${rep.notes.map((n) => `<li class="note info">${icon('info')}<span>${esc(n)}</span></li>`).join('')}</ul>`;
    };

    const loadSim = async () => {
      try { sim = await get('/api/ir/simulate-close'); } catch { sim = null; }
      if (rep) render();
    };
    const load = async () => {
      try {
        rep = await get('/api/ir');
        render();
        loadSim();
      } catch (e) {
        root.innerHTML = `<div class="banner danger">${icon('alert')}<div class="grow">${esc(e.message)}</div></div>`;
      }
    };

    root.addEventListener('click', async (e) => {
      const act = e.target.closest('[data-act]');
      if (act?.dataset.act === 'notes') {
        const { openNotesImport } = await import('../components/notes_import.js');
        openNotesImport();
        return;
      }
      if (act?.dataset.act === 'resim') { sim = null; render(); loadSim(); return; }
      if (act?.dataset.act === 'close-detail') { selected = null; render(); return; }
      const tr = e.target.closest('tr[data-month]');
      if (tr) {
        selected = selected === tr.dataset.month ? null : tr.dataset.month;
        render();
        root.querySelector('#ir-detail')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    });

    await load();
    const off = on('data-changed', load);
    const timer = setInterval(loadSim, 60000); // preços mudam: refaz a simulação a cada minuto
    return () => { off(); clearInterval(timer); };
  },
};
