/**
 * Backtest Module: Comunicação com o motor quantitativo e renderização de gráficos Chart.js
 */

let equityChartInstance = null;
let tradersChartInstance = null;

// Inicializa opções de filtros de traders e produtos
async function initBacktestFilters() {
  try {
    const res = await fetch('/api/backtest/filters');
    if (!res.ok) return;
    const data = await res.json();
    
    // Preenche traders
    const traderSelect = document.getElementById('bt-trader');
    if (traderSelect && data.traders) {
      traderSelect.innerHTML = '<option value="all">Todos os Traders</option>';
      data.traders.forEach(tr => {
        if (tr) {
          const opt = document.createElement('option');
          opt.value = tr;
          opt.textContent = tr;
          traderSelect.appendChild(opt);
        }
      });
    }
  } catch (err) {
    console.error('Erro ao carregar filtros de backtest:', err);
  }
}

// Executa o backtest
async function runBacktest() {
  const btn = document.getElementById('btn-run-backtest');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = 'Executando...';
  }

  const payload = {
    product: document.getElementById('bt-product').value,
    trader: document.getElementById('bt-trader').value,
    sizing_mode: document.getElementById('bt-sizing').value,
    fixed_capital: parseFloat(document.getElementById('bt-capital-trade').value) || 1000,
    initial_equity: parseFloat(document.getElementById('bt-initial-equity').value) || 10000,
    date_from: document.getElementById('bt-date-from').value || null,
    date_to: document.getElementById('bt-date-to').value || null
  };

  try {
    const res = await fetch('/api/backtest/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      showToast('Erro ao rodar backtest.', 'error');
      return;
    }

    const data = await res.json();
    renderBacktestResults(data);
    showToast('Backtest executado com sucesso!', 'success');
  } catch (err) {
    console.error('Falha no backtest:', err);
    showToast('Erro de comunicação com o servidor.', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Executar`;
    }
  }
}

// Renderiza dados e gráficos
function renderBacktestResults(data) {
  const s = data.summary;
  if (!s) return;

  // 1. Atualiza Cards
  const profitEl = document.getElementById('bt-res-profit');
  profitEl.textContent = `R$ ${s.net_profit.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  profitEl.className = `card-value ${s.net_profit >= 0 ? 'positive' : 'negative'}`;

  const roiEl = document.getElementById('bt-res-roi');
  roiEl.textContent = `ROI: ${s.roi_pct >= 0 ? '+' : ''}${s.roi_pct.toFixed(1)}% (Final: R$ ${s.final_equity.toLocaleString('pt-BR', { minimumFractionDigits: 2 })})`;

  const winRateEl = document.getElementById('bt-res-winrate');
  winRateEl.textContent = `${s.win_rate.toFixed(1)}%`;

  const tradesCountEl = document.getElementById('bt-res-trades-count');
  tradesCountEl.textContent = `${s.total_trades} trades (${s.winning_trades}V / ${s.losing_trades}D)`;

  document.getElementById('bt-res-pf').textContent = `${s.profit_factor.toFixed(2)}`;
  document.getElementById('bt-res-payoff').textContent = `Payoff: ${s.payoff.toFixed(2)}x (Méd. Win R$ ${s.avg_win.toFixed(0)} / Loss R$ ${s.avg_loss.toFixed(0)})`;

  document.getElementById('bt-res-dd').textContent = `R$ ${s.max_drawdown_val.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`;
  document.getElementById('bt-res-dd-pct').textContent = `Queda máxima: -${s.max_drawdown_pct.toFixed(1)}%`;

  // 2. Gráfico da Curva de Patrimônio (Chart.js)
  renderEquityChart(data.equity_curve);

  // 3. Gráfico de Desempenho por Trader
  renderTradersChart(data.traders_ranking);

  // 4. Tabela de Trades Simulados
  renderBacktestTable(data.trades);
}

function renderEquityChart(curveData) {
  const ctx = document.getElementById('chart-equity').getContext('2d');
  if (equityChartInstance) {
    equityChartInstance.destroy();
  }

  // Reduz densidade se houver milhares de pontos para performance
  const step = Math.max(1, Math.floor(curveData.length / 300));
  const sampled = curveData.filter((_, idx) => idx % step === 0 || idx === curveData.length - 1);

  const labels = sampled.map(p => p.date);
  const values = sampled.map(p => p.equity);

  // Gradiente Neon
  const gradient = ctx.createLinearGradient(0, 0, 0, 300);
  gradient.addColorStop(0, 'rgba(0, 229, 255, 0.35)');
  gradient.addColorStop(1, 'rgba(0, 229, 255, 0.00)');

  equityChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: 'Patrimônio (R$)',
        data: values,
        borderColor: '#00e5ff',
        borderWidth: 2,
        backgroundColor: gradient,
        fill: true,
        tension: 0.15,
        pointRadius: sampled.length > 50 ? 0 : 2,
        pointHoverRadius: 5
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(15, 21, 33, 0.95)',
          titleColor: '#00e5ff',
          bodyColor: '#fff',
          borderColor: 'rgba(255, 255, 255, 0.1)',
          borderWidth: 1,
          callbacks: {
            label: (ctx) => ` R$ ${ctx.parsed.y.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(255, 255, 255, 0.03)' },
          ticks: { color: '#64748b', maxTicksLimit: 8 }
        },
        y: {
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: {
            color: '#64748b',
            callback: (v) => `R$ ${v.toLocaleString('pt-BR')}`
          }
        }
      }
    }
  });
}

function renderTradersChart(ranking) {
  const ctx = document.getElementById('chart-traders').getContext('2d');
  if (tradersChartInstance) {
    tradersChartInstance.destroy();
  }

  const topTraders = ranking.slice(0, 6);
  const labels = topTraders.map(t => t.trader);
  const dataPnL = topTraders.map(t => t.pnl);

  const colors = dataPnL.map(v => v >= 0 ? 'rgba(16, 185, 129, 0.8)' : 'rgba(244, 63, 94, 0.8)');

  tradersChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: labels,
      datasets: [{
        data: dataPnL,
        backgroundColor: colors,
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => ` PnL: R$ ${ctx.parsed.x.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}`
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(255, 255, 255, 0.04)' },
          ticks: {
            color: '#64748b',
            callback: (v) => `R$ ${v.toLocaleString('pt-BR')}`
          }
        },
        y: {
          grid: { display: false },
          ticks: { color: '#f8fafc', font: { weight: 600 } }
        }
      }
    }
  });
}

function renderBacktestTable(trades) {
  const tbody = document.getElementById('tbody-bt-trades');
  const countEl = document.getElementById('bt-table-count');
  if (!tbody) return;

  if (countEl) countEl.textContent = `${trades.length} operações simuladas`;

  if (!trades || trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: var(--text-muted);">Nenhuma operação encontrada para os filtros selecionados.</td></tr>';
    return;
  }

  // Renderiza os primeiros 100 registros para fluidez
  const displayLimit = 100;
  tbody.innerHTML = trades.slice(0, displayLimit).map(t => {
    const isWin = t.pnl >= 0;
    const pnlClass = isWin ? 'positive' : 'negative';
    const ladoClass = t.lado === 'BUY' ? 'badge-buy' : 'badge-sell';

    return `
      <tr>
        <td><span class="ticker-badge">${t.ticker}</span></td>
        <td>${t.trader}</td>
        <td><span class="badge ${ladoClass}">${t.lado === 'BUY' ? 'COMPRA' : 'VENDA'}</span></td>
        <td style="text-align: right; font-family: var(--font-mono);">${t.quantidade.toLocaleString('pt-BR')}</td>
        <td style="text-align: right; font-family: var(--font-mono);">R$ ${t.preco_entrada.toFixed(2)}</td>
        <td style="text-align: right; font-family: var(--font-mono);">R$ ${t.preco_saida.toFixed(2)}</td>
        <td style="text-align: right; font-family: var(--font-mono); color: ${isWin ? 'var(--emerald)' : 'var(--rose)'};">
          ${t.pnl_pct >= 0 ? '+' : ''}${t.pnl_pct.toFixed(1)}%
        </td>
        <td style="text-align: right; font-family: var(--font-mono);" class="${pnlClass}">
          R$ ${t.pnl.toLocaleString('pt-BR', { minimumFractionDigits: 2 })}
        </td>
        <td style="color: var(--text-muted); font-size: 0.75rem; white-space: nowrap;">${typeof formatDateTimeBR === 'function' ? formatDateTimeBR(t.data_entrada) : t.data_entrada.slice(0, 16)}</td>
        <td style="color: var(--text-muted); font-size: 0.75rem; white-space: nowrap;">${typeof formatDateTimeBR === 'function' ? formatDateTimeBR(t.data_saida) : t.data_saida.slice(0, 16)}</td>
      </tr>
    `;
  }).join('');
}


// Sincroniza dados do Supabase
async function syncBacktestCache() {
  showToast('Sincronizando histórico com a plataforma...', 'info');
  try {
    const res = await fetch('/api/backtest/sync-cache', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast(`Sincronização concluída! ${data.synced_count} ordens catalogadas.`, 'success');
      initBacktestFilters();
      runBacktest();
    } else {
      showToast(`Erro na sincronização: ${data.error}`, 'error');
    }
  } catch (err) {
    showToast('Falha na requisição de sincronização.', 'error');
  }
}
