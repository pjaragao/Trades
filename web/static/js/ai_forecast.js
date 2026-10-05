/**
 * AI Forecast Module: Google TimesFM 2.5 time-series inference & interactive charts.
 */

let aiForecastChartInstance = null;
let activeTradesCache = [];
let currentPredictionRequestId = 0;

// Função auxiliar de formatação numérica brasileira (. milhar, , centavos)
function formatNumberBR(val, decimals = 2) {
  if (val === null || val === undefined || isNaN(val)) return '-';
  const num = parseFloat(val);
  return num.toLocaleString('pt-BR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

document.addEventListener('DOMContentLoaded', () => {
  // Inicialização sob demanda quando a aba for aberta
});

// Carrega as recomendações ativas no dropdown da aba de IA
async function initAiTab(targetTicker = null) {
  try {
    const res = await fetch('/api/trades/open');
    if (!res.ok) return;
    const trades = await res.json();
    activeTradesCache = trades;

    const selectEl = document.getElementById('ai-select-trade');
    if (selectEl) {
      selectEl.innerHTML = '<option value="">Selecione uma recomendação aberta...</option>';
      trades.forEach((t, idx) => {
        const opt = document.createElement('option');
        opt.value = idx;
        let optType = t.opcao_tipo;
        if (!optType) {
          const clean = (t.ticker || '').toUpperCase().replace('.SA', '');
          if (/^[A-Z]{4}\d{1,2}$/.test(clean)) {
            optType = 'AÇÃO';
          } else if (clean.length >= 5 && 'MNOPQRSTUVWX'.includes(clean[4])) {
            optType = 'PUT';
          } else if (clean.length >= 5 && 'ABCDEFGHIJKL'.includes(clean[4])) {
            optType = 'CALL';
          } else {
            optType = 'AÇÃO';
          }
        }
        const under = t.underlying_ticker || t.papel_principal || '';
        const underBadge = under && under !== t.ticker ? ` [${under}]` : '';
        opt.textContent = `${t.ticker}${underBadge} (${optType} - ${t.lado}) | Trader: ${t.trader_nome || 'N/A'}`;
        selectEl.appendChild(opt);
      });
    }

    // Determina se há um ticker alvo (passado como parâmetro ou já digitado no input)
    const customInput = document.getElementById('ai-custom-ticker');
    const requestedTicker = targetTicker || (customInput && customInput.value.trim() ? customInput.value.trim() : null);

    if (requestedTicker) {
      const matchIdx = trades.findIndex(t => t.ticker.toUpperCase() === requestedTicker.toUpperCase());
      if (matchIdx >= 0) {
        if (selectEl) selectEl.value = matchIdx;
        if (customInput) customInput.value = trades[matchIdx].ticker;
        runAiPredictionForTrade(trades[matchIdx]);
      } else {
        if (customInput) customInput.value = requestedTicker;
        runAiPrediction();
      }
    } else if (trades.length > 0) {
      // Padrão: seleciona a primeira recomendação se nada tiver sido escolhido ainda
      if (selectEl) selectEl.selectedIndex = 1;
      onSelectAiTrade();
    }

    loadBatchAiForecasts();

  } catch (err) {
    console.error('Erro ao inicializar aba de IA:', err);
  }
}

// Ao selecionar uma recomendação
function onSelectAiTrade() {
  const selectEl = document.getElementById('ai-select-trade');
  const idx = selectEl.value;
  if (idx === '' || !activeTradesCache[idx]) return;

  const t = activeTradesCache[idx];
  document.getElementById('ai-custom-ticker').value = t.ticker;
  runAiPredictionForTrade(t);
}

// Executa a previsão manual pelo botão
function runAiPrediction() {
  const customTicker = document.getElementById('ai-custom-ticker').value.trim();
  if (!customTicker) {
    showToast('Informe um ticker ou selecione uma recomendação.', 'error');
    return;
  }

  // Sincroniza o dropdown de seleção caso o ticker esteja na lista
  const selectEl = document.getElementById('ai-select-trade');
  const matchedIdx = activeTradesCache.findIndex(t => t.ticker.toUpperCase() === customTicker.toUpperCase());
  if (matchedIdx >= 0 && selectEl) {
    selectEl.value = matchedIdx;
  }

  if (matchedIdx >= 0) {
    runAiPredictionForTrade(activeTradesCache[matchedIdx]);
  } else {
    // Trade genérico / Ação digitada
    const clean = customTicker.toUpperCase().replace('.SA', '');
    let optType = 'ACAO';
    let tipoAtivo = 'Ações (B3)';
    if (/^[A-Z]{4}\d{1,2}$/.test(clean)) {
      optType = 'ACAO';
      tipoAtivo = 'Ações (B3)';
    } else if (clean.length >= 5 && 'MNOPQRSTUVWX'.includes(clean[4])) {
      optType = 'PUT';
      tipoAtivo = 'Opções (B3)';
    } else if (clean.length >= 5 && 'ABCDEFGHIJKL'.includes(clean[4])) {
      optType = 'CALL';
      tipoAtivo = 'Opções (B3)';
    }

    const genericTrade = {
      ticker: customTicker,
      lado: 'BUY',
      opcao_tipo: optType,
      tipo_ativo: tipoAtivo,
      strike: null,
      preco_entrada: 1.0
    };
    runAiPredictionForTrade(genericTrade);
  }
}

// Executa a inferência TimesFM via API
async function runAiPredictionForTrade(trade) {
  const requestId = ++currentPredictionRequestId;

  const btn = document.getElementById('btn-run-ai');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<svg class="spin-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation: spin 1s linear infinite;"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Processando TimesFM...`;
  }

  const horizon = parseInt(document.getElementById('ai-horizon').value) || 15;
  const payload = {
    ...trade,
    horizon: horizon
  };

  try {
    const res = await fetch('/api/ai/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      if (requestId === currentPredictionRequestId) {
        showToast('Erro ao calcular previsão TimesFM.', 'error');
      }
      return;
    }

    const data = await res.json();

    // Descarta respostas antigas caso uma nova previsão tenha sido solicitada
    if (requestId !== currentPredictionRequestId) {
      console.log(`Previsão desatualizada descartada para ${trade.ticker}`);
      return;
    }

    renderAiResults(data);
    showToast(`Previsão TimesFM para ${data.ticker} concluída!`, 'success');

  } catch (err) {
    if (requestId === currentPredictionRequestId) {
      console.error('Falha na previsão IA:', err);
      showToast('Erro ao comunicar com o servidor.', 'error');
    }
  } finally {
    if (requestId === currentPredictionRequestId && btn) {
      btn.disabled = false;
      btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg> Prever com TimesFM`;
    }
  }
}

