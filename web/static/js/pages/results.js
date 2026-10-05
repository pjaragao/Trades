// Tela RESULTADOS — "Estou ganhando dinheiro de verdade?"
import { get, qs } from '../api.js';
import * as f from '../format.js';
import { on } from '../state.js';
import { esc, icon, loading } from '../ui.js';

const PERIODS = [['month', 'Este mês'], ['3m', '3 meses'], ['year', 'Este ano'], ['all', 'Tudo']];

function range(key) {
  const now = new Date();
  const iso = (d) => f.localInputValue(d).slice(0, 10);
  if (key === 'month') return { from: iso(new Date(now.getFullYear(), now.getMonth(), 1)) };
  if (key === '3m') return { from: iso(new Date(now.getFullYear(), now.getMonth() - 2, 1)) };
  if (key === 'year') return { from: `${now.getFullYear()}-01-01` };
  return {};
}

function kpis(r) {
  const t = (label, value, sub = '', cls = '') => `<div class="card tile"><div class="tile-label">${label}</div><div class="tile-value ${cls}">${value}</div><div class="tile-sub">${sub}</div></div>`;
  return `<div class="grid grid-4 section">
    ${t('Resultado realizado', f.brl(r.realized_pnl, { sign: true }), r.return_on_capital_pct === null ? '' : `${f.pct(r.return_on_capital_pct)} do capital`, f.tone(r.realized_pnl))}
    ${t('Operações encerradas', r.trades, r.win_rate === null ? '' : `acerto ${f.pct(r.win_rate, { sign: false })}`)}
    ${t('Profit factor', r.profit_factor === null ? '—' : r.profit_factor >= 99 ? '∞' : f.num(r.profit_factor), `ganho médio ${f.brl(r.avg_win)} · perda média ${f.brl(r.avg_loss)}`)}
    ${t('Custos pagos', f.brl(r.fees), r.fees_pct_of_gross === null ? '' : `${f.pct(r.fees_pct_of_gross, { sign: false })} do movimento de P&L`)}
    ${t('Slippage na entrada', f.pct(r.avg_entry_slippage_pct), 'positivo = paguei mais caro que o analista', r.avg_entry_slippage_pct > 0 ? 'loss' : r.avg_entry_slippage_pct < 0 ? 'gain' : '')}
    ${t('Slippage na saída', f.pct(r.avg_exit_slippage_pct), 'positivo = saí pior que o analista', r.avg_exit_slippage_pct > 0 ? 'loss' : r.avg_exit_slippage_pct < 0 ? 'gain' : '')}
    ${t('Drawdown máximo', f.brl(r.max_drawdown), 'queda do pico (realizado)')}
    ${t('Day trade', f.brl(r.day_trade_pnl, { sign: true }), 'parte tributada a 20%', f.tone(r.day_trade_pnl))}
  </div>`;
}

function byTrader(rows) {
  if (!rows.length) return '<div class="empty compact"><p>Sem operações encerradas no período.</p></div>';
  return `<div class="table-wrap"><table class="table">
    <thead><tr><th>Analista</th><th class="r">Operações</th><th class="r">Acerto</th><th class="r">Resultado</th><th class="r">Meu retorno médio</th><th class="r">Retorno do sinal</th><th class="r">Slippage entrada</th><th class="r">Custos</th></tr></thead>
    <tbody>${rows.map((r) => `<tr>
      <td><strong>${esc(r.trader)}</strong></td><td class="num r">${r.trades}</td>
      <td class="num r">${r.win_rate === null ? '—' : f.pct(r.win_rate, { sign: false })}</td>
      <td class="num r ${f.tone(r.pnl)}">${f.brl(r.pnl, { sign: true })}</td>
      <td class="num r ${f.tone(r.avg_my_return_pct)}">${f.pct(r.avg_my_return_pct)}</td>
      <td class="num r ${f.tone(r.avg_signal_return_pct)}">${f.pct(r.avg_signal_return_pct)}</td>
      <td class="num r ${r.avg_entry_slippage_pct > 0 ? 'loss' : r.avg_entry_slippage_pct < 0 ? 'gain' : ''}">${f.pct(r.avg_entry_slippage_pct)}</td>
      <td class="num r">${f.brl(r.fees)}</td></tr>`).join('')}</tbody></table></div>`;
}

