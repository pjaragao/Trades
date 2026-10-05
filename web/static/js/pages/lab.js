// Tela LABORATÓRIO — "Quem vale a pena seguir? Que ideias novas existem?"
import { get, post } from '../api.js';
import * as f from '../format.js';
import { state } from '../state.js';
import { copyableBadge, esc, icon, loading, toastError } from '../ui.js';

const TABS = [
  ['analistas', 'Analistas', 'eye'],
  ['backtest', 'Backtest de cópia', 'chart'],
  ['screeners', 'Screeners', 'filter'],
  ['ia', 'Previsão IA', 'brain'],
  ['conhecimento', 'Base de conhecimento', 'book'],
];

const estBadge = (txt = 'Estimativa') => `<span class="badge badge-est" title="Valores calculados por modelo/aproximação — não são cotações reais">${esc(txt)}</span>`;
let charts = [];
const destroyCharts = () => { charts.forEach((c) => c.destroy()); charts = []; };

function lineChart(canvas, labels, datasets, { money = true } = {}) {
  if (!window.Chart) { canvas.parentElement.innerHTML = '<p class="muted">Gráfico indisponível (Chart.js não carregou).</p>'; return; }
  const grid = 'rgba(148,163,184,0.10)';
  charts.push(new window.Chart(canvas, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: datasets.some((d) => d.label), labels: { color: '#9aa5c0', boxWidth: 12 } } },
      scales: {
        x: { grid: { color: grid }, ticks: { color: '#8b96b3', maxTicksLimit: 8 } },
        y: { grid: { color: grid }, ticks: { color: '#8b96b3', callback: (v) => (money ? f.brl(v, { dec: 0 }) : f.num(v)) } },
      },
    },
  }));
}

// ---------------------------------------------------------------- Analistas
async function tabAnalysts(el) {
  el.innerHTML = loading();
  const rows = (await get('/api/traders')).filter((r) => r.closed + r.open > 0);
  let onlyCopy = false;
  const render = () => {
    const list = rows.filter((r) => !onlyCopy || r.copyable === 'yes').sort((a, b) => (b.followed - a.followed) || ((b.closed || 0) - (a.closed || 0)));
    el.innerHTML = `
      <div class="toolbar"><label class="check"><input type="checkbox" id="only-copy" ${onlyCopy ? 'checked' : ''}> Só copiáveis manualmente</label>
        <span class="grow"></span><span class="hint">Histórico do TradingFloors (retorno % do sinal, sem custos). "Copiável" = costuma manter a posição de um pregão para outro.</span></div>
      <div class="card table-wrap"><table class="table table-compact">
        <thead><tr><th>Analista</th><th>Classe</th><th class="r">Encerradas</th><th class="r">Abertas</th><th class="r">Acerto</th><th class="r">Retorno médio</th><th class="r">Ganho / perda médios</th><th class="r">Profit factor</th><th class="r">Permanência</th><th class="r">Mesmo dia</th><th>Cópia manual</th></tr></thead>
        <tbody>${list.map((r) => `<tr>
          <td><strong>${esc(r.trader)}</strong>${r.followed ? ' <span class="badge badge-info badge-plain">seguindo</span>' : ''}</td>
          <td>${esc(r.asset_label)}</td>
          <td class="num r">${r.closed}</td><td class="num r">${r.open}</td>
          <td class="num r">${r.win_rate === null ? '—' : f.pct(r.win_rate, { sign: false })}</td>
          <td class="num r ${f.tone(r.avg_return_pct)}">${f.pct(r.avg_return_pct, { dec: 2 })}</td>
          <td class="num r"><span class="gain">${f.pct(r.avg_win_pct)}</span> / <span class="loss">${f.pct(r.avg_loss_pct)}</span></td>
          <td class="num r">${r.profit_factor === null ? '—' : r.profit_factor >= 99 ? '∞' : f.num(r.profit_factor)}</td>
          <td class="num r">${r.median_hold_days === null ? '—' : `${f.num(r.median_hold_days, 1)} d`}</td>
          <td class="num r">${r.same_day_share === null ? '—' : f.pct(r.same_day_share, { sign: false, dec: 0 })}</td>
          <td>${copyableBadge(r)}</td></tr>`).join('')}</tbody></table></div>`;
    el.querySelector('#only-copy').onchange = (e) => { onlyCopy = e.target.checked; render(); };
  };
  render();
}

