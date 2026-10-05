let strategiesData = null;
let screenerData = null;
let strategyTradesData = null;
let currentStrategySubTab = 'strat-trades';
let currentScreenerTool = 'put-selling';
let currentDbOffset = 0;
const dbLimit = 30;
let totalDbCount = 0;

// Formatação numérica uniforme: '.' para milhar e ',' para centavos (sem R$)
function formatNumberBR(val, decimals = 2) {
  if (val === null || val === undefined || val === '') return '-';
  const n = typeof val === 'number' ? val : parseFloat(String(val).replace(',', '.'));
  if (isNaN(n)) return '-';
  return n.toLocaleString('pt-BR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
window.formatNumberBR = formatNumberBR;

async function initStrategiesTab() {
  switchStrategySubTab(currentStrategySubTab);
}

function switchStrategySubTab(subTabId) {
  currentStrategySubTab = subTabId;

  // Atualiza botões
  document.querySelectorAll('.sub-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-subtab') === subTabId);
  });

  // Atualiza painéis
  document.querySelectorAll('.sub-tab-pane').forEach(pane => {
    pane.classList.toggle('active', pane.id === `subpane-${subTabId}`);
  });

  if (subTabId === 'strat-trades') {
    loadStrategyTrades();
  } else if (subTabId === 'screener') {
    switchScreenerTool(currentScreenerTool);
  } else if (subTabId === 'knowledge') {
    if (!strategiesData) loadStrategiesCatalog();
  } else if (subTabId === 'analysts-db') {
    loadDatabaseTrades(0);
    if (!strategiesData) loadStrategiesCatalog();
  }
}

async function loadStrategyTrades() {
  const tbody = document.getElementById('strat-trades-table-body');
  const countTotal = document.getElementById('strat-trades-total-count');
  const countWin = document.getElementById('strat-trades-win-count');
  const countLoss = document.getElementById('strat-trades-loss-count');
  const countActiveStrats = document.getElementById('strat-trades-active-strats');
  const selectFilter = document.getElementById('filter-strat-select');
  if (!tbody) return;

  tbody.innerHTML = '<tr><td colspan="12" style="text-align: center; padding: 2rem; color: var(--text-muted);"><span class="loading-spinner"></span> Sincronizando operações mapeadas às estratégias...</td></tr>';

  try {
    const res = await fetch('/api/strategies/trades');
    const data = await res.json();
    strategyTradesData = data;

    const trades = data.trades || [];
    
    // Contadores
    let winCount = 0;
    let lossCount = 0;
    trades.forEach(t => {
      if ((t.pnl_pct || 0) > 0 || (t.is_screener_opportunity && t.adherence && t.adherence.includes('Margem'))) winCount++;
      else if ((t.pnl_pct || 0) < 0) lossCount++;
    });

    if (countTotal) countTotal.textContent = trades.length;
    if (countWin) countWin.textContent = winCount;
    if (countLoss) countLoss.textContent = lossCount;
    if (countActiveStrats) countActiveStrats.textContent = (data.strategies_summary || []).length;

    // Popula dropdown de estratégias
    if (selectFilter && selectFilter.options.length <= 1 && data.strategies_summary) {
      data.strategies_summary.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.strategy_id;
        opt.textContent = `[${s.strategy_id}] ${s.strategy_name} (${s.count})`;
        selectFilter.appendChild(opt);
      });
    }

    renderStrategyTradesTable(trades);

  } catch (err) {
    console.error('Erro ao carregar trades por estratégia:', err);
    tbody.innerHTML = '<tr><td colspan="12" style="text-align: center; padding: 1.5rem; color: var(--accent-negative);">Falha ao carregar operações por estratégia.</td></tr>';
  }
}

function filterStrategyTrades() {
  const sel = document.getElementById('filter-strat-select');
  const selectedStrat = sel ? sel.value : 'all';
  if (!strategyTradesData || !strategyTradesData.trades) return;

  let filtered = strategyTradesData.trades;
  if (selectedStrat !== 'all') {
    filtered = filtered.filter(t => t.strategy_id === selectedStrat);
  }
  renderStrategyTradesTable(filtered);
}

function renderStrategyTradesTable(trades) {
  const tbody = document.getElementById('strat-trades-table-body');
  if (!tbody) return;

  if (trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="12" style="text-align: center; padding: 2rem; color: var(--text-muted);">Nenhuma operação em aberto para a estratégia selecionada.</td></tr>';
    return;
  }

  tbody.innerHTML = trades.map(t => {
    const isBuy = (t.lado || 'BUY').toUpperCase() === 'BUY';
    const precoEnt = formatNumberBR(t.preco_entrada, 2);
    const precoAtu = (t.preco_atual !== null && t.preco_atual !== undefined) ? formatNumberBR(t.preco_atual, 2) : '-';
    
    let pnlDisplay = '-';
    let pnlColor = 'var(--text-muted)';
    if (t.pnl_pct !== null && t.pnl_pct !== undefined) {
      const pnlVal = parseFloat(t.pnl_pct);
      pnlDisplay = `${pnlVal >= 0 ? '+' : ''}${formatNumberBR(pnlVal, 2)}%`;
      pnlColor = pnlVal > 0 ? 'var(--accent-positive)' : (pnlVal < 0 ? 'var(--accent-negative)' : 'var(--text-muted)');
    }

    // Badge de ativo
    const tipoAtivo = t.tipo_ativo || 'OPCOES';
    let tipoBadgeColor = 'var(--accent-cyan)';
    if (tipoAtivo.includes('OPCOES') || tipoAtivo.includes('Opções')) tipoBadgeColor = 'var(--accent-positive)';
    else if (tipoAtivo.includes('Cripto')) tipoBadgeColor = '#f59e0b';
    else if (tipoAtivo.includes('Forex')) tipoBadgeColor = '#3b82f6';
    else if (tipoAtivo.includes('Ações')) tipoBadgeColor = '#10b981';

    // Alvo / Stop
    const alvoStr = t.alvo_sugerido ? `🎯 ${formatNumberBR(t.alvo_sugerido, 2)}` : '-';
    const stopStr = t.stop_sugerido ? `🛑 ${formatNumberBR(t.stop_sugerido, 2)}` : '-';

    return `
      <tr>
        <td>
          <span class="badge ${t.win_rate_pct >= 80 ? 'badge-primary' : 'badge-secondary'}" style="font-size: 0.68rem; margin-bottom: 2px; display: inline-block;">${t.strategy_id}</span>
          <div style="font-size: 0.72rem; color: #fff; font-weight: 600; max-width: 180px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${t.strategy_name}">
            ${t.strategy_name}
          </div>
        </td>
        <td>
          <span class="ticker-badge" style="font-size: 0.8rem;">${t.ticker}</span>
          <div style="font-size: 0.68rem; color: var(--text-muted);">${t.produto || 'Trading Floor'}</div>
        </td>
        <td><span class="tag-pill" style="font-size: 0.65rem; padding: 2px 5px; border: 1px solid ${tipoBadgeColor}; color: ${tipoBadgeColor}; border-radius: 4px;">${tipoAtivo}</span></td>
        <td><strong style="color: var(--emerald); font-size: 0.75rem;">${t.source}</strong></td>
        <td><span class="badge ${isBuy ? 'badge-buy' : 'badge-sell'}" style="font-size: 0.65rem;">${isBuy ? 'COMPRA' : 'VENDA'}</span></td>
        <td style="text-align: right; font-family: var(--font-mono); font-size: 0.78rem;">${precoEnt}</td>
        <td style="text-align: right; font-family: var(--font-mono); font-size: 0.78rem; color: var(--cyan);">${precoAtu}</td>
        <td style="text-align: right; font-family: var(--font-mono); font-weight: 700; color: ${pnlColor}; font-size: 0.8rem;">${pnlDisplay}</td>
        <td>
          <div style="font-size: 0.72rem; color: var(--text-secondary); max-width: 200px; line-height: 1.3;" title="${t.setup_rule}">
            ${t.setup_rule}
          </div>
        </td>
        <td style="font-size: 0.72rem; font-family: var(--font-mono); white-space: nowrap;">
          <div style="color: var(--accent-positive);">${alvoStr}</div>
          <div style="color: var(--accent-negative);">${stopStr}</div>
        </td>
        <td>
          <span style="font-size: 0.7rem; padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.06); color: ${t.adherence && (t.adherence.includes('🎯') || t.adherence.includes('Margem')) ? 'var(--accent-positive)' : 'var(--text-muted)'}; display: inline-block;">
            ${t.adherence}
          </span>
        </td>
        <td style="text-align: center;">
          ${t.is_screener_opportunity ? `
            <button class="btn btn-primary btn-sm" style="font-size: 0.68rem; padding: 2px 8px;" onclick="switchStrategySubTab('screener')">
              Ver Scanner
            </button>
          ` : `
            <button class="btn btn-secondary btn-sm" style="font-size: 0.68rem; padding: 2px 8px;" onclick="executeManualTrade('${t.trade_id}')">
              Executar
            </button>
          `}
        </td>
      </tr>
    `;
  }).join('');
}