// Renderiza dados do TimesFM nos Cards e no Gráfico
function renderAiResults(data) {
  // 1. Cards
  const scoreEl = document.getElementById('ai-card-score');
  scoreEl.textContent = `${formatNumberBR(data.ai_score, 1)}%`;
  scoreEl.className = `card-value ${data.ai_score >= 70 ? 'positive' : (data.ai_score >= 50 ? 'cyan' : 'negative')}`;

  const verdictEl = document.getElementById('ai-card-verdict');
  verdictEl.textContent = data.verdict;
  verdictEl.className = `card-value ${data.verdict_badge === 'success' ? 'positive' : (data.verdict_badge === 'danger' ? 'negative' : 'cyan')}`;
  document.getElementById('ai-card-verdict-sub').textContent = data.is_aligned ? '✓ Alinhado com a tese' : '⚠ Contra-tendência projetada';

  const undTicker = (data.underlying_ticker || data.papel_principal || data.underlying || '').replace('.SA', '').replace('^', '').replace('=X', 'USD/BRL');
  document.getElementById('ai-card-underlying').textContent = undTicker;
  document.getElementById('ai-card-underlying-sub').textContent = `Atual: ${formatNumberBR(data.current_price, 2)} → Alvo: ${formatNumberBR(data.forecast_final_price, 2)}`;

  const changeEl = document.getElementById('ai-card-change');
  const chg = data.expected_change_pct;
  changeEl.textContent = `${chg >= 0 ? '+' : ''}${formatNumberBR(chg, 2)}%`;
  changeEl.className = `card-value ${chg >= 0 ? 'positive' : 'negative'}`;
  document.getElementById('ai-card-change-sub').textContent = `Direção: ${data.predicted_direction} (Alvo: ${data.target_direction})`;

  // Atualiza badge de ativo no título do gráfico se existir
  const badgeEl = document.getElementById('ai-underlying-badge');
  if (badgeEl) {
    badgeEl.textContent = `Ativo: ${undTicker}`;
  }

  // 2. Relatório de Análise
  const isAcao = data.opcao_tipo === 'ACAO';
  const opDesc = isAcao ? `Swing Trade (${data.lado})` : `${data.opcao_tipo} (${data.lado})`;

  document.getElementById('ai-reasoning-text').innerHTML = `
    <strong>Análise TimesFM (${data.ticker}):</strong> ${data.reason}<br><br>
    • <strong>Ativo Analisado:</strong> <strong>${undTicker}</strong> na B3 (Preço atual: <strong>${formatNumberBR(data.current_price, 2)}</strong>).<br>
    • <strong>Projeção para ${data.chart_forecast.dates.length} dias úteis:</strong> ${formatNumberBR(data.forecast_final_price, 2)} (${chg >= 0 ? '+' : ''}${formatNumberBR(chg, 2)}%).<br>
    ${data.strike ? `• <strong>Strike da Opção:</strong> ${formatNumberBR(data.strike, 2)} (${data.opcao_tipo}).<br>` : ''}
    • <strong>Alinhamento:</strong> Operação sugerida: <strong>${opDesc}</strong>. O movimento esperado de <strong>${data.predicted_direction}</strong> ${data.is_aligned ? 'está favorável à tese da operação' : 'apresenta divergência em relação ao objetivo'}.
  `;

  // 3. Gráfico Chart.js
  renderAiForecastChart(data);
}