function journal(trades) {
  if (!trades.length) return '<div class="empty compact"><p>Nenhuma operação encerrada no período.</p></div>';
  return `<div class="table-wrap"><table class="table">
    <thead><tr><th>Encerrada</th><th>Ativo</th><th>Analista</th><th class="r">Qtd</th><th class="r">Entrada (eu / sinal)</th><th class="r">Saída (eu / sinal)</th><th class="r">Custos</th><th class="r">Resultado</th><th class="r">Eu vs sinal</th></tr></thead>
    <tbody>${trades.map((t) => `<tr>
      <td class="nowrap">${esc(f.dateTime(t.closed_at))}<span class="cell-sub">aberta ${esc(f.date(t.opened_at))}</span></td>
      <td><span class="ticker">${esc(t.ticker)}</span>${t.day_trade_pnl ? ' <span class="badge badge-plain">DT</span>' : ''}</td>
      <td>${esc(t.trader || '—')}</td>
      <td class="num r">${f.qty(t.direction === 'LONG' ? t.buy_qty : t.sell_qty)}</td>
      <td class="num r">${f.brl(t.my_entry)}<span class="cell-sub">${t.signal ? f.brl(t.signal.preco_entrada) : '—'}</span></td>
      <td class="num r">${f.brl(t.my_exit)}<span class="cell-sub">${t.signal && t.signal.preco_saida ? f.brl(t.signal.preco_saida) : '—'}</span></td>
      <td class="num r">${f.brl(t.fees)}</td>
      <td class="num r ${f.tone(t.realized_pnl)}">${f.brl(t.realized_pnl, { sign: true })}<span class="cell-sub ${f.tone(t.return_pct)}">${f.pct(t.return_pct)}</span></td>
      <td class="num r"><span class="${f.tone(t.return_pct)}">${f.pct(t.return_pct)}</span> <span class="faint">/</span> <span class="${f.tone(t.signal_return_pct)}">${f.pct(t.signal_return_pct)}</span></td>
    </tr>`).join('')}</tbody></table></div>`;
}

function taxCard(ir) {
  const nd = ir.next_darf;
  const cov = ir.coverage;
  return `<section class="section card">
    <div class="card-head"><h2>${icon('receipt')} Imposto de renda</h2><a class="btn btn-sm" href="#/ir">Abrir Notas e IR</a></div>
    <div class="card-body"><div class="grid grid-3">
      <div><div class="muted">Próximo DARF</div><div class="mono ${nd ? 'warn-text' : ''}" style="font-size:1.2rem">${nd ? f.brl(nd.value) : 'nada a pagar'}</div>
        ${nd ? `<div class="hint">vence ${esc(f.date(nd.due_date + 'T12:00:00-03:00', { year: true }))} · ${nd.status === 'fechado' ? 'fechado com notas' : 'estimado'}</div>` : ''}</div>
      <div><div class="muted">Prejuízo a compensar</div><div class="mono" style="font-size:1.2rem">${f.brl(ir.loss_carry.swing + ir.loss_carry.day)}</div>
        <div class="hint">swing ${f.brl(ir.loss_carry.swing)} · day trade ${f.brl(ir.loss_carry.day)}</div></div>
      <div><div class="muted">Notas de corretagem</div><div class="mono" style="font-size:1.2rem">${cov.days_covered} de ${cov.days_total} pregões</div>
        <div class="hint">${cov.missing.length ? `faltam ${cov.missing.length} — sem elas o IR é estimado` : 'IR fechado com as notas'}</div></div>
    </div></div></section>`;
}