async function loadStrategiesCatalog() {
  const container = document.getElementById('strategies-catalog-list');
  const tfTable = document.getElementById('tf-traders-table-body');
  const ytCandidatesList = document.getElementById('yt-candidates-list');

  try {
    const res = await fetch('/api/strategies/catalog');
    const data = await res.json();
    strategiesData = data;

    // Renderiza Cards de Estratégias
    if (container && data.catalog && data.catalog.strategies) {
      container.innerHTML = data.catalog.strategies.map(s => `
        <div class="glass-card strategy-card" style="border-left: 4px solid ${s.win_rate_pct >= 80 ? 'var(--accent-positive)' : 'var(--accent-cyan)'}; margin-bottom: 1rem;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
            <div>
              <span class="badge ${s.status === 'ACTIVE' ? 'badge-primary' : 'badge-secondary'}" style="margin-right: 0.5rem; font-size: 0.7rem;">${s.id}</span>
              <span class="badge" style="background: rgba(255,255,255,0.06); font-size: 0.7rem;">${s.source}</span>
              <h3 style="font-size: 1.05rem; font-weight: 600; margin: 0.4rem 0 0.2rem 0; color: #fff;">${s.name}</h3>
            </div>
            <div style="text-align: right;">
              <span style="font-size: 1.25rem; font-weight: 700; color: ${s.win_rate_pct >= 80 ? 'var(--accent-positive)' : 'var(--accent-cyan)'};">
                ${s.win_rate_pct}%
              </span>
              <div style="font-size: 0.7rem; color: var(--text-muted);">Win Rate Histórico</div>
            </div>
          </div>
          
          <p style="font-size: 0.82rem; color: var(--text-secondary); margin-bottom: 0.8rem; line-height: 1.4;">
            ${s.summary}
          </p>

          <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.5rem; padding: 0.5rem; background: rgba(0,0,0,0.25); border-radius: 6px; font-size: 0.75rem; margin-bottom: 0.8rem;">
            <div>
              <span style="color: var(--text-muted); display: block;">Classe</span>
              <strong style="color: #fff;">${s.asset_class}</strong>
            </div>
            <div>
              <span style="color: var(--text-muted); display: block;">Payoff Ratio</span>
              <strong style="color: #fff;">${s.payoff_ratio}</strong>
            </div>
            <div>
              <span style="color: var(--text-muted); display: block;">Profit Factor</span>
              <strong style="color: #fff;">${s.profit_factor}</strong>
            </div>
            <div>
              <span style="color: var(--text-muted); display: block;">Max Drawdown</span>
              <strong style="color: ${s.max_drawdown_pct <= 15 ? 'var(--accent-positive)' : 'var(--accent-warning)'};">${s.max_drawdown_pct}%</strong>
            </div>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 0.5rem;">
            <div style="display: flex; gap: 0.3rem; flex-wrap: wrap;">
              ${s.symbols.map(sym => `<span class="tag-pill" style="font-size: 0.7rem; padding: 2px 6px; background: rgba(255,255,255,0.08); border-radius: 4px;">${sym}</span>`).join('')}
            </div>
            <div style="display: flex; gap: 0.3rem; align-items: center;">
              <button class="btn btn-secondary btn-sm" style="font-size: 0.72rem; padding: 3px 8px;" onclick="filterStrategyTradesById('${s.id}')" title="Ver operações no painel de Trades">
                🎯 Trades
              </button>
              <button class="btn btn-primary btn-sm" style="font-size: 0.72rem; padding: 3px 8px;" onclick="filterScreenerForStrategy('${s.id}')" title="Abrir ferramenta / simulador no Hub">
                🔍 Abrir Ferramenta
              </button>
            </div>
          </div>
        </div>
      `).join('');
    }

    // Renderiza Tabela de Traders do TradingFloor
    if (tfTable && data.tf_profile && data.tf_profile.traders) {
      tfTable.innerHTML = data.tf_profile.traders.map(t => `
        <tr>
          <td><strong>${t.trader}</strong></td>
          <td>${t.total_trades}</td>
          <td><span style="color: ${t.win_rate_pct >= 50 ? 'var(--accent-positive)' : 'var(--accent-cyan)'}; font-weight: 600;">${t.win_rate_pct}%</span></td>
          <td>${t.payoff_ratio}</td>
          <td>${t.profit_factor}</td>
          <td style="color: ${t.total_pnl >= 0 ? 'var(--accent-positive)' : 'var(--accent-negative)'}; font-weight: 600;">
            ${formatNumberBR(t.total_pnl, 2)}
          </td>
          <td>${formatNumberBR(t.expectancy_per_trade, 2)}</td>
          <td><span style="font-size: 0.75rem; color: var(--text-muted);">${Object.keys(t.top_tickers || {}).join(', ')}</span></td>
        </tr>
      `).join('');
    }

    // Renderiza Vídeos Candidatos do YouTube
    if (ytCandidatesList && data.youtube_channels && data.youtube_channels.length > 0) {
      const channel = data.youtube_channels[0];
      const candidates = channel.strategy_candidates || channel.candidate_strategy_videos || [];
      ytCandidatesList.innerHTML = candidates.map(c => `
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 0.6rem; border-bottom: 1px solid rgba(255,255,255,0.05);">
          <div>
            <div style="font-weight: 600; font-size: 0.85rem; color: #fff;">${c.title}</div>
            <div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 2px;">
              Canal: <strong>${channel.channel_name}</strong> | Tópicos: ${(c.matched_topics || c.topics || []).join(', ')}
            </div>
          </div>
          <div style="display: flex; gap: 0.5rem; align-items: center;">
            <a href="${c.url}" target="_blank" class="btn btn-secondary btn-sm" style="text-decoration: none; padding: 3px 8px; font-size: 0.75rem;">Assistir ↗</a>
            <button class="btn btn-primary btn-sm" style="padding: 3px 8px; font-size: 0.75rem;" onclick="crawlVideoUrl('${c.url}')">Analisar</button>
          </div>
        </div>
      `).join('');
    }

  } catch (err) {
    console.error('Erro ao carregar catálogo de estratégias:', err);
  }
}

let currentPutScreenerCycle = 'current';

async function switchPutScreenerCycle(cycle) {
  currentPutScreenerCycle = cycle;
  await loadPutSellingScreener(cycle);
}

