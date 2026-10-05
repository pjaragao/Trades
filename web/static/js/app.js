/**
 * App Module: Gerenciamento do Dashboard ao vivo, status do robô, configurações e terminal.
 */

let currentTab = 'dashboard';
let isBotRunning = false;
let isDryRun = true;
let pollTimer = null;

document.addEventListener('DOMContentLoaded', () => {
  setupTabs();
  refreshDashboard();
  loadSettings();
  initBacktestFilters();

  // Polling periódico a cada 3 segundos
  pollTimer = setInterval(() => {
    fetchBotStatus();
    if (currentTab === 'dashboard') {
      fetchLocalTrades();
    } else if (currentTab === 'logs') {
      fetchLogs();
    }
  }, 3000);
});

// Navegação entre Abas
function setupTabs() {
  const tabBtns = document.querySelectorAll('.nav-tab-btn');
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const target = btn.getAttribute('data-tab');
      switchTab(target);
    });
  });
}

function switchTab(tabId) {
  currentTab = tabId;

  document.querySelectorAll('.nav-tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-tab') === tabId);
  });

  document.querySelectorAll('.tab-pane').forEach(pane => {
    pane.classList.toggle('active', pane.id === `pane-${tabId}`);
  });

  if (tabId === 'dashboard') {
    refreshDashboard();
  } else if (tabId === 'backtest') {
    // Roda backtest inicial caso os gráficos estejam vazios
    if (!equityChartInstance) {
      runBacktest();
    }
  } else if (tabId === 'ai-forecast') {
    if (typeof activeTradesCache === 'undefined' || activeTradesCache.length === 0) {
      initAiTab();
    }
  } else if (tabId === 'strategies') {
    initStrategiesTab();
  } else if (tabId === 'logs') {
    fetchLogs();
  }
}

// Atualização Geral do Dashboard
async function refreshDashboard() {
  await fetchBotStatus();
  await fetchTradingFloorsTrades();
  await fetchLocalTrades();
}

// Consulta status do robô
async function fetchBotStatus() {
  try {
    const res = await fetch('/api/status');
    if (!res.ok) return;
    const data = await res.json();

    isBotRunning = data.is_running;
    isDryRun = data.dry_run;

    // Atualiza Badge do Header
    const badgeEl = document.getElementById('status-badge');
    const badgeText = document.getElementById('status-text');
    if (badgeEl && badgeText) {
      if (isBotRunning) {
        badgeEl.className = 'status-badge running';
        badgeText.textContent = isDryRun ? 'ROBÔ RODANDO (SIMULADO)' : 'ROBÔ RODANDO (REAL)';
      } else {
        badgeEl.className = 'status-badge stopped';
        badgeText.textContent = 'ROBÔ PARADO';
      }
    }

    // Atualiza Botão Iniciar/Parar
    const btnBot = document.getElementById('btn-toggle-bot');
    if (btnBot) {
      if (isBotRunning) {
        btnBot.className = 'btn btn-danger';
        btnBot.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg> Pausar Robô`;
      } else {
        btnBot.className = 'btn btn-success';
        btnBot.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> Iniciar Robô`;
      }
    }

    // Atualiza Botão Alternar Modo
    const btnMode = document.getElementById('btn-toggle-mode');
    if (btnMode) {
      btnMode.textContent = isDryRun ? 'Alternar p/ Conta Real' : 'Alternar p/ Modo Simulação';
    }

    // Atualiza Cards do Dashboard
    document.getElementById('dash-bot-status').textContent = isBotRunning ? 'RODANDO' : 'PARADO';
    document.getElementById('dash-bot-status').className = `card-value ${isBotRunning ? 'positive' : ''}`;
    document.getElementById('dash-uptime').textContent = `Uptime: ${data.uptime}`;

    const modeVal = document.getElementById('dash-mode-value');
    modeVal.textContent = isDryRun ? 'SIMULAÇÃO' : 'CONTA REAL';
    modeVal.className = `card-value ${isDryRun ? 'cyan' : 'positive'}`;

    document.getElementById('dash-open-count').textContent = data.open_positions_count;

    const mt5Status = document.getElementById('dash-mt5-status');
    if (data.mt5_connected) {
      mt5Status.textContent = 'CONECTADO';
      mt5Status.className = 'card-value positive';
      document.getElementById('dash-mt5-subtext').textContent = 'Pronto para ordens B3';
    } else {
      mt5Status.textContent = isDryRun ? 'SIMULADO' : 'DESCONECTADO';
      mt5Status.className = `card-value ${isDryRun ? 'cyan' : 'negative'}`;
      document.getElementById('dash-mt5-subtext').textContent = isDryRun ? 'Dry-Run interno ativo' : 'Aguardando terminal MT5';
    }

    // Barra de parâmetros
    document.getElementById('bar-capital').textContent = formatNumberBR(data.fixed_capital || 1000, 2);
    document.getElementById('bar-interval').textContent = `${data.poll_interval}s`;
    document.getElementById('bar-products').textContent = (data.allowed_products || []).join(', ') || 'Todos';

  } catch (err) {
    console.error('Erro ao consultar status:', err);
  }
}