function renderAiForecastChart(data) {
  const ctx = document.getElementById('chart-ai-forecast').getContext('2d');
  if (aiForecastChartInstance) {
    aiForecastChartInstance.destroy();
  }

  const hist = data.chart_historical || { dates: [], prices: [] };
  const fc = data.chart_forecast || { dates: [], prices: [], q10: [], q90: [] };

  if (!hist.dates || hist.dates.length === 0 || !fc.dates || fc.dates.length === 0) {
    console.warn('Dados insuficientes para desenhar gráfico TimesFM');
    return;
  }

  // Monta linha do tempo contínua
  const allLabels = [...hist.dates, ...fc.dates];

  // Série Histórica
  const histData = [...hist.prices, ...Array(fc.dates.length).fill(null)];

  // Série Prevista (inicia no último preço histórico para conectar os pontos de forma contínua)
  const padLen = Math.max(0, hist.dates.length - 1);
  const lastHistPrice = hist.prices.length > 0 ? hist.prices[hist.prices.length - 1] : (fc.prices[0] || 0);

  const forecastData = Array(padLen).fill(null);
  forecastData.push(lastHistPrice);
  forecastData.push(...fc.prices);

  // Quantil Superior (90%)
  const q90Data = Array(padLen).fill(null);
  q90Data.push(lastHistPrice);
  q90Data.push(...fc.q90);

  // Quantil Inferior (10%)
  const q10Data = Array(padLen).fill(null);
  q10Data.push(lastHistPrice);
  q10Data.push(...fc.q10);

  // Linha de Strike
  const strikeData = (data.strike && data.strike > 0) ? Array(allLabels.length).fill(data.strike) : null;

  const datasets = [
    {
      label: 'Histórico',
      data: histData,
      borderColor: '#64748b',
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.1
    },
    {
      label: 'Previsão TimesFM',
      data: forecastData,
      borderColor: '#00e5ff',
      borderWidth: 2.5,
      pointRadius: 3,
      pointHoverRadius: 6,
      tension: 0.2
    },
    {
      label: 'Cone Superior (90%)',
      data: q90Data,
      borderColor: 'rgba(0, 229, 255, 0.4)',
      borderWidth: 1,
      borderDash: [4, 4],
      pointRadius: 0,
      fill: false,
      tension: 0.2
    },
    {
      label: 'Cone Inferior (10%)',
      data: q10Data,
      borderColor: 'rgba(0, 229, 255, 0.4)',
      borderWidth: 1,
      borderDash: [4, 4],
      pointRadius: 0,
      fill: '-1', // Preenche com o dataset anterior (q90Data)
      backgroundColor: 'rgba(0, 229, 255, 0.08)',
      tension: 0.2
    }
  ];

  if (strikeData) {
    datasets.push({
      label: `Strike (${formatNumberBR(data.strike, 2)})`,
      data: strikeData,
      borderColor: '#f59e0b',
      borderWidth: 1.5,
      borderDash: [6, 4],
      pointRadius: 0,
      fill: false
    });
  }

  aiForecastChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels: allLabels,
      datasets: datasets
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
            label: (ctx) => {
              if (ctx.raw === null) return '';
              return ` ${ctx.dataset.label}: ${formatNumberBR(parseFloat(ctx.raw), 2)}`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(255, 255, 255, 0.03)' },
          ticks: { color: '#64748b', maxTicksLimit: 10 }
        },
        y: {
          grid: { color: 'rgba(255, 255, 255, 0.05)' },
          ticks: {
            color: '#64748b',
            callback: (v) => formatNumberBR(v, 2)
          }
        }
      }
    }
  });
}