async function loadPutSellingScreener(cycle = currentPutScreenerCycle) {
  const container = document.getElementById('screener-cards-grid') || document.getElementById('grid-put-selling-screener');
  const headerInfo = document.getElementById('screener-header-info') || document.getElementById('screener-expiration-info');
  if (!container) return;

  container.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; padding: 1.5rem; color: var(--text-muted);"><span class="loading-spinner"></span> Consultando mercado e volatilidade via yfinance...</div>`;

  try {
    const res = await fetch(`/api/strategies/screener?cycle=${encodeURIComponent(cycle)}`);
    const data = await res.json();
    screenerData = data;

    const putStrat = data.opportunities ? data.opportunities['STRAT-YT-001'] : null;
    const candidates = putStrat ? putStrat.candidates : [];

    if (headerInfo && putStrat) {
      const isCur = cycle === 'current';
      headerInfo.innerHTML = `
        <div style="display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; justify-content: space-between; width: 100%;">
          <div>
            <span>Vencimento Alvo B3: <strong>${putStrat.expiration_date}</strong></span> • 
            <span>Oportunidades: <strong>${candidates.length}</strong></span> • 
            <span style="color: var(--accent-positive);">CDI Base: <strong>11,75% a.a. (0,93% a.m.)</strong></span>
          </div>
          <div style="display: flex; gap: 0.35rem; align-items: center;">
            <button class="btn btn-sm ${isCur ? 'btn-primary' : 'btn-secondary'}" style="font-size: 0.72rem; padding: 2px 8px;" onclick="switchPutScreenerCycle('current')">
              Vencimento Atual (${putStrat.expiration_date.slice(3, 5)}/26)
            </button>
            <button class="btn btn-sm ${!isCur ? 'btn-primary' : 'btn-secondary'}" style="font-size: 0.72rem; padding: 2px 8px;" onclick="switchPutScreenerCycle('next')">
              Próximo Ciclo Mensal
            </button>
          </div>
        </div>
      `;
    }

    if (candidates.length === 0) {
      container.innerHTML = `<div style="grid-column: 1 / -1; text-align: center; padding: 1.5rem; color: var(--text-muted);">Nenhuma oportunidade identificada com os critérios atuais.</div>`;
      return;
    }

    container.innerHTML = candidates.map(c => {
      const std = c.standard_setup;
      const isShortPeriod = c.days_to_expiration <= 5;
      const periodLabel = isShortPeriod ? `Período (${c.days_to_expiration}d)` : `Ciclo Mensal (${c.days_to_expiration}d)`;

      return `
        <div class="glass-card" style="border: 1px solid rgba(0, 240, 255, 0.2); background: rgba(13, 20, 36, 0.75);">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
            <div>
              <span style="font-size: 1.15rem; font-weight: 700; color: #fff;">${c.symbol}</span>
              <span style="font-size: 0.75rem; color: var(--text-muted); margin-left: 0.4rem;">${c.company_name}</span>
            </div>
            <div style="text-align: right;">
              <span style="font-size: 0.95rem; font-weight: 600; color: #fff;">${formatNumberBR(c.current_price, 2)}</span>
              <div style="font-size: 0.68rem; color: var(--accent-cyan);">ATR(14): ${formatNumberBR(c.atr_14, 2)}</div>
            </div>
          </div>

          <!-- Strike Recomendado -->
          <div style="background: rgba(0, 255, 136, 0.08); border: 1px dashed rgba(0, 255, 136, 0.3); border-radius: 6px; padding: 0.6rem; margin-bottom: 0.75rem;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <div>
                <span style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;">Strike Alvo (-1 ATR)</span>
                <div style="font-size: 1.2rem; font-weight: 700; color: var(--accent-positive);">${formatNumberBR(std.strike, 2)}</div>
              </div>
              <div style="text-align: right;">
                <span style="font-size: 0.7rem; color: var(--text-muted);">Margem de Queda</span>
                <div style="font-size: 0.9rem; font-weight: 600; color: #fff;">-${formatNumberBR(std.safety_margin_pct, 1)}%</div>
              </div>
            </div>
          </div>

          <!-- Métricas de Retorno Uniformes com Venda Coberta -->
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; font-size: 0.75rem; margin-bottom: 0.75rem;">
            <div style="background: rgba(255,255,255,0.03); padding: 0.4rem; border-radius: 4px;">
              <span style="color: var(--text-muted); display: block; font-size: 0.68rem;">Prêmio da Opção</span>
              <strong style="color: #fff; display: block;">${formatNumberBR(std.estimated_premium, 2)} (${formatNumberBR(std.monthly_yield_pct, 2)}% a.m.)</strong>
              <div style="font-size: 0.68rem; color: var(--cyan); font-weight: 600;">${formatNumberBR(std.cdi_ratio_pct, 0)}% do CDI</div>
            </div>
            <div style="background: rgba(0,255,136,0.05); padding: 0.4rem; border-radius: 4px;">
              <span style="color: var(--text-muted); display: block; font-size: 0.68rem;">Total c/ Garantia CDI</span>
              <strong style="color: var(--accent-positive); display: block;">${formatNumberBR(std.total_monthly_yield_with_cdi_pct, 2)}% a.m.</strong>
              <div style="font-size: 0.68rem; color: var(--accent-positive); font-weight: 600;">${formatNumberBR(std.total_cdi_ratio_pct, 0)}% do CDI</div>
            </div>
          </div>

          <!-- Explicativo do CDI Base -->
          <div style="background: rgba(255, 255, 255, 0.03); border-radius: 4px; padding: 0.35rem 0.5rem; margin-bottom: 0.75rem; font-size: 0.68rem; color: var(--text-muted);">
            <span>📊 CDI Base: <strong>${formatNumberBR(c.cdi_annual_pct || 11.75, 2)}% a.a.</strong> (${formatNumberBR(c.cdi_monthly_pct || 0.93, 2)}% a.m.)</span>
          </div>

          <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 0.5rem; font-size: 0.72rem;">
            <span style="color: var(--text-muted);">Venc: ${c.expiration_date} (${c.days_to_expiration}d)</span>
            <div style="display: flex; gap: 0.3rem;">
              <button class="btn btn-secondary btn-sm" style="font-size: 0.7rem; padding: 2px 6px;" onclick="openTradeInAi('${c.symbol}')">⚡ IA</button>
              <button class="btn btn-secondary btn-sm" style="font-size: 0.7rem; padding: 2px 6px;" onclick="runOptionBacktest('${c.symbol}')">📊 Backtest</button>
              <button class="btn btn-primary btn-sm" style="font-size: 0.7rem; padding: 2px 7px;" onclick='executeStrategyTrade({
                strategy_id: "STRAT-YT-001",
                strategy_name: "Venda de Put OTM",
                ticker: "${std.option_ticker || c.symbol}",
                lado: "SELL",
                tipo_ativo: "OPCOES",
                preco_entrada: ${std.estimated_premium},
                alvo: 0.01,
                stop: ${std.estimated_premium * 2.5},
                quantidade: 1000,
                observacoes: "Venda de Put OTM (-1 ATR): Strike ${std.strike} - Prêmio ${std.estimated_premium}"
              })'>🚀 Executar</button>
            </div>
          </div>
        </div>
      `;
    }).join('');

  } catch (err) {
    console.error('Erro no screener:', err);
    container.innerHTML = `<div style="grid-column: 1 / -1; color: var(--accent-negative); padding: 1rem;">Falha ao carregar dados do screener.</div>`;
  }
}

async function runLiveScreener(cycle = currentPutScreenerCycle) {
  return await loadPutSellingScreener(cycle);
}
window.runLiveScreener = runLiveScreener;
window.loadPutSellingScreener = loadPutSellingScreener;

/* ==========================================================
   HUB DE FERRAMENTAS MULTIESTRATÉGIA
   ========================================================== */