// ---------------------------------------------------------------- Backtest
async function tabBacktest(el) {
  const prefs = state.prefs;
  const traders = state.system?.traders || [];
  const followed = new Set((prefs?.follow?.traders || []).map((t) => t.toLowerCase()));
  el.innerHTML = `
    <div class="lab-grid">
      <div class="card">
        <div class="card-head"><h3>${icon('filter')} Parâmetros</h3></div>
        <div class="card-body stack">
          <div class="field"><span class="label">Analistas</span>
            <div class="pick-list" id="bt-traders">${traders.map((t) => `<button type="button" class="pick ${followed.has(t.toLowerCase()) ? 'on' : ''}" data-v="${esc(t)}">${esc(t)}</button>`).join('')}</div></div>
          <div class="field"><span class="label">Classes</span>
            <div class="pick-list" id="bt-classes">${['OPCAO', 'ACAO', 'FUTURO'].map((c) => `<button type="button" class="pick ${['OPCAO', 'ACAO'].includes(c) ? 'on' : ''}" data-v="${c}">${esc(f.ASSET_LABELS[c])}</button>`).join('')}</div></div>
          <div class="form-grid">
            <div class="field"><label for="bt-from">De</label><input id="bt-from" class="input" type="date"></div>
            <div class="field"><label for="bt-to">Até</label><input id="bt-to" class="input" type="date"></div>
            <div class="field"><label for="bt-cap">Capital inicial</label><input id="bt-cap" class="input num" value="${f.num(prefs?.capital?.total ?? 10000)}"></div>
            <div class="field"><label for="bt-vpt">Valor por trade</label><input id="bt-vpt" class="input num" value="${f.num(prefs?.sizing?.value_per_trade ?? 1000)}"></div>
            <div class="field span-2"><label for="bt-slip">Slippage da cópia manual (% por ponta)</label><input id="bt-slip" class="input num" value="1,0">
              <span class="hint">Quanto pior que o analista você entra e sai, em média.</span></div>
          </div>
          <label class="check"><input type="checkbox" id="bt-skip" checked> Pular operações abertas e fechadas no mesmo dia</label>
          <button class="btn btn-primary" id="bt-run">${icon('play')} Simular</button>
        </div>
      </div>
      <div id="bt-res" class="stack"><div class="card"><div class="empty"><div class="empty-icon">${icon('chart', 'icon-lg')}</div><h3>"E se eu tivesse copiado?"</h3><p>Simula seguir os analistas escolhidos com o seu tamanho de posição, capital livre, custos e atraso de cópia.</p></div></div></div>
    </div>`;
  el.addEventListener('click', (e) => { const p = e.target.closest('.pick'); if (p) p.classList.toggle('on'); });
  el.querySelector('#bt-run').onclick = async () => {
    const res = el.querySelector('#bt-res');
    const picks = (id) => [...el.querySelectorAll(`#${id} .pick.on`)].map((b) => b.dataset.v);
    res.innerHTML = `<div class="card">${loading('Simulando…')}</div>`;
    try {
      const r = await post('/api/lab/backtest', {
        traders: picks('bt-traders'), asset_classes: picks('bt-classes'),
        date_from: el.querySelector('#bt-from').value, date_to: el.querySelector('#bt-to').value,
        initial_capital: f.parseNum(el.querySelector('#bt-cap').value), value_per_trade: f.parseNum(el.querySelector('#bt-vpt').value),
        slippage_pct: f.parseNum(el.querySelector('#bt-slip').value) ?? 1, skip_intraday: el.querySelector('#bt-skip').checked,
      });
      const s = r.summary;
      const tile = (l, v, sub = '', cls = '') => `<div class="card tile"><div class="tile-label">${l}</div><div class="tile-value ${cls}">${v}</div><div class="tile-sub">${sub}</div></div>`;
      destroyCharts();
      res.innerHTML = `
        <div class="grid grid-4">
          ${tile('Resultado líquido', f.brl(s.net_pnl, { sign: true }), `${f.pct(s.return_pct)} do capital`, f.tone(s.net_pnl))}
          ${tile('Operações', s.trades, `de ${s.signals} sinais · acerto ${s.win_rate === null ? '—' : f.pct(s.win_rate, { sign: false })}`)}
          ${tile('Custos', f.brl(s.fees), `PF ${s.profit_factor === null ? '—' : s.profit_factor >= 99 ? '∞' : f.num(s.profit_factor)}`)}
          ${tile('Drawdown máx.', f.brl(s.max_drawdown), s.max_drawdown_pct === null ? '' : f.pct(s.max_drawdown_pct, { sign: false }))}
        </div>
        <div class="card"><div class="card-head"><h3>Patrimônio simulado</h3><span class="hint">retorno médio: você ${f.pct(s.avg_my_return_pct)} · sinal ${f.pct(s.avg_signal_return_pct)} · permanência ${s.avg_hold_days ?? '—'} d</span></div>
          <div class="card-body"><div class="chart-box"><canvas id="bt-chart"></canvas></div></div></div>
        ${Object.keys(s.skipped).length ? `<div class="banner info">${icon('info')}<div class="grow">Sinais não simulados: ${Object.entries(s.skipped).map(([k, v]) => `${esc(k)}: <strong>${v}</strong>`).join(' · ')}</div></div>` : ''}
        <div class="card table-wrap"><table class="table"><thead><tr><th>Analista</th><th class="r">Operações</th><th class="r">Acerto</th><th class="r">Resultado</th><th class="r">Custos</th><th class="r">Retorno médio do sinal</th></tr></thead>
          <tbody>${r.by_trader.map((t) => `<tr><td><strong>${esc(t.trader)}</strong></td><td class="num r">${t.trades}</td><td class="num r">${f.pct(t.win_rate, { sign: false })}</td><td class="num r ${f.tone(t.pnl)}">${f.brl(t.pnl, { sign: true })}</td><td class="num r">${f.brl(t.fees)}</td><td class="num r ${f.tone(t.avg_signal_return_pct)}">${f.pct(t.avg_signal_return_pct)}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">Nenhuma operação simulada.</td></tr>'}</tbody></table></div>
        <div class="card table-wrap"><div class="card-head"><h3>Operações simuladas <span class="count faint">${r.trades.length}</span></h3></div><table class="table">
          <thead><tr><th>Entrada</th><th>Saída</th><th>Ativo</th><th>Analista</th><th class="r">Qtd</th><th class="r">Entrada</th><th class="r">Saída</th><th class="r">Custos</th><th class="r">Resultado</th></tr></thead>
          <tbody>${r.trades.slice(0, 150).map((t) => `<tr><td>${esc(f.dateTime(t.entry_at))}</td><td>${esc(f.dateTime(t.exit_at))}</td><td><span class="ticker">${esc(t.ticker)}</span></td><td>${esc(t.trader)}</td><td class="num r">${f.qty(t.qty)}</td><td class="num r">${f.price(t.entry)}</td><td class="num r">${f.price(t.exit)}</td><td class="num r">${f.brl(t.fees)}</td><td class="num r ${f.tone(t.pnl)}">${f.brl(t.pnl, { sign: true })}<span class="cell-sub">${f.pct(t.return_pct)}</span></td></tr>`).join('')}</tbody></table></div>`;
      const css = getComputedStyle(document.documentElement);
      const curve = r.equity_curve;
      lineChart(res.querySelector('#bt-chart'), curve.map((p) => (p.date ? f.date(p.date + 'T12:00:00-03:00', { year: true }) : 'início')),
        [{ data: curve.map((p) => p.equity), borderColor: css.getPropertyValue('--accent').trim(), backgroundColor: 'rgba(34,211,166,0.12)', fill: true, pointRadius: 0, tension: 0.2, borderWidth: 2 }]);
    } catch (err) {
      res.innerHTML = `<div class="banner danger">${icon('alert')}<div class="grow">${esc(err.message)}</div></div>`;
    }
  };
}

// ---------------------------------------------------------------- Screeners
const SCREENER_COLS = {
  put_selling: [['Ativo', (i) => `<span class="ticker">${esc(i.symbol)}</span><span class="cell-sub">${esc(i.company_name)}</span>`], ['Preço', (i) => f.brl(i.current_price), 'r'], ['ATR 14', (i) => f.brl(i.atr_14), 'r'], ['Strike (−1 ATR)', (i) => `${f.brl(i.standard_setup.strike)}<span class="cell-sub">${f.pct(-i.standard_setup.safety_margin_pct)}</span>`, 'r'], ['Prêmio est.', (i) => f.brl(i.standard_setup.estimated_premium), 'r'], ['% a.m.', (i) => f.pct(i.standard_setup.monthly_yield_pct, { sign: false, dec: 2 }), 'r'], ['% do CDI', (i) => f.pct(i.standard_setup.cdi_ratio_pct, { sign: false, dec: 0 }), 'r'], ['Vencimento', (i) => `${esc(i.expiration_date)}<span class="cell-sub">${i.days_to_expiration} d</span>`]],
  bull_spread: [['Ativo', (i) => `<span class="ticker">${esc(i.ticker)}</span><span class="cell-sub">${esc(i.name)}</span>`], ['Preço', (i) => f.brl(i.current_spot), 'r'], ['Compra CALL', (i) => `${f.brl(i.strike_long)}<span class="cell-sub">${esc(i.ticker_long)}*</span>`, 'r'], ['Vende CALL', (i) => `${f.brl(i.strike_short)}<span class="cell-sub">${esc(i.ticker_short)}*</span>`, 'r'], ['Custo líq. est.', (i) => f.brl(i.cost_net), 'r'], ['Lucro máx.', (i) => f.brl(i.max_profit), 'r'], ['Retorno máx.', (i) => f.pct(i.roi_pct, { sign: false, dec: 0 }), 'r'], ['Breakeven', (i) => f.brl(i.breakeven), 'r']],
  covered_call: [['Ativo', (i) => `<span class="ticker">${esc(i.ticker)}</span><span class="cell-sub">${esc(i.name)}</span>`], ['Preço', (i) => f.brl(i.current_spot), 'r'], ['Vende CALL', (i) => `${f.brl(i.strike)}<span class="cell-sub">${esc(i.option_ticker)}*</span>`, 'r'], ['Prêmio est.', (i) => f.brl(i.premium), 'r'], ['% a.m.', (i) => f.pct(i.monthly_yield_pct, { sign: false, dec: 2 }), 'r'], ['% do CDI', (i) => f.pct(i.cdi_ratio_pct, { sign: false, dec: 0 }), 'r'], ['Se exercido', (i) => f.pct(i.total_if_exercised_pct), 'r'], ['Vencimento', (i) => esc(i.expiration_date)]],
  swing_trade: [['Ativo', (i) => `<span class="ticker">${esc(i.ticker)}</span><span class="cell-sub">${esc(i.name)}</span>`], ['Setup', (i) => `${esc(i.trigger_type)}<span class="cell-sub">${esc(i.signal_strength)}</span>`], ['Preço', (i) => f.brl(i.current_price), 'r'], ['IFR', (i) => f.num(i.rsi14, 1), 'r'], ['Dist. MM20', (i) => f.pct(i.dist_mm20_pct), 'r'], ['Stop', (i) => `${f.brl(i.stop_loss)}<span class="cell-sub">−${f.num(i.stop_loss_pct, 1)}%</span>`, 'r'], ['Alvos', (i) => `${f.brl(i.target_1)} / ${f.brl(i.target_2)}`, 'r'], ['Score', (i) => `${f.num(i.score, 0)}${i.is_actionable ? ' <span class="badge badge-ok badge-plain">acionável</span>' : ''}`, 'r']],
  futures_levels: [['Ativo', (i) => `<span class="ticker">${esc(i.ticker)}</span><span class="cell-sub">${esc(i.name)}</span>`], ['Fech. anterior', (i) => f.price(i.previous_close), 'r'], ['S2 / S1', (i) => `${f.price(i.s2)} / ${f.price(i.s1)}`, 'r'], ['Pivô', (i) => f.price(i.pivot_point), 'r'], ['R1 / R2', (i) => `${f.price(i.r1)} / ${f.price(i.r2)}`, 'r'], ['Compra (suporte)', (i) => `${esc(i.buy_setup.entry_zone)}<span class="cell-sub">alvo ${esc(i.buy_setup.target)}</span>`], ['Venda (resistência)', (i) => `${esc(i.sell_setup.entry_zone)}<span class="cell-sub">alvo ${esc(i.sell_setup.target)}</span>`]],
};

async function tabScreeners(el) {
  el.innerHTML = loading();
  const data = await get('/api/lab/screeners');
  const cdi = data.rates.cdi;
  el.innerHTML = `
    <div class="banner warning">${icon('alert')}<div class="grow"><strong>Tudo aqui é estimativa.</strong> Prêmios por Black-Scholes com volatilidade fixa, tickers de opção ilustrativos (*) e cotações diárias do Yahoo Finance. Confira a série real e o preço no Home Broker antes de operar.
      CDI usado: <strong class="mono">${f.num(cdi.value, 2)}% a.a.</strong> ${cdi.source === 'bcb' ? `(BCB, ${esc(cdi.date)})` : cdi.source === 'cache' ? '(último valor salvo do BCB)' : '(valor fixo — BCB indisponível)'}</div></div>
    <div class="grid grid-auto section">
      ${data.screeners.map((s) => `<div class="card strategy-card">
        <div class="row-between"><h3>${esc(s.name)}</h3>${estBadge()}</div>
        <p class="muted mt-2" style="font-size:var(--fs-sm)">${esc(s.about)}</p>
        <div class="row-between mt-3"><span class="faint" style="font-size:var(--fs-xs)">${esc(s.asset)} · ${esc(s.id)}</span>
          <button class="btn btn-sm" data-run="${esc(s.id)}" data-type="${esc(s.type)}">${icon('play')} Rodar</button></div></div>`).join('')}
    </div>
    <div id="scr-res" class="section"></div>
    <div class="grid grid-2 section">
      <div class="card"><div class="card-head"><h3>Alocação com renda (venda de PUT + coberta)</h3>${estBadge()}</div>
        <div class="card-body stack"><div class="row"><div class="input-group" style="max-width:220px"><span class="prefix">R$</span><input class="input num" id="alloc-cap" value="100.000"></div>
          <button class="btn btn-sm" id="alloc-run">Simular</button></div><div id="alloc-res"></div></div></div>
      <div class="card"><div class="card-head"><h3>Backtest histórico — venda de PUT −1 ATR</h3>${estBadge('Simulação')}</div>
        <div class="card-body stack"><div class="row wrap"><input class="input num" id="ob-sym" value="VALE3" style="max-width:120px"><input class="input" id="ob-start" type="date" value="2018-01-01" style="max-width:170px">
          <button class="btn btn-sm" id="ob-run">Rodar</button></div><div id="ob-res"></div></div></div>
    </div>`;

  el.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-run]');
    if (!b) return;
    const out = el.querySelector('#scr-res');
    out.innerHTML = `<div class="card">${loading('Buscando cotações e calculando… (pode levar alguns segundos)')}</div>`;
    out.scrollIntoView({ behavior: 'smooth', block: 'start' });
    try {
      const r = await get(`/api/lab/screener/${encodeURIComponent(b.dataset.run)}`);
      const cols = SCREENER_COLS[b.dataset.type] || [];
      const items = r.items || [];
      out.innerHTML = `<div class="card"><div class="card-head"><h3>${esc(r.strategy_name)} ${estBadge()}</h3><span class="hint">${items.length} ativo(s)${r.expiration_date ? ` · vencimento ${esc(r.expiration_date)}` : ''}</span></div>
        ${items.length ? `<div class="table-wrap"><table class="table"><thead><tr>${cols.map(([h, , a]) => `<th class="${a || ''}">${esc(h)}</th>`).join('')}</tr></thead>
        <tbody>${items.map((i) => `<tr>${cols.map(([, fn, a]) => `<td class="${a === 'r' ? 'num r' : ''}">${fn(i)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : '<div class="empty compact"><p>Sem dados (Yahoo Finance pode estar indisponível).</p></div>'}</div>`;
    } catch (err) { out.innerHTML = `<div class="banner danger">${icon('alert')}<div class="grow">${esc(err.message)}</div></div>`; }
  });

  el.querySelector('#alloc-run').onclick = async () => {
    const out = el.querySelector('#alloc-res');
    out.innerHTML = loading();
    try {
      const r = await post('/api/lab/allocation', { capital: f.parseNum(el.querySelector('#alloc-cap').value) });
      const a = r.allocations;
      out.innerHTML = `<dl class="kv">
        ${Object.values(a).map((x) => `<dt>${esc(x.label)} (${f.num(x.percentage, 0)}%)</dt><dd>${f.brl(x.amount_brl)}</dd>`).join('')}
        <dt>Renda mensal estimada</dt><dd>${f.brl(r.total_monthly_income_brl)} (${f.pct(r.monthly_return_pct, { sign: false, dec: 2 })})</dd>
        <dt>Equivale a</dt><dd>${f.pct(r.cdi_multiplier_pct, { sign: false, dec: 0 })} do CDI</dd></dl>
        <p class="hint mt-3">Preços das ações da cesta são aproximados e fixos no módulo; prêmios estimados.</p>`;
    } catch (err) { out.innerHTML = `<div class="note danger">${esc(err.message)}</div>`; }
  };
  el.querySelector('#ob-run').onclick = async () => {
    const out = el.querySelector('#ob-res');
    out.innerHTML = loading('Baixando histórico…');
    try {
      const r = await post('/api/lab/option-backtest', { symbol: el.querySelector('#ob-sym').value, start_date: el.querySelector('#ob-start').value });
      if (r.error) throw new Error(r.error);
      out.innerHTML = `<dl class="kv">
        <dt>Período</dt><dd>${esc(r.period)}</dd>
        <dt>Meses com ganho</dt><dd>${r.win_months}/${r.total_months} (${f.pct(r.win_rate_pct, { sign: false })})</dd>
        <dt>Estratégia</dt><dd>${f.num(r.strategy_multiple)}x</dd>
        <dt>CDI no período</dt><dd>${f.num(r.cdi_multiple)}x</dd>
        <dt>Comprar e segurar</dt><dd>${f.num(r.buy_hold_multiple)}x</dd>
        <dt>Drawdown máx.</dt><dd>${f.pct(r.max_drawdown_pct, { sign: false })}</dd></dl>
        <p class="hint mt-3">Prêmios históricos estimados (não há série histórica de opções); CDI constante no período.</p>`;
    } catch (err) { out.innerHTML = `<div class="note danger">${esc(err.message)}</div>`; }
  };
}

// ---------------------------------------------------------------- IA
async function tabAI(el) {
  el.innerHTML = loading();
  const [st, sigs] = await Promise.all([get('/api/lab/ai/status'), get('/api/signals?status=open&scope=followed&limit=200')]);
  el.innerHTML = `
    <div class="banner ${st.installed ? 'info' : 'warning'}">${icon(st.installed ? 'info' : 'alert')}<div class="grow">
      ${st.installed ? 'Google TimesFM instalado. O modelo é carregado só na primeira previsão (pode levar 1–2 min).' : 'TimesFM/torch não instalados (<code>pip install -r requirements-lab.txt</code>). Sem eles, a previsão usa só uma extrapolação estatística simples.'}
      O score é uma heurística sobre a direção prevista do ativo-objeto — <strong>não é probabilidade de acerto</strong>.</div></div>
    <div class="card card-pad">
      <div class="row wrap">
        <select class="select" id="ai-sig" style="max-width:420px">${sigs.items.map((s) => `<option value="${esc(s.id)}">${esc(s.ticker)} · ${esc(s.trader)} · ${s.underlying ? esc(s.underlying) : ''}</option>`).join('')}</select>
        <select class="select" id="ai-h" style="max-width:150px"><option value="10">10 pregões</option><option value="15" selected>15 pregões</option><option value="20">20 pregões</option></select>
        <button class="btn btn-primary" id="ai-run" ${sigs.items.length ? '' : 'disabled'}>${icon('brain')} Prever</button>
        <span class="muted" id="ai-state">${esc(st.state === 'ready' ? (st.model_loaded ? 'modelo carregado' : 'extrapolação estatística') : st.state === 'loading' ? 'carregando modelo…' : '')}</span>
      </div>
    </div>
    <div id="ai-res" class="mt-4"></div>`;
  if (!sigs.items.length) el.querySelector('#ai-res').innerHTML = '<p class="muted">Nenhum sinal aberto dos analistas que você segue.</p>';

  const run = async () => {
    const out = el.querySelector('#ai-res');
    const stEl = el.querySelector('#ai-state');
    out.innerHTML = `<div class="card">${loading('Calculando previsão…')}</div>`;
    try {
      const r = await post('/api/lab/ai/predict', { signal_id: el.querySelector('#ai-sig').value, horizon: Number(el.querySelector('#ai-h').value) });
      if (r.pending) {
        stEl.textContent = 'carregando modelo… (primeira vez demora)';
        setTimeout(run, 4000);
        return;
      }
      stEl.textContent = r.status.model_loaded ? 'modelo carregado' : 'extrapolação estatística';
      const p = r.prediction;
      destroyCharts();
      out.innerHTML = `
        <div class="grid grid-4">
          <div class="card tile"><div class="tile-label">Ativo-objeto</div><div class="tile-value">${esc(p.underlying_ticker)}</div><div class="tile-sub">${f.brl(p.current_price)} hoje</div></div>
          <div class="card tile"><div class="tile-label">Previsão no horizonte</div><div class="tile-value ${f.tone(p.expected_change_pct)}">${f.pct(p.expected_change_pct)}</div><div class="tile-sub">${f.brl(p.forecast_final_price)}</div></div>
          <div class="card tile"><div class="tile-label">Direção (sinal / modelo)</div><div class="tile-value" style="font-size:1.1rem">${esc(p.target_direction)} / ${esc(p.predicted_direction)}</div><div class="tile-sub">${p.is_aligned ? 'alinhados' : 'divergentes'}</div></div>
          <div class="card tile"><div class="tile-label">Score heurístico</div><div class="tile-value">${f.num(p.ai_score, 0)}</div><div class="tile-sub">${esc(p.verdict)}</div></div>
        </div>
        <div class="card mt-4"><div class="card-head"><h3>${esc(p.underlying_ticker)}: histórico e previsão</h3>${p.is_model ? `<span class="badge badge-info badge-plain">${esc(p.model_used)}</span>` : estBadge(p.model_used)}</div>
          <div class="card-body"><div class="chart-box"><canvas id="ai-chart"></canvas></div><p class="muted mt-3">${esc(p.reason || '')}</p></div></div>`;
      const h = p.chart_historical;
      const fc = p.chart_forecast;
      const labels = [...h.dates, ...fc.dates].map((d) => f.date(d + 'T12:00:00-03:00'));
      const pad = (arr, n) => [...Array(n).fill(null), ...arr];
      const css = getComputedStyle(document.documentElement);
      lineChart(out.querySelector('#ai-chart'), labels, [
        { label: 'Histórico', data: [...h.prices, ...Array(fc.dates.length).fill(null)], borderColor: '#9aa5c0', pointRadius: 0, borderWidth: 2 },
        { label: 'Previsão', data: pad(fc.prices, h.dates.length), borderColor: css.getPropertyValue('--accent').trim(), pointRadius: 0, borderWidth: 2, borderDash: [5, 4] },
        { label: 'Faixa 10–90%', data: pad(fc.q90, h.dates.length), borderColor: 'rgba(34,211,166,0.25)', backgroundColor: 'rgba(34,211,166,0.08)', pointRadius: 0, fill: '+1', borderWidth: 1 },
        { label: '', data: pad(fc.q10, h.dates.length), borderColor: 'rgba(34,211,166,0.25)', pointRadius: 0, borderWidth: 1 },
      ]);
    } catch (err) {
      out.innerHTML = `<div class="banner danger">${icon('alert')}<div class="grow">${esc(err.message)}</div></div>`;
    }
  };
  el.querySelector('#ai-run')?.addEventListener('click', run);
}

// ---------------------------------------------------------------- Base de conhecimento
function md(text) {
  const lines = esc(text).split('\n');
  let html = '';
  let inList = false;
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
  for (const raw of lines) {
    const l = raw.trimEnd();
    const li = l.match(/^\s*[-*]\s+(.*)/);
    if (li) { if (!inList) { html += '<ul>'; inList = true; } html += `<li>${inline(li[1])}</li>`; continue; }
    if (inList) { html += '</ul>'; inList = false; }
    const h = l.match(/^(#{1,3})\s+(.*)/);
    if (h) { html += `<h${h[1].length + 1}>${inline(h[2])}</h${h[1].length + 1}>`; continue; }
    if (/^\|/.test(l)) { html += `<div class="mono" style="font-size:var(--fs-xs);white-space:pre">${l}</div>`; continue; }
    html += l ? `<p>${inline(l)}</p>` : '';
  }
  if (inList) html += '</ul>';
  return html;
}

async function tabKnowledge(el) {
  el.innerHTML = loading();
  const kb = await get('/api/lab/knowledge');
  const group = (origin) => kb.strategies.filter((s) => s.origin === origin);
  const item = (s) => `<button class="alert-item" style="width:100%;border:0;background:none;text-align:left;color:inherit" data-doc="${esc(s.id)}" ${s.has_doc ? '' : 'disabled'}>
      <div class="alert-icon ${s.origin === 'tradingfloors' ? 'action' : 'warn'}">${icon(s.origin === 'tradingfloors' ? 'signals' : 'play')}</div>
      <div><div class="alert-title">${esc(s.name)}</div><div class="alert-body">${esc(s.source)} · ${esc(s.asset_class || '')}</div>
      <div class="alert-time">${s.live_stats ? `real: acerto ${f.pct(s.live_stats.win_rate, { sign: false })} · ${s.live_stats.closed} operações · ${esc({ yes: 'copiável', no: 'intraday', partial: 'parcial', unknown: 'poucos dados' }[s.live_stats.copyable])}` : s.claimed && s.claimed.win_rate_pct ? `declarado no vídeo: acerto ${f.pct(s.claimed.win_rate_pct, { sign: false, dec: 0 })} (não verificado)` : ''}</div></div></button>`;
  el.innerHTML = `
    <div class="lab-grid">
      <div class="stack">
        <div class="card"><div class="card-head"><h3>${icon('signals')} Analistas do TradingFloors</h3></div>${group('tradingfloors').map(item).join('')}</div>
        <div class="card"><div class="card-head"><h3>${icon('play')} Estratégias de vídeos</h3>${estBadge('Não verificado')}</div>${group('youtube').map(item).join('')}</div>
        <div class="card card-pad stack"><h3>Importar vídeo do YouTube</h3>
          <input class="input" id="yt-url" placeholder="https://www.youtube.com/watch?v=…">
          <button class="btn btn-sm" id="yt-run">${icon('download')} Analisar vídeo e canal</button><div id="yt-res" class="hint"></div>
          ${kb.channels.map((c) => `<p class="hint">Canal: <strong>${esc(c.channel_name)}</strong>${c.videos ? ` · ${c.videos} vídeos analisados` : ''}${c.updated_at ? ` · ${esc(f.date(c.updated_at, { year: true }))}` : ''}</p>`).join('')}
        </div>
      </div>
      <div class="card card-pad" id="kb-doc"><div class="empty"><div class="empty-icon">${icon('book', 'icon-lg')}</div><h3>Escolha uma estratégia</h3><p>Para analistas do TradingFloors, os números ao lado vêm do histórico real; para vídeos, são o que o autor declarou.</p></div></div>
    </div>`;
  el.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-doc]');
    if (!b) return;
    const box = el.querySelector('#kb-doc');
    box.innerHTML = loading();
    try {
      const d = await get(`/api/lab/knowledge/${encodeURIComponent(b.dataset.doc)}`);
      box.innerHTML = `<div class="kb-doc">${md(d.markdown)}</div>`;
      box.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (err) { box.innerHTML = `<div class="note danger">${esc(err.message)}</div>`; }
  });
  el.querySelector('#yt-run').onclick = async () => {
    const out = el.querySelector('#yt-res');
    out.innerHTML = '<span class="spinner"></span> analisando… (pode levar minutos)';
    try {
      const r = await post('/api/lab/youtube', { url: el.querySelector('#yt-url').value });
      out.textContent = r.success === false ? (r.error || 'Falhou') : `Ok: ${r.channel_name || ''} · ${r.strategy_candidates_count ?? r.candidates ?? ''} vídeo(s) candidatos.`;
    } catch (err) { out.textContent = err.message; }
  };
}

export default {
  title: 'Laboratório',
  async mount(root, params) {
    let tab = params.get('tab') || 'analistas';
    root.innerHTML = `
      <div class="page-head"><div><h1>Laboratório</h1><p class="sub">Quem vale a pena seguir? Que ideias novas existem? Nada aqui gera ordem — é estudo.</p></div></div>
      <div class="tabs" role="tablist">${TABS.map(([k, l, ic]) => `<button data-tab="${k}">${icon(ic)} ${esc(l)}</button>`).join('')}</div>
      <div id="lab-body"></div>`;
    const show = async () => {
      destroyCharts();
      root.querySelectorAll('[data-tab]').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
      history.replaceState(null, '', `#/laboratorio?tab=${tab}`);
      const old = root.querySelector('#lab-body');
      const body = document.createElement('div');
      body.id = 'lab-body';
      old.replaceWith(body);
      try {
        await ({ analistas: tabAnalysts, backtest: tabBacktest, screeners: tabScreeners, ia: tabAI, conhecimento: tabKnowledge }[tab] || tabAnalysts)(body);
      } catch (err) { toastError(err); body.innerHTML = `<div class="banner danger">${icon('alert')}<div class="grow">${esc(err.message)}</div></div>`; }
    };
    root.querySelector('.tabs').addEventListener('click', (e) => {
      const b = e.target.closest('[data-tab]');
      if (!b) return;
      tab = b.dataset.tab;
      show();
    });
    await show();
    return () => destroyCharts();
  },
};