let chart;
function drawChart(canvas, curve, capital) {
  if (!window.Chart) { canvas.parentElement.innerHTML = '<p class="muted">Gráfico indisponível (sem internet para carregar o Chart.js).</p>'; return; }
  chart && chart.destroy();
  const labels = curve.map((p) => (p.date ? f.date(p.date + 'T12:00:00-03:00') : 'início'));
  const values = curve.map((p) => p.equity);
  const css = getComputedStyle(document.documentElement);
  const accent = css.getPropertyValue('--accent').trim();
  const loss = css.getPropertyValue('--danger').trim();
  const grid = 'rgba(148,163,184,0.10)';
  const last = values[values.length - 1] ?? capital;
  const color = last >= capital ? accent : loss;
  chart = new window.Chart(canvas, {
    type: 'line',
    data: { labels, datasets: [{ data: values, borderColor: color, backgroundColor: color + '22', fill: true, tension: 0.25, pointRadius: values.length > 40 ? 0 : 3, borderWidth: 2 },
      { data: values.map(() => capital), borderColor: 'rgba(148,163,184,0.45)', borderDash: [4, 4], pointRadius: 0, borderWidth: 1 }] },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => (c.datasetIndex ? `Capital inicial ${f.brl(c.parsed.y)}` : `Patrimônio ${f.brl(c.parsed.y)}`) } } },
      scales: {
        x: { grid: { color: grid }, ticks: { color: '#8b96b3', maxTicksLimit: 8 } },
        y: { grid: { color: grid }, ticks: { color: '#8b96b3', callback: (v) => f.brl(v, { dec: 0 }) } },
      },
    },
  });
}

export default {
  title: 'Resultados',
  async mount(root, params) {
    let period = 'month';
    let account = params.get('conta') === 'simulacao' ? 'paper' : 'real';
    root.innerHTML = `
      <div class="page-head"><div><h1>Resultados</h1><p class="sub">Seus números reais — preço e quantidade que você executou, com custos.</p></div>
        <div class="row wrap">
          <div class="segmented" id="acct"><button data-a="real">Real</button><button data-a="paper">Simulação</button></div>
          <div class="segmented" id="period">${PERIODS.map(([k, l]) => `<button data-p="${k}">${l}</button>`).join('')}</div>
          <a class="btn btn-sm" id="csv-op" href="/api/export/operacoes.csv">${icon('download')} Operações CSV</a>
          <a class="btn btn-sm" id="csv-ex" href="/api/export/execucoes.csv">${icon('download')} Execuções CSV</a>
        </div></div>
      <div id="res">${loading()}</div>`;
    const res = root.querySelector('#res');

    const load = async () => {
      root.querySelectorAll('#period button').forEach((b) => b.classList.toggle('active', b.dataset.p === period));
      root.querySelectorAll('#acct button').forEach((b) => b.classList.toggle('active', b.dataset.a === account));
      root.querySelector('#csv-op').href = `/api/export/operacoes.csv?account=${account}`;
      root.querySelector('#csv-ex').href = `/api/export/execucoes.csv?account=${account}`;
      res.innerHTML = loading();
      try {
        const [r, ir] = await Promise.all([get(`/api/results${qs({ ...range(period), account })}`), account === 'real' ? get('/api/ir') : null]);
        res.innerHTML = `
          ${kpis(r)}
          <section class="section card">
            <div class="card-head"><h2>${icon('chart')} Curva de patrimônio (realizado)</h2><span class="hint">começa no capital configurado (${f.brl(r.capital)})</span></div>
            <div class="card-body">${r.equity_curve.length > 1 ? '<div class="chart-box"><canvas id="eq"></canvas></div>' : '<p class="muted">A curva aparece quando houver operações encerradas no período.</p>'}</div>
          </section>
          <section class="section"><div class="section-title"><h2>Desempenho por analista</h2></div><div class="card">${byTrader(r.by_trader)}</div></section>
          <section class="section"><div class="section-title"><h2>Diário de operações <span class="count">${r.closed_trades.length}</span></h2></div><div class="card">${journal(r.closed_trades)}</div></section>
          ${account === 'real' && ir ? taxCard(ir) : ''}`;
        const cv = res.querySelector('#eq');
        if (cv) drawChart(cv, r.equity_curve, r.capital);
      } catch (e) {
        res.innerHTML = `<div class="banner danger">${icon('alert')}<div class="grow">${esc(e.message)}</div></div>`;
      }
    };

    root.querySelector('#acct').addEventListener('click', (e) => {
      const b = e.target.closest('[data-a]');
      if (!b) return;
      account = b.dataset.a;
      load();
    });
    root.querySelector('#period').addEventListener('click', (e) => {
      const b = e.target.closest('[data-p]');
      if (!b) return;
      period = b.dataset.p;
      load();
    });
    await load();
    const off = on('data-changed', load);
    return () => { off(); chart && chart.destroy(); chart = null; };
  },
};