function switchScreenerTool(toolId) {
  currentScreenerTool = toolId;

  // Atualiza botões pills
  const pills = document.querySelectorAll('#screener-tool-pills button');
  pills.forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-tool') === toolId);
  });

  // Atualiza visibilidade dos painéis
  document.querySelectorAll('.strategy-tool-view').forEach(view => {
    view.style.display = view.id === `tool-view-${toolId}` ? 'block' : 'none';
  });

  // Executa o carregador específico
  if (toolId === 'put-selling') {
    runLiveScreener();
  } else if (toolId === 'bull-spread') {
    loadBullSpreadScreener();
  } else if (toolId === 'swing-trade') {
    loadSwingTradeScreener();
  } else if (toolId === 'covered-call') {
    loadCoveredCallScreener();
  } else if (toolId === 'futures-levels') {
    loadFuturesLevels();
  } else if (toolId === 'portfolio-allocator') {
    runAllocationSimulation();
  }
}

function refreshCurrentScreenerTool() {
  switchScreenerTool(currentScreenerTool);
}

function filterScreenerForStrategy(stratId) {
  const toolMap = {
    'STRAT-YT-001': 'put-selling',
    'STRAT-YT-002': 'bull-spread',
    'STRAT-TF-004': 'bull-spread',
    'STRAT-YT-003': 'swing-trade',
    'STRAT-TF-003': 'swing-trade',
    'STRAT-TF-005': 'swing-trade',
    'STRAT-TF-007': 'swing-trade',
    'STRAT-TF-009': 'swing-trade',
    'STRAT-YT-004': 'covered-call',
    'STRAT-TF-001': 'futures-levels',
    'STRAT-TF-002': 'futures-levels',
    'STRAT-TF-006': 'futures-levels',
    'STRAT-TF-010': 'futures-levels',
    'STRAT-YT-007': 'portfolio-allocator'
  };

  const targetTool = toolMap[stratId] || 'put-selling';
  switchStrategySubTab('screener');
  switchScreenerTool(targetTool);
}

function filterStrategyTradesById(stratId) {
  switchStrategySubTab('strat-trades');
  const sel = document.getElementById('filter-strat-select');
  if (sel) {
    sel.value = stratId;
    filterStrategyTrades();
  }
}

async function loadBullSpreadScreener() {
  const container = document.getElementById('bull-spread-cards-grid');
  if (!container) return;
  container.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 2rem; color: var(--text-muted);"><span class="loading-spinner"></span> Calculando travas de alta com calls (Bull Spreads)...</div>';

  try {
    const res = await fetch('/api/strategies/screener/STRAT-YT-002');
    const data = await res.json();
    const items = data.items || [];

    if (items.length === 0) {
      container.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 1.5rem; color: var(--text-muted);">Nenhuma trava disponível no momento.</div>';
      return;
    }

    container.innerHTML = items.map(o => `
      <div class="glass-card" style="border: 1px solid rgba(0, 229, 255, 0.25); background: rgba(13, 20, 36, 0.75);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
          <div>
            <span style="font-size: 1.15rem; font-weight: 700; color: #fff;">${o.ticker}</span>
            <span style="font-size: 0.75rem; color: var(--text-muted); margin-left: 0.4rem;">${o.name}</span>
          </div>
          <div style="text-align: right;">
            <span style="font-size: 0.95rem; font-weight: 600; color: #fff;">Spot: ${formatNumberBR(o.current_spot, 2)}</span>
            <div style="font-size: 0.68rem; color: var(--accent-cyan);">Venc: ${o.expiration_date} (${o.days_to_exp}d)</div>
          </div>
        </div>

        <div style="background: rgba(0,0,0,0.3); border-radius: 6px; padding: 0.6rem; margin-bottom: 0.75rem;">
          <div style="display: flex; justify-content: space-between; margin-bottom: 0.3rem;">
            <span style="font-size: 0.75rem; color: var(--accent-positive);">Compra Call ATM:</span>
            <strong style="font-size: 0.8rem; color: #fff;">${o.ticker_long} (${formatNumberBR(o.strike_long, 2)}) ~ ${formatNumberBR(o.prem_long, 2)}</strong>
          </div>
          <div style="display: flex; justify-content: space-between;">
            <span style="font-size: 0.75rem; color: var(--accent-negative);">Venda Call OTM:</span>
            <strong style="font-size: 0.8rem; color: #fff;">${o.ticker_short} (${formatNumberBR(o.strike_short, 2)}) ~ ${formatNumberBR(o.prem_short, 2)}</strong>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.4rem; font-size: 0.75rem; margin-bottom: 0.75rem; text-align: center;">
          <div style="background: rgba(255,255,255,0.03); padding: 0.4rem; border-radius: 4px;">
            <span style="color: var(--text-muted); display: block; font-size: 0.68rem;">Custo Líquido</span>
            <strong style="color: #fff;">${formatNumberBR(o.cost_net, 2)}</strong>
          </div>
          <div style="background: rgba(0,255,136,0.05); padding: 0.4rem; border-radius: 4px;">
            <span style="color: var(--text-muted); display: block; font-size: 0.68rem;">Lucro Máx</span>
            <strong style="color: var(--accent-positive);">${formatNumberBR(o.max_profit, 2)}</strong>
          </div>
          <div style="background: rgba(0,229,255,0.05); padding: 0.4rem; border-radius: 4px;">
            <span style="color: var(--text-muted); display: block; font-size: 0.68rem;">ROI Projetado</span>
            <strong style="color: var(--cyan); font-weight: 700;">+${formatNumberBR(o.roi_pct, 1)}%</strong>
          </div>
        </div>

        <div style="font-size: 0.72rem; color: var(--text-muted); margin-bottom: 0.75rem; display: flex; justify-content: space-between;">
          <span>Breakeven: <strong>${formatNumberBR(o.breakeven, 2)}</strong></span>
          <span>Alvo da Ação: <strong>+${formatNumberBR(o.alvo_pct, 1)}%</strong></span>
        </div>

        <div style="display: flex; gap: 0.4rem; justify-content: flex-end; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 0.5rem;">
          <button class="btn btn-secondary btn-sm" style="font-size: 0.72rem; padding: 2px 7px;" onclick="openTradeInAi('${o.ticker}')">
            ⚡ IA
          </button>
          <button class="btn btn-primary btn-sm" style="font-size: 0.72rem; padding: 2px 8px;" onclick='executeStrategyTrade({
            strategy_id: "STRAT-YT-002",
            strategy_name: "Trava de Alta com Call",
            ticker: "${o.ticker_long}/${o.ticker_short}",
            lado: "BUY",
            tipo_ativo: "OPCOES",
            preco_entrada: ${o.cost_net},
            alvo: ${o.max_profit},
            stop: ${o.cost_net},
            quantidade: 100,
            observacoes: "Trava de Alta: Compra ${o.ticker_long} (Strike ${o.strike_long}) + Venda ${o.ticker_short} (Strike ${o.strike_short})"
          })'>
            🚀 Executar Trava
          </button>
        </div>
      </div>
    `).join('');
  } catch (err) {
    console.error('Erro ao carregar bull spread screener:', err);
    container.innerHTML = '<div style="grid-column: 1 / -1; color: var(--accent-negative); padding: 1rem;">Falha ao carregar oportunidades de travas de alta.</div>';
  }
}