// Inicia / Para o Robô
async function toggleBot() {
  const endpoint = isBotRunning ? '/api/bot/stop' : '/api/bot/start';
  try {
    const res = await fetch(endpoint, { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      showToast(isBotRunning ? 'Robô pausado.' : 'Robô iniciado com sucesso!', 'success');
      fetchBotStatus();
    } else {
      showToast(`Erro: ${data.error}`, 'error');
    }
  } catch (err) {
    showToast('Falha na requisição.', 'error');
  }
}

// Alterna entre Simulação e Conta Real
async function toggleMode() {
  const newMode = !isDryRun;
  const confirmMsg = newMode 
    ? 'Deseja voltar para o Modo Simulação (Dry-Run)?' 
    : 'ATENÇÃO: Deseja mudar para CONTA REAL? As ordens serão enviadas para sua corretora via MetaTrader 5.';
  
  if (!confirm(confirmMsg)) return;

  try {
    const res = await fetch('/api/bot/set-mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dry_run: newMode })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Modo alterado para ${newMode ? 'Simulação' : 'Conta Real'}!`, 'success');
      fetchBotStatus();
    } else {
      showToast(`Erro ao alterar modo: ${data.error}`, 'error');
    }
  } catch (err) {
    showToast('Erro de comunicação.', 'error');
  }
}

// Formatação de data/hora no padrão solicitado: DD/MM/AA HH:mm
function formatDateTimeBR(dateStr) {
  if (!dateStr) return '-';
  const str = String(dateStr).trim().replace('T', ' ');
  const parts = str.split(' ');
  const datePart = parts[0]; // "2026-09-14"
  const timePart = parts[1] ? parts[1].slice(0, 5) : ''; // "13:27"

  if (datePart && datePart.includes('-')) {
    const [y, m, d] = datePart.split('-');
    if (y && m && d) {
      const yy = y.length === 4 ? y.slice(-2) : y;
      return timePart ? `${d}/${m}/${yy} ${timePart}` : `${d}/${m}/${yy}`;
    }
  }
  return str.slice(0, 16);
}

let allTradingFloorsTrades = [];

function filterOpenTradesByQuickPill(product, btn) {
  document.querySelectorAll('.tf-filter-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  const productSelect = document.getElementById('tf-filter-product');
  if (productSelect) {
    productSelect.value = product;
  }
  applyAllOpenTradeFilters();
}

function resetOpenTradeFilters() {
  const searchInput = document.getElementById('tf-filter-search');
  const traderSelect = document.getElementById('tf-filter-trader');
  const productSelect = document.getElementById('tf-filter-product');
  const sideSelect = document.getElementById('tf-filter-side');
  const assetSelect = document.getElementById('tf-filter-asset');

  if (searchInput) searchInput.value = '';
  if (traderSelect) traderSelect.value = 'all';
  if (productSelect) productSelect.value = 'all';
  if (sideSelect) sideSelect.value = 'all';
  if (assetSelect) assetSelect.value = 'all';

  document.querySelectorAll('.tf-filter-btn').forEach(b => b.classList.remove('active'));
  const allBtn = document.querySelector('.tf-filter-btn');
  if (allBtn) allBtn.classList.add('active');

  applyAllOpenTradeFilters();
}

function updateTraderSelectOptions(trades) {
  const select = document.getElementById('tf-filter-trader');
  if (!select) return;
  const currentVal = select.value;
  const traders = new Set();
  trades.forEach(t => {
    if (t.trader_nome && t.trader_nome !== 'N/A') {
      traders.add(t.trader_nome.trim());
    }
  });
  const sortedTraders = Array.from(traders).sort();
  let html = '<option value="all">Todos os Traders</option>';
  sortedTraders.forEach(tr => {
    html += `<option value="${tr}">${tr}</option>`;
  });
  select.innerHTML = html;
  if (sortedTraders.includes(currentVal)) {
    select.value = currentVal;
  }
}

function applyAllOpenTradeFilters() {
  const search = (document.getElementById('tf-filter-search')?.value || '').toLowerCase().trim();
  const trader = document.getElementById('tf-filter-trader')?.value || 'all';
  const product = document.getElementById('tf-filter-product')?.value || 'all';
  const side = document.getElementById('tf-filter-side')?.value || 'all';
  const asset = document.getElementById('tf-filter-asset')?.value || 'all';

  let filtered = allTradingFloorsTrades;

  if (search) {
    filtered = filtered.filter(t => {
      const ticker = String(t.ticker || '').toLowerCase();
      const trName = String(t.trader_nome || '').toLowerCase();
      const papel = String(t.papel_principal || t.underlying_ticker || '').toLowerCase();
      return ticker.includes(search) || trName.includes(search) || papel.includes(search);
    });
  }

  if (trader !== 'all') {
    filtered = filtered.filter(t => (t.trader_nome || '').trim().toLowerCase() === trader.toLowerCase());
  }

  if (product !== 'all') {
    filtered = filtered.filter(t => {
      const prod = String(t.produto || '').toLowerCase();
      const prodDisp = String(t.produto_display || '').toLowerCase();
      const pTarget = product.toLowerCase();
      return prod.includes(pTarget) || prodDisp.includes(pTarget) || (t.produtos_all && t.produtos_all.some(p => String(p).toLowerCase().includes(pTarget)));
    });
  }

  if (side !== 'all') {
    filtered = filtered.filter(t => String(t.lado || '').toUpperCase() === side.toUpperCase());
  }

  if (asset !== 'all') {
    filtered = filtered.filter(t => {
      const tipo = String(t.tipo_ativo || '').toUpperCase();
      const target = asset.toUpperCase();
      if (target === 'OPCOES') return tipo.includes('OPCOES') || tipo.includes('OPÇÃO') || tipo.includes('OPÇÕES');
      if (target === 'FUTUROS') return tipo.includes('FUTURO');
      if (target === 'ACOES') return tipo.includes('AÇÃO') || tipo.includes('ACOES') || tipo.includes('AÇÕES');
      if (target === 'CRIPTO') return tipo.includes('CRIPTO');
      return tipo.includes(target);
    });
  }

  renderOpenTradesTable(filtered);
}

// Formatação de números padrão brasileiro: '.' para milhar e ',' para centavos (sem R$)
function formatNumberBR(val, decimals = 2) {
  if (val === null || val === undefined || val === '') return '-';
  const n = typeof val === 'number' ? val : parseFloat(String(val).replace(',', '.'));
  if (isNaN(n)) return '-';
  return n.toLocaleString('pt-BR', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

// Renderiza a tabela de Recomendações com Totais e Notional calculados (sem R$)
function renderOpenTradesTable(trades) {
  const tbody = document.getElementById('tbody-tf-trades');
  const countEl = document.getElementById('tf-trades-count');
  if (!tbody) return;

  if (countEl) {
    countEl.textContent = `${trades.length} de ${allTradingFloorsTrades.length} operações abertas`;
  }

  if (!trades || trades.length === 0) {
    tbody.innerHTML = '<tr><td colspan="12" style="text-align: center; color: var(--text-muted); padding: 1.5rem;">Nenhuma recomendação aberta com os filtros selecionados.</td></tr>';
    return;
  }

  tbody.innerHTML = trades.map(t => {
    const isBuy = (t.lado || 'BUY').toUpperCase() === 'BUY';
    const precoEntNum = parseFloat(t.preco_entrada || 0);
    const qtdNum = parseFloat(t.quantidade || 0);
    const precoEnt = formatNumberBR(precoEntNum, 2);
    const precoAtu = (t.preco_atual !== null && t.preco_atual !== undefined) ? formatNumberBR(t.preco_atual, 2) : '-';
    const qtd = parseInt(qtdNum).toLocaleString('pt-BR');
    
    // Total Entrada: Preço Entrada x Quantidade Sugerida
    const totalEntradaNum = precoEntNum * qtdNum;
    const totalEntradaStr = formatNumberBR(totalEntradaNum, 2);

    // Notional (Valor em caso de exercício):
    let notionalNum = 0;
    let notionalSubtext = '';
    const strikeNum = parseFloat(t.strike || 0);
    if (strikeNum > 0) {
      // Opção: Strike x Quantidade
      notionalNum = strikeNum * qtdNum;
      notionalSubtext = `Strike ${formatNumberBR(strikeNum, 2)}`;
    } else if (t.ticker && t.ticker.toUpperCase().startsWith('WIN')) {
      // Mini Índice B3: 0.20 por ponto
      notionalNum = precoEntNum * 0.20 * qtdNum;
      notionalSubtext = `${formatNumberBR(precoEntNum, 0)} pts × 0,20`;
    } else if (t.ticker && t.ticker.toUpperCase().startsWith('WDO')) {
      // Mini Dólar B3: 10 por ponto
      notionalNum = precoEntNum * 10.0 * qtdNum;
      notionalSubtext = `${formatNumberBR(precoEntNum, 2)} pts × 10`;
    } else {
      // Ações à vista ou papéis gerais
      notionalNum = precoEntNum * qtdNum;
      notionalSubtext = `À vista`;
    }
    const notionalStr = formatNumberBR(notionalNum, 2);

    // Horário formatado no padrão DD/MM/AA HH:mm
    const dataStr = formatDateTimeBR(t.timestamp_entrada);

    const tipoAtivo = t.tipo_ativo || (t.produto === 'Opções' || t.produto === 'Desafio Eleições' ? 'OPCOES' : 'Futuros (B3)');
    let tipoBadgeColor = 'var(--accent-cyan)';
    if (tipoAtivo.includes('OPCOES') || tipoAtivo.includes('Opções')) tipoBadgeColor = 'var(--accent-positive)';
    else if (tipoAtivo.includes('Cripto')) tipoBadgeColor = '#f59e0b';
    else if (tipoAtivo.includes('Forex')) tipoBadgeColor = '#3b82f6';
    else if (tipoAtivo.includes('Ações')) tipoBadgeColor = '#10b981';

    return `
      <tr>
        <td><span style="font-weight: 600; font-size: 0.78rem;">${t.produto_display || t.produto || 'Trading Floor'}</span></td>
        <td><span class="tag-pill" style="font-size: 0.7rem; padding: 2px 6px; border: 1px solid ${tipoBadgeColor}; color: ${tipoBadgeColor}; border-radius: 4px;">${tipoAtivo}</span></td>
        <td style="color: var(--emerald); font-weight: 600;">${t.trader_nome || 'N/A'}</td>
        <td>
          <span class="ticker-badge">${t.ticker}</span>
          ${t.papel_principal && t.papel_principal !== t.ticker ? `<div style="font-size: 0.68rem; color: var(--text-muted);">${t.papel_principal}</div>` : ''}
        </td>
        <td><span class="badge ${isBuy ? 'badge-buy' : 'badge-sell'}">${isBuy ? 'COMPRA' : 'VENDA'}</span></td>
        <td style="text-align: right; font-family: var(--font-mono);">${precoEnt}</td>
        <td style="text-align: right; font-family: var(--font-mono); color: var(--cyan);">${precoAtu}</td>
        <td style="text-align: right; font-family: var(--font-mono);">${qtd}</td>
        <td style="text-align: right; font-family: var(--font-mono); font-weight: 600; color: var(--accent-positive);">
          ${totalEntradaStr}
        </td>
        <td style="text-align: right; font-family: var(--font-mono);">
          <div style="font-weight: 600; color: var(--accent-cyan);">${notionalStr}</div>
          <div style="font-size: 0.65rem; color: var(--text-muted);">${notionalSubtext}</div>
        </td>
        <td style="color: var(--text-muted); font-size: 0.75rem; white-space: nowrap;">${dataStr}</td>
        <td style="text-align: center;">
          <div style="display: flex; gap: 0.35rem; justify-content: center;">
            <button class="btn btn-secondary btn-sm" onclick="executeManualTrade('${t.id}')">
              Executar
            </button>
            <button class="btn btn-secondary btn-sm" style="border-color: var(--cyan); color: var(--cyan);" onclick="openTradeInAi('${t.ticker}')" title="Ver Previsão TimesFM">
              ⚡ IA
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

// Consulta recomendações ativas no TradingFloors
async function fetchTradingFloorsTrades() {
  const tbody = document.getElementById('tbody-tf-trades');
  if (!tbody) return;

  try {
    const res = await fetch('/api/trades/open');
    if (!res.ok) return;
    const trades = await res.json();
    allTradingFloorsTrades = trades || [];
    updateTraderSelectOptions(allTradingFloorsTrades);
    applyAllOpenTradeFilters();
  } catch (err) {
    console.error('Erro ao buscar trades do TradingFloors:', err);
  }
}

function openTradeInAi(ticker) {
  switchTab('ai-forecast');
  initAiTab(ticker);
}

// Consulta posições locais acompanhadas
async function fetchLocalTrades() {
  const tbody = document.getElementById('tbody-local-trades');
  const countEl = document.getElementById('local-trades-count');
  if (!tbody) return;

  try {
    const res = await fetch('/api/trades/tracked');
    if (!res.ok) return;
    const trades = await res.json();

    if (countEl) countEl.textContent = `${trades.length} registradas`;

    if (!trades || trades.length === 0) {
      tbody.innerHTML = '<tr><td colspan="9" style="text-align: center; color: var(--text-muted);">Nenhuma posição sincronizada ativa no momento.</td></tr>';
      return;
    }

    tbody.innerHTML = trades.map(t => {
      const isBuy = (t.lado || 'BUY').toUpperCase() === 'BUY';
      const precoEnt = formatNumberBR(parseFloat(t.preco_entrada_executado || t.preco_entrada_sugerido || 0), 2);
      const precoSai = t.preco_saida ? formatNumberBR(t.preco_saida, 2) : '-';
      const isOpen = t.status === 'OPEN';

      return `
        <tr>
          <td><span class="ticker-badge">${t.ticker}</span></td>
          <td><span class="badge ${isBuy ? 'badge-buy' : 'badge-sell'}">${isBuy ? 'COMPRA' : 'VENDA'}</span></td>
          <td>${t.trader_nome}</td>
          <td style="text-align: right; font-family: var(--font-mono);">${precoEnt}</td>
          <td style="text-align: right; font-family: var(--font-mono);">${parseInt(t.quantidade_executada || 0).toLocaleString('pt-BR')}</td>
          <td style="font-family: var(--font-mono); color: var(--purple);">#${t.mt5_ticket || 'SIM'}</td>
          <td><span class="badge ${isOpen ? 'badge-open' : 'badge-closed'}">${t.status}</span></td>
          <td style="text-align: right; font-family: var(--font-mono);">${precoSai}</td>
          <td>
            ${isOpen ? `
              <button class="btn btn-danger btn-sm" onclick="closeManualPosition('${t.trade_id}')">
                Encerrar
              </button>
            ` : '<span style="color: var(--text-muted); font-size: 0.75rem;">Finalizado</span>'}
          </td>
        </tr>
      `;
    }).join('');

  } catch (err) {
    console.error('Erro ao buscar trades locais:', err);
  }
}


// Disparo Manual de Ordem
async function executeManualTrade(tradeId) {
  if (!confirm('Deseja executar manualmente esta recomendação agora?')) return;
  try {
    const res = await fetch('/api/trades/execute-manual', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trade_id: tradeId })
    });
    const data = await res.json();
    if (data.success) {
      showToast('Ordem enviada com sucesso!', 'success');
      refreshDashboard();
    } else {
      showToast(`Falha: ${data.error}`, 'error');
    }
  } catch (err) {
    showToast('Erro ao disparar ordem.', 'error');
  }
}

// Fechamento Manual de Posição
async function closeManualPosition(tradeId) {
  if (!confirm('Deseja encerrar e zerar esta posição no MT5 agora?')) return;
  try {
    const res = await fetch('/api/trades/close-manual', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trade_id: tradeId })
    });
    const data = await res.json();
    if (data.success) {
      showToast('Posição encerrada com sucesso!', 'success');
      refreshDashboard();
    } else {
      showToast(`Falha ao encerrar: ${data.error}`, 'error');
    }
  } catch (err) {
    showToast('Erro ao encerrar posição.', 'error');
  }
}

// Carregar Configurações
async function loadSettings() {
  try {
    const res = await fetch('/api/config');
    if (!res.ok) return;
    const config = await res.json();

    const risk = config.risk || {};
    const mt5 = config.mt5 || {};
    const exec = config.execution || {};

    document.getElementById('cfg-sizing-mode').value = risk.sizing_mode || 'fixed_capital';
    document.getElementById('cfg-fixed-capital').value = risk.fixed_capital_per_trade || 1000;
    document.getElementById('cfg-fixed-qty').value = risk.fixed_quantity || 100;
    document.getElementById('cfg-max-positions').value = risk.max_open_positions || 10;
    document.getElementById('cfg-max-slippage').value = risk.max_slippage_pct || 5.0;

    document.getElementById('cfg-mt5-path').value = mt5.terminal_path || '';
    document.getElementById('cfg-order-type').value = mt5.order_type || 'limit';
    document.getElementById('cfg-magic-number').value = mt5.magic_number || 998877;
    document.getElementById('cfg-initial-sync').value = exec.initial_sync_mode || 'only_new';

  } catch (err) {
    console.error('Erro ao carregar configurações:', err);
  }
}

// Salvar Configurações
async function saveSettings() {
  const payload = {
    risk: {
      sizing_mode: document.getElementById('cfg-sizing-mode').value,
      fixed_capital_per_trade: parseFloat(document.getElementById('cfg-fixed-capital').value) || 1000,
      fixed_quantity: parseInt(document.getElementById('cfg-fixed-qty').value) || 100,
      max_open_positions: parseInt(document.getElementById('cfg-max-positions').value) || 10,
      max_slippage_pct: parseFloat(document.getElementById('cfg-max-slippage').value) || 5.0
    },
    mt5: {
      terminal_path: document.getElementById('cfg-mt5-path').value.trim(),
      order_type: document.getElementById('cfg-order-type').value,
      magic_number: parseInt(document.getElementById('cfg-magic-number').value) || 998877
    },
    execution: {
      initial_sync_mode: document.getElementById('cfg-initial-sync').value
    }
  };

  try {
    const res = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast('Configurações salvas com sucesso!', 'success');
      fetchBotStatus();
    } else {
      showToast(`Erro ao salvar: ${data.error}`, 'error');
    }
  } catch (err) {
    showToast('Erro de comunicação.', 'error');
  }
}

// Terminal e Logs
async function fetchLogs() {
  const body = document.getElementById('terminal-body');
  if (!body) return;

  try {
    const res = await fetch('/api/logs?limit=80');
    if (!res.ok) return;
    const logs = await res.json();

    if (logs && logs.length > 0) {
      body.innerHTML = logs.map(l => `
        <div class="log-entry">
          <span class="log-time">[${l.timestamp}]</span>
          <span class="log-level ${l.level}">[${l.level}]</span>
          <span class="log-msg">${escapeHtml(l.message)}</span>
        </div>
      `).join('');
      body.scrollTop = body.scrollHeight;
    }
  } catch (err) {
    console.error('Erro ao buscar logs:', err);
  }
}

function clearLogs() {
  const body = document.getElementById('terminal-body');
  if (body) {
    body.innerHTML = '<div class="log-entry"><span class="log-time">[--:--:--]</span><span class="log-level INFO">[INFO]</span><span class="log-msg">Logs limpos pelo usuário.</span></div>';
  }
}

// Toast Notifier
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;

  container.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 3500);
}

function escapeHtml(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' };
  return String(text).replace(/[&<>"']/g, m => map[m]);
}