// Carrega mini-cards de previsão em lote para as recomendações ativas
async function loadBatchAiForecasts() {
  const container = document.getElementById('ai-batch-grid');
  if (!container) return;

  container.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted);">Processando sinais com TimesFM...</div>';

  try {
    const res = await fetch('/api/ai/active-forecasts');
    if (!res.ok) return;
    const forecasts = await res.json();

    if (!forecasts || forecasts.length === 0) {
      container.innerHTML = '<div style="grid-column: 1/-1; text-align: center; color: var(--text-muted);">Nenhum sinal ativo para análise.</div>';
      return;
    }

    container.innerHTML = forecasts.map(item => {
      const p = item.prediction;
      const isGood = p.ai_score >= 70;
      const scoreColor = isGood ? 'var(--emerald)' : (p.ai_score >= 50 ? 'var(--cyan)' : 'var(--rose)');

      return `
        <div class="glass-card" style="cursor: pointer;" onclick="selectTradeFromBatch('${item.ticker}')">
          <div class="card-header-compact">
            <span class="ticker-badge">${item.ticker}</span>
            <span class="badge ${p.verdict_badge === 'success' ? 'badge-buy' : 'badge-sell'}">${p.opcao_tipo}</span>
          </div>
          <div style="display: flex; justify-content: space-between; align-items: baseline; margin: 0.5rem 0;">
            <span style="font-size: 0.8rem; color: var(--text-secondary);">${item.trader_nome}</span>
            <span style="font-size: 1.4rem; font-weight: 800; font-family: var(--font-mono); color: ${scoreColor};">
              ${formatNumberBR(p.ai_score, 1)}%
            </span>
          </div>
          <div style="font-size: 0.75rem; color: var(--text-muted);">
            ${p.underlying.replace('.SA', '')}: ${p.expected_change_pct >= 0 ? '+' : ''}${formatNumberBR(p.expected_change_pct, 1)}% (${p.predicted_direction})
          </div>
          <div style="margin-top: 0.5rem; font-size: 0.75rem; font-weight: 600; color: ${scoreColor};">
            ${p.verdict}
          </div>
        </div>
      `;
    }).join('');

  } catch (err) {
    console.error('Erro ao carregar previsões em lote:', err);
  }
}

function selectTradeFromBatch(ticker) {
  document.getElementById('ai-custom-ticker').value = ticker;
  runAiPrediction();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