async function loadSwingTradeScreener() {
  const tbody = document.getElementById('swing-trade-table-body');
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="11" style="text-align: center; padding: 2rem; color: var(--text-muted);"><span class="loading-spinner"></span> Analisando médias móveis e IFR das ações B3...</td></tr>';

  try {
    const res = await fetch('/api/strategies/screener/STRAT-YT-003');
    const data = await res.json();
    const items = data.items || [];

    if (items.length === 0) {
      tbody.innerHTML = '<tr><td colspan="11" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">Nenhuma ação em ponto de entrada no momento.</td></tr>';
      return;
    }

    tbody.innerHTML = items.map(s => {
      const isStrong = s.score >= 80;
      return `
        <tr>
          <td>
            <span class="ticker-badge">${s.ticker}</span>
            <div style="font-size: 0.7rem; color: var(--text-muted);">${s.name}</div>
          </td>
          <td><span style="font-size: 0.75rem; color: #fff;">${s.sector}</span></td>
          <td style="text-align: right; font-weight: 600; color: #fff;">${formatNumberBR(s.current_price, 2)}</td>
          <td>
            <span class="tag-pill" style="font-size: 0.7rem; ${s.rsi14 >= 50 && s.rsi14 <= 65 ? 'color: var(--accent-positive); border: 1px solid var(--accent-positive);' : 'color: var(--text-muted);'}">
              ${s.rsi14}
            </span>
          </td>
          <td>
            <span class="badge ${isStrong ? 'badge-buy' : 'badge-secondary'}" style="font-size: 0.68rem;">
              ${s.trigger_type}
            </span>
          </td>
          <td style="font-weight: 600; color: #fff;">${formatNumberBR(s.entry_price, 2)}</td>
          <td style="text-align: right; color: var(--accent-negative); font-weight: 600;">
            ${formatNumberBR(s.stop_loss, 2)}
            <div style="font-size: 0.65rem; color: var(--text-muted);">-${formatNumberBR(s.stop_loss_pct, 1)}%</div>
          </td>
          <td style="text-align: right; color: var(--accent-positive); font-weight: 600;">
            ${formatNumberBR(s.target_1, 2)}
            <div style="font-size: 0.65rem; color: var(--accent-positive);">+${formatNumberBR(s.target_1_pct, 1)}%</div>
          </td>
          <td style="text-align: right; color: var(--cyan); font-weight: 600;">
            ${formatNumberBR(s.target_2, 2)}
            <div style="font-size: 0.65rem; color: var(--cyan);">+${formatNumberBR(s.target_2_pct, 1)}%</div>
          </td>
          <td style="font-weight: 600; color: #fff;">${s.payoff_ratio}x</td>
          <td style="text-align: center;">
            <div style="display: flex; gap: 0.3rem; justify-content: center;">
              <button class="btn btn-secondary btn-sm" style="font-size: 0.7rem; padding: 2px 6px;" onclick="openTradeInAi('${s.ticker}')">⚡ IA</button>
              <button class="btn btn-primary btn-sm" style="font-size: 0.7rem; padding: 2px 7px;" onclick='executeStrategyTrade({
                strategy_id: "STRAT-YT-003",
                strategy_name: "Swing Trade 72% Acerto",
                ticker: "${s.ticker}",
                lado: "BUY",
                tipo_ativo: "Ações (B3)",
                preco_entrada: ${s.entry_price},
                alvo: ${s.target_1},
                stop: ${s.stop_loss},
                quantidade: 100,
                observacoes: "Swing Trade: Entrada ${s.entry_price} | Stop ${s.stop_loss} | Alvo 1 ${s.target_1}"
              })'>🚀 Executar</button>
            </div>
          </td>
        </tr>
      `;
    }).join('');

  } catch (err) {
    console.error('Erro ao carregar swing trade screener:', err);
    tbody.innerHTML = '<tr><td colspan="11" style="text-align: center; color: var(--accent-negative);">Falha ao consultar scanner de swing trade.</td></tr>';
  }
}

async function loadCoveredCallScreener() {
  const container = document.getElementById('covered-call-cards-grid');
  if (!container) return;
  container.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 2rem; color: var(--text-muted);"><span class="loading-spinner"></span> Calculando dividendos sintéticos para Blue Chips...</div>';

  try {
    const res = await fetch('/api/strategies/screener/STRAT-YT-004');
    const data = await res.json();
    const items = data.items || [];

    if (items.length === 0) {
      container.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 1.5rem; color: var(--text-muted);">Nenhuma oportunidade de venda coberta encontrada.</div>';
      return;
    }

    container.innerHTML = items.map(c => `
      <div class="glass-card" style="border: 1px solid rgba(245, 158, 11, 0.25); background: rgba(13, 20, 36, 0.75);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
          <div>
            <span style="font-size: 1.15rem; font-weight: 700; color: #fff;">${c.ticker}</span>
            <span style="font-size: 0.75rem; color: var(--text-muted); margin-left: 0.4rem;">${c.name}</span>
          </div>
          <div style="text-align: right;">
            <span style="font-size: 0.95rem; font-weight: 600; color: #fff;">Spot: ${formatNumberBR(c.current_spot, 2)}</span>
            <div style="font-size: 0.68rem; color: #f59e0b;">Venc: ${c.expiration_date} (${c.days_to_exp}d)</div>
          </div>
        </div>

        <div style="background: rgba(245, 158, 11, 0.08); border: 1px dashed rgba(245, 158, 11, 0.3); border-radius: 6px; padding: 0.6rem; margin-bottom: 0.75rem;">
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
              <span style="font-size: 0.68rem; color: var(--text-muted); text-transform: uppercase;">Call Sugerida para Venda</span>
              <div style="font-size: 1.15rem; font-weight: 700; color: #f59e0b;">${c.option_ticker}</div>
            </div>
            <div style="text-align: right;">
              <span style="font-size: 0.68rem; color: var(--text-muted);">Strike OTM (+3%)</span>
              <div style="font-size: 1.05rem; font-weight: 600; color: #fff;">${formatNumberBR(c.strike, 2)}</div>
            </div>
          </div>
        </div>

        <!-- Métricas de Retorno Uniformes com Venda de Put -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; font-size: 0.75rem; margin-bottom: 0.75rem;">
          <div style="background: rgba(255,255,255,0.03); padding: 0.4rem; border-radius: 4px;">
            <span style="color: var(--text-muted); display: block; font-size: 0.68rem;">Dividendo Sintético Mensal</span>
            <strong style="color: var(--accent-positive);">${formatNumberBR(c.monthly_yield_pct, 2)}% a.m.</strong>
            <div style="font-size: 0.68rem; color: var(--cyan); font-weight: 600;">${formatNumberBR(c.cdi_ratio_pct, 0)}% do CDI</div>
          </div>
          <div style="background: rgba(255,255,255,0.03); padding: 0.4rem; border-radius: 4px;">
            <span style="color: var(--text-muted); display: block; font-size: 0.68rem;">Renda p/ 1.000 Ações</span>
            <strong style="color: #fff;">${formatNumberBR(c.income_per_1000_shares, 2)}</strong>
            <div style="font-size: 0.65rem; color: var(--text-muted);">Prêmio: ${formatNumberBR(c.premium, 2)}</div>
          </div>
        </div>

        <!-- Explicativo do CDI Base -->
        <div style="background: rgba(255, 255, 255, 0.03); border-radius: 4px; padding: 0.35rem 0.5rem; margin-bottom: 0.75rem; font-size: 0.68rem; color: var(--text-muted);">
          <span>📊 CDI Base: <strong>${formatNumberBR(c.cdi_annual_pct || 11.75, 2)}% a.a.</strong> (${formatNumberBR(c.cdi_monthly_pct || 0.93, 2)}% a.m.)</span>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 0.5rem; font-size: 0.72rem;">
          <span style="color: var(--text-muted);">Proteção contra queda: <strong>${formatNumberBR(c.downside_protection_pct, 2)}%</strong></span>
          <div style="display: flex; gap: 0.3rem;">
            <button class="btn btn-secondary btn-sm" style="font-size: 0.7rem; padding: 2px 6px;" onclick="openTradeInAi('${c.ticker}')">⚡ IA</button>
            <button class="btn btn-primary btn-sm" style="font-size: 0.7rem; padding: 2px 7px;" onclick='executeStrategyTrade({
              strategy_id: "STRAT-YT-004",
              strategy_name: "Venda Coberta & Dividendos",
              ticker: "${c.option_ticker}",
              lado: "SELL",
              tipo_ativo: "OPCOES",
              preco_entrada: ${c.premium},
              alvo: 0.01,
              stop: ${c.premium * 2},
              quantidade: 1000,
              observacoes: "Venda Coberta de Call: Venda de ${c.option_ticker} (Strike ${c.strike}) - Prêmio ${c.premium}"
            })'>🚀 Executar</button>
          </div>
        </div>
      </div>
    `).join('');

  } catch (err) {
    console.error('Erro ao carregar covered call screener:', err);
    container.innerHTML = '<div style="grid-column: 1 / -1; color: var(--accent-negative); padding: 1rem;">Falha ao consultar venda coberta.</div>';
  }
}

async function loadFuturesLevels() {
  const container = document.getElementById('futures-levels-grid');
  if (!container) return;
  container.innerHTML = '<div style="grid-column: 1 / -1; text-align: center; padding: 2rem; color: var(--text-muted);"><span class="loading-spinner"></span> Calculando Pivot Points e níveis para WINFUT e WDOFUT...</div>';

  try {
    const res = await fetch('/api/strategies/screener/STRAT-TF-001');
    const data = await res.json();
    const items = data.items || [];

    container.innerHTML = items.map(l => `
      <div class="glass-card" style="border: 1px solid rgba(236, 72, 153, 0.25); background: rgba(13, 20, 36, 0.75);">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
          <div>
            <span style="font-size: 1.2rem; font-weight: 700; color: #fff;">${l.ticker}</span>
            <span style="font-size: 0.75rem; color: var(--text-muted); margin-left: 0.4rem;">${l.name}</span>
          </div>
          <div style="text-align: right;">
            <span style="font-size: 0.95rem; font-weight: 600; color: #fff;">Fechamento Ant: ${l.previous_close}</span>
            <div style="font-size: 0.68rem; color: #ec4899;">Amplitude Diária: ${l.daily_range} pts</div>
          </div>
        </div>

        <!-- Barra de Pivot Points -->
        <div style="display: grid; grid-template-columns: repeat(5, 1fr); gap: 0.3rem; font-size: 0.72rem; margin-bottom: 1rem; text-align: center;">
          <div style="background: rgba(239, 68, 68, 0.1); padding: 0.4rem; border-radius: 4px; border: 1px solid rgba(239, 68, 68, 0.2);">
            <span style="color: var(--accent-negative); display: block; font-size: 0.65rem;">R2</span>
            <strong style="color: #fff;">${l.r2}</strong>
          </div>
          <div style="background: rgba(239, 68, 68, 0.05); padding: 0.4rem; border-radius: 4px;">
            <span style="color: var(--accent-negative); display: block; font-size: 0.65rem;">R1</span>
            <strong style="color: #fff;">${l.r1}</strong>
          </div>
          <div style="background: rgba(0, 229, 255, 0.1); padding: 0.4rem; border-radius: 4px; border: 1px solid rgba(0, 229, 255, 0.3);">
            <span style="color: var(--cyan); display: block; font-size: 0.65rem;">PIVOT</span>
            <strong style="color: #fff;">${l.pivot_point}</strong>
          </div>
          <div style="background: rgba(0, 255, 136, 0.05); padding: 0.4rem; border-radius: 4px;">
            <span style="color: var(--accent-positive); display: block; font-size: 0.65rem;">S1</span>
            <strong style="color: #fff;">${l.s1}</strong>
          </div>
          <div style="background: rgba(0, 255, 136, 0.1); padding: 0.4rem; border-radius: 4px; border: 1px solid rgba(0, 255, 136, 0.2);">
            <span style="color: var(--accent-positive); display: block; font-size: 0.65rem;">S2</span>
            <strong style="color: #fff;">${l.s2}</strong>
          </div>
        </div>

        <!-- Setups de Compra e Venda -->
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-bottom: 0.75rem;">
          <div style="background: rgba(0, 255, 136, 0.05); border-left: 3px solid var(--accent-positive); padding: 0.6rem; border-radius: 4px;">
            <div style="font-weight: 700; font-size: 0.75rem; color: var(--accent-positive); margin-bottom: 0.3rem;">🎯 Setup Compra no Suporte</div>
            <div style="font-size: 0.7rem; color: var(--text-secondary); line-height: 1.4;">
              Entrada: <strong>${l.buy_setup.entry_zone}</strong><br>
              Alvo: <strong style="color: var(--accent-positive);">${l.buy_setup.target}</strong> (${l.buy_setup.expected_gain_brl})<br>
              Stop: <strong style="color: var(--accent-negative);">${l.buy_setup.stop}</strong> (${l.buy_setup.risk_brl})
            </div>
            <button class="btn btn-secondary btn-sm" style="margin-top: 0.5rem; font-size: 0.68rem; width: 100%;" onclick='executeStrategyTrade({
              strategy_id: "STRAT-TF-001",
              strategy_name: "Scalp Suporte ${l.ticker}",
              ticker: "${l.ticker}",
              lado: "BUY",
              tipo_ativo: "FUTUROS",
              preco_entrada: ${l.s1},
              alvo: ${l.pivot_point},
              stop: ${l.s2},
              quantidade: 1,
              observacoes: "Scalp Compra no Suporte: Entrada ${l.buy_setup.entry_zone}"
            })'>🚀 Executar Compra</button>
          </div>

          <div style="background: rgba(239, 68, 68, 0.05); border-left: 3px solid var(--accent-negative); padding: 0.6rem; border-radius: 4px;">
            <div style="font-weight: 700; font-size: 0.75rem; color: var(--accent-negative); margin-bottom: 0.3rem;">🎯 Setup Venda na Resistência</div>
            <div style="font-size: 0.7rem; color: var(--text-secondary); line-height: 1.4;">
              Entrada: <strong>${l.sell_setup.entry_zone}</strong><br>
              Alvo: <strong style="color: var(--accent-positive);">${l.sell_setup.target}</strong> (${l.sell_setup.expected_gain_brl})<br>
              Stop: <strong style="color: var(--accent-negative);">${l.sell_setup.stop}</strong> (${l.sell_setup.risk_brl})
            </div>
            <button class="btn btn-secondary btn-sm" style="margin-top: 0.5rem; font-size: 0.68rem; width: 100%;" onclick='executeStrategyTrade({
              strategy_id: "STRAT-TF-001",
              strategy_name: "Scalp Resistência ${l.ticker}",
              ticker: "${l.ticker}",
              lado: "SELL",
              tipo_ativo: "FUTUROS",
              preco_entrada: ${l.r1},
              alvo: ${l.pivot_point},
              stop: ${l.r2},
              quantidade: 1,
              observacoes: "Scalp Venda na Resistência: Entrada ${l.sell_setup.entry_zone}"
            })'>🚀 Executar Venda</button>
          </div>
        </div>

        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.72rem; color: var(--text-muted); border-top: 1px solid rgba(255,255,255,0.06); padding-top: 0.4rem;">
          <span>Setups: ${l.strategies_linked.join(', ')}</span>
          <button class="btn btn-secondary btn-sm" style="font-size: 0.68rem; padding: 2px 6px;" onclick="openTradeInAi('${l.ticker}')">⚡ Tendência IA</button>
        </div>
      </div>
    `).join('');

  } catch (err) {
    console.error('Erro ao carregar níveis de futuros:', err);
    container.innerHTML = '<div style="grid-column: 1 / -1; color: var(--accent-negative); padding: 1rem;">Falha ao calcular níveis de futuros.</div>';
  }
}

function setSimCapital(val) {
  const input = document.getElementById('alloc-capital-input');
  if (input) {
    input.value = val;
    runAllocationSimulation();
  }
}

async function runAllocationSimulation() {
  const input = document.getElementById('alloc-capital-input');
  const container = document.getElementById('portfolio-alloc-results');
  if (!input || !container) return;

  const capital = parseFloat(input.value) || 100000;
  container.innerHTML = '<div style="text-align: center; padding: 2rem; color: var(--text-muted);"><span class="loading-spinner"></span> Simulando carteira híbrida de ' + formatNumberBR(capital, 2) + '...</div>';

  try {
    const res = await fetch('/api/strategies/simulate-allocation', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ capital: capital })
    });
    const d = await res.json();

    const al = d.allocations;
    const inc = d.income_breakdown;

    container.innerHTML = `
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 1.5rem;">
        <div class="glass-card" style="border-left: 4px solid var(--accent-positive);">
          <span style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">Renda Mensal Total Projetada</span>
          <div style="font-size: 1.6rem; font-weight: 800; color: var(--accent-positive);">
            ${formatNumberBR(d.total_monthly_income_brl, 2)}
          </div>
          <div style="font-size: 0.75rem; color: var(--cyan); font-weight: 600;">
            ${formatNumberBR(d.monthly_return_pct, 2)}% ao mês (${formatNumberBR(d.cdi_multiplier_pct, 0)}% do CDI)
          </div>
        </div>

        <div class="glass-card" style="border-left: 4px solid var(--cyan);">
          <span style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">Renda Fixa CDI (60% Garantia)</span>
          <div style="font-size: 1.3rem; font-weight: 700; color: #fff;">
            ${formatNumberBR(inc.rf_yield_monthly, 2)}
          </div>
          <div style="font-size: 0.72rem; color: var(--text-muted);">Capital: ${formatNumberBR(al.fixed_income_guarantee.amount_brl, 2)}</div>
        </div>

        <div class="glass-card" style="border-left: 4px solid #f59e0b;">
          <span style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">Renda Venda de Puts OTM</span>
          <div style="font-size: 1.3rem; font-weight: 700; color: #f59e0b;">
            ${formatNumberBR(inc.put_selling_monthly, 2)}
          </div>
          <div style="font-size: 0.72rem; color: var(--text-muted);">Lastro na Renda Fixa (1,8% a.m.)</div>
        </div>

        <div class="glass-card" style="border-left: 4px solid #3b82f6;">
          <span style="font-size: 0.72rem; color: var(--text-muted); text-transform: uppercase;">Ações Dividendos + Venda Coberta</span>
          <div style="font-size: 1.3rem; font-weight: 700; color: #3b82f6;">
            ${formatNumberBR(inc.stocks_dividends_monthly + inc.covered_call_monthly, 2)}
          </div>
          <div style="font-size: 0.72rem; color: var(--text-muted);">Div: ${formatNumberBR(inc.stocks_dividends_monthly, 2)} + Call: ${formatNumberBR(inc.covered_call_monthly, 2)}</div>
        </div>
      </div>

      <!-- Cesta Recomendada de Ativos -->
      <div class="glass-card">
        <h4 style="font-size: 0.95rem; font-weight: 700; color: #fff; margin-bottom: 0.75rem;">
          🛒 Cesta de Ações Dividendistas Recomendadas (30% do Patrimônio: ${formatNumberBR(al.dividend_stocks.amount_brl, 2)})
        </h4>
        <div style="overflow-x: auto;">
          <table class="data-table" style="width: 100%; font-size: 0.8rem;">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Empresa</th>
                <th>Peso na Carteira</th>
                <th style="text-align: right;">Capital Alocado</th>
                <th style="text-align: right;">Preço Aprox.</th>
                <th style="text-align: right;">Quantidade de Ações</th>
                <th style="text-align: center;">Ações</th>
              </tr>
            </thead>
            <tbody>
              ${(d.recommended_basket || []).map(b => `
                <tr>
                  <td><span class="ticker-badge">${b.ticker}</span></td>
                  <td>${b.name}</td>
                  <td>${formatNumberBR(b.weight_pct, 1)}%</td>
                  <td style="text-align: right; font-weight: 600;">${formatNumberBR(b.amount_brl, 2)}</td>
                  <td style="text-align: right;">${formatNumberBR(b.approx_price, 2)}</td>
                  <td style="text-align: right; font-weight: 700; color: var(--accent-positive);">${parseInt(b.shares_qty).toLocaleString('pt-BR')} ações</td>
                  <td style="text-align: center;">
                    <button class="btn btn-secondary btn-sm" style="font-size: 0.7rem; padding: 2px 7px;" onclick="openTradeInAi('${b.ticker}')">⚡ IA</button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      </div>
    `;

  } catch (err) {
    console.error('Erro na simulação de alocação:', err);
    container.innerHTML = '<div style="color: var(--accent-negative); padding: 1rem;">Falha ao simular alocação de capital.</div>';
  }
}

async function executeStrategyTrade(tradeData) {
  try {
    const res = await fetch('/api/strategies/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(tradeData)
    });
    const result = await res.json();
    if (result.success) {
      showToast(result.message || `Operação ${tradeData.ticker} registrada para acompanhamento!`, 'success');
      if (typeof fetchLocalTrades === 'function') {
        fetchLocalTrades();
      }
    } else {
      showToast(result.error || 'Erro ao registrar operação', 'error');
    }
  } catch (err) {
    console.error('Erro ao executar trade de estratégia:', err);
    showToast('Erro de comunicação com o servidor.', 'error');
  }
}

async function handleYouTubeCrawlSubmit() {
  const input = document.getElementById('yt-crawl-url-input');
  const btn = document.getElementById('btn-yt-crawl-submit');
  const statusDiv = document.getElementById('yt-crawl-status');
  if (!input || !input.value.trim()) {
    showToast('Informe a URL do vídeo do YouTube', 'warning');
    return;
  }

  const url = input.value.trim();
  btn.disabled = true;
  btn.innerHTML = '<span class="loading-spinner"></span> Rastreando...';
  statusDiv.style.display = 'block';
  statusDiv.innerHTML = 'Conectando ao YouTube, capturando transcrição e mapeando estratégias do canal...';

  try {
    const res = await fetch('/api/strategies/youtube/crawl', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: url, limit: 30 })
    });
    const result = await res.json();

    if (result.success) {
      statusDiv.innerHTML = `<span style="color: var(--accent-positive);">✓ Sucesso!</span> Canal <strong>${result.channel_name}</strong> mapeado! Encontrados <strong>${result.candidates_found}</strong> vídeos com estratégias.`;
      showToast(`Vídeo e canal processados com sucesso!`, 'success');
      input.value = '';
      await loadStrategiesCatalog();
    } else {
      statusDiv.innerHTML = `<span style="color: var(--accent-negative);">Erro:</span> ${result.error || 'Falha ao processar vídeo'}`;
      showToast(result.error || 'Erro na extração', 'error');
    }
  } catch (err) {
    statusDiv.innerHTML = `<span style="color: var(--accent-negative);">Erro de conexão com o servidor.</span>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Inspecionar Canal & Extrair Estratégias';
  }
}

async function crawlVideoUrl(url) {
  const input = document.getElementById('yt-crawl-url-input');
  if (input) {
    input.value = url;
    await handleYouTubeCrawlSubmit();
  }
}

async function refreshTfPatterns() {
  const btn = document.getElementById('btn-refresh-tf');
  if (btn) btn.disabled = true;
  showToast('Recalculando métricas e padrões do TradingFloor...', 'info');

  try {
    const res = await fetch('/api/strategies/tf/refresh', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast('Padrões do TradingFloor atualizados com sucesso!', 'success');
      await loadStrategiesCatalog();
    } else {
      showToast(data.error || 'Erro ao atualizar padrões', 'error');
    }
  } catch (err) {
    showToast('Erro de conexão com o servidor', 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function runOptionBacktest(symbol) {
  showToast(`Iniciando simulação histórica para ${symbol}...`, 'info');
  try {
    const res = await fetch('/api/strategies/backtest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ strategy_id: 'STRAT-YT-001', symbol: `${symbol}.SA`, start_date: '2016-01-01' })
    });
    const data = await res.json();
    if (data.error) {
      showToast(data.error, 'error');
    } else {
      alert(`Backtest Concluído para ${symbol}!\n\n` +
            `• Período: ${data.period}\n` +
            `• Taxa de Acerto: ${data.win_rate_pct}% (${data.win_months} vitórias / ${data.loss_months} derrotas)\n` +
            `• Retorno Estratégia: ${data.strategy_multiple}x o capital (${formatNumberBR(data.final_equity, 2)})\n` +
            `• Retorno CDI (100%): ${data.cdi_multiple}x o capital (${formatNumberBR(data.cdi_final_equity, 2)})\n` +
            `• Retorno Buy & Hold: ${data.buy_hold_multiple}x o capital\n` +
            `• Max Drawdown: ${data.max_drawdown_pct}%`);
    }
  } catch (err) {
    showToast('Erro ao rodar backtest', 'error');
  }
}

function filterScreenerForStrategy(stratId) {
  if (stratId === 'STRAT-YT-001') {
    switchStrategySubTab('screener');
  } else {
    switchStrategySubTab('strat-trades');
    setTimeout(() => {
      const sel = document.getElementById('filter-strat-select');
      if (sel) {
        sel.value = stratId;
        filterStrategyTrades();
      }
    }, 100);
  }
}

// ==========================================
// EXPLORADOR HISTÓRICO DE TRADES DO BANCO
// ==========================================

async function loadDatabaseTrades(offset = 0) {
  currentDbOffset = Math.max(0, offset);
  const tbody = document.getElementById('db-trades-table-body');
  const counterEl = document.getElementById('db-trades-counter');
  const pageInfo = document.getElementById('db-pagination-info');
  const prevBtn = document.getElementById('btn-db-prev');
  const nextBtn = document.getElementById('btn-db-next');
  if (!tbody) return;

  const status = document.getElementById('db-filter-status')?.value || 'all';
  const product = document.getElementById('db-filter-product')?.value || 'all';
  const asset = document.getElementById('db-filter-asset')?.value || 'all';
  const trader = document.getElementById('db-filter-trader')?.value || 'all';
  const ticker = document.getElementById('db-filter-ticker')?.value || '';

  tbody.innerHTML = '<tr><td colspan="12" style="text-align: center; padding: 1.5rem; color: var(--text-muted);"><span class="loading-spinner"></span> Consultando banco SQLite...</td></tr>';

  try {
    const params = new URLSearchParams({
      status: status,
      product: product,
      tipo_ativo: asset,
      trader: trader,
      ticker: ticker,
      offset: currentDbOffset,
      limit: dbLimit
    });

    const res = await fetch(`/api/trades/database?${params.toString()}`);
    const data = await res.json();
    totalDbCount = data.total_count || 0;

    if (counterEl) {
      counterEl.textContent = `${totalDbCount.toLocaleString('pt-BR')} operações encontradas`;
    }

    // Popula select de traders caso ainda não tenha sido preenchido
    const traderSelect = document.getElementById('db-filter-trader');
    if (traderSelect && traderSelect.options.length <= 1 && data.filter_options?.traders) {
      data.filter_options.traders.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t;
        opt.textContent = t;
        traderSelect.appendChild(opt);
      });
    }

    if (!data.trades || data.trades.length === 0) {
      tbody.innerHTML = '<tr><td colspan="12" style="text-align: center; padding: 1.5rem; color: var(--text-muted);">Nenhuma operação encontrada com os filtros selecionados.</td></tr>';
      if (pageInfo) pageInfo.textContent = 'Sem registros';
      if (prevBtn) prevBtn.disabled = true;
      if (nextBtn) nextBtn.disabled = true;
      return;
    }

    tbody.innerHTML = data.trades.map(t => {
      const isWin = (t.pnl_realizado || 0) > 0;
      const isLoss = (t.pnl_realizado || 0) < 0;
      const pnlColor = isWin ? 'var(--accent-positive)' : (isLoss ? 'var(--accent-negative)' : 'var(--text-muted)');
      const pnlText = (t.pnl_realizado !== null && t.pnl_realizado !== undefined) ? formatNumberBR(t.pnl_realizado, 2) : '-';
      const pontosText = (t.pnl_pontos !== null && t.pnl_pontos !== undefined) ? `${formatNumberBR(t.pnl_pontos, 1)} pts` : '-';
      const precoEnt = t.preco_entrada ? formatNumberBR(t.preco_entrada, 2) : '-';
      const precoSai = t.preco_saida ? formatNumberBR(t.preco_saida, 2) : '-';
      const isBuy = (t.lado || 'BUY').toUpperCase() === 'BUY';
      const dataStr = typeof formatDateTimeBR === 'function' ? formatDateTimeBR(t.timestamp_entrada) : (t.timestamp_entrada || '').slice(0, 16).replace('T', ' ');


      const tipoAtivo = t.tipo_ativo || (t.produto === 'Opções' || t.produto === 'Desafio Eleições' ? 'OPCOES' : 'Futuros (B3)');
      let tipoBadgeColor = 'var(--accent-cyan)';
      if (tipoAtivo.includes('OPCOES') || tipoAtivo.includes('Opções')) tipoBadgeColor = 'var(--accent-positive)';
      else if (tipoAtivo.includes('Cripto')) tipoBadgeColor = '#f59e0b';
      else if (tipoAtivo.includes('Forex')) tipoBadgeColor = '#3b82f6';
      else if (tipoAtivo.includes('Ações')) tipoBadgeColor = '#10b981';

      return `
        <tr>
          <td><span class="ticker-badge">${t.ticker}</span></td>
          <td><span style="font-size: 0.75rem; color: #fff;">${t.produto || 'Trading Floor'}</span></td>
          <td><span class="tag-pill" style="font-size: 0.68rem; padding: 2px 5px; border: 1px solid ${tipoBadgeColor}; color: ${tipoBadgeColor}; border-radius: 4px;">${tipoAtivo}</span></td>
          <td><strong style="color: var(--emerald);">${t.trader_nome}</strong></td>
          <td><span class="badge ${isBuy ? 'badge-buy' : 'badge-sell'}" style="font-size: 0.65rem;">${isBuy ? 'COMPRA' : 'VENDA'}</span></td>
          <td style="text-align: right; font-family: var(--font-mono);">${parseInt(t.quantidade || 0).toLocaleString('pt-BR')}</td>
          <td style="text-align: right; font-family: var(--font-mono);">${precoEnt}</td>
          <td style="text-align: right; font-family: var(--font-mono);">${precoSai}</td>
          <td style="text-align: right; font-family: var(--font-mono); font-weight: 600; color: ${pnlColor};">${pnlText}</td>
          <td style="text-align: right; font-family: var(--font-mono); font-size: 0.72rem; color: var(--text-muted);">${pontosText}</td>
          <td style="color: var(--text-muted); font-size: 0.72rem;">${dataStr}</td>
          <td><span class="badge ${t.status === 'OPEN' ? 'badge-primary' : 'badge-secondary'}" style="font-size: 0.65rem;">${t.status}</span></td>
        </tr>
      `;
    }).join('');

    // Atualiza info de paginação
    const currentPage = Math.floor(currentDbOffset / dbLimit) + 1;
    const totalPages = Math.ceil(totalDbCount / dbLimit) || 1;
    const startRecord = currentDbOffset + 1;
    const endRecord = Math.min(currentDbOffset + data.trades.length, totalDbCount);
    if (pageInfo) pageInfo.textContent = `Exibindo ${startRecord} a ${endRecord} de ${totalDbCount.toLocaleString('pt-BR')} (Página ${currentPage} de ${totalPages})`;
    if (prevBtn) prevBtn.disabled = currentDbOffset === 0;
    if (nextBtn) nextBtn.disabled = endRecord >= totalDbCount;

  } catch (err) {
    console.error('Erro ao carregar trades do banco:', err);
    tbody.innerHTML = '<tr><td colspan="12" style="text-align: center; color: var(--accent-negative);">Erro ao carregar registros do banco de dados.</td></tr>';
  }
}

function paginateDbTrades(direction) {
  const newOffset = currentDbOffset + (direction * dbLimit);
  if (newOffset >= 0 && newOffset < totalDbCount) {
    loadDatabaseTrades(newOffset);
  }
}
