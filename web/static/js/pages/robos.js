// Tela FÁBRICA DE ROBÔS & REGIMES DE MERCADO (Módulo separado: robo_lab)
import { get, post } from '../api.js';
import * as f from '../format.js';
import { esc, icon, loading, toastError } from '../ui.js';

const TABS = [
  ['matriz', 'Sentimento & Seletor Causal', 'zap'],
  ['arena', 'Ranking & Exaustão de Filtros', 'chart'],
  ['canal', 'Canal YouTube (250 Vídeos)', 'play'],
  ['mt5', 'Exportar Robô MT5 (.mq5)', 'download'],
];

const REGIME_BADGE = {
  ALTA: '<span class="badge badge-ok">ALTA (Bull)</span>',
  LATERAL: '<span class="badge badge-warn">LATERAL (De Lado)</span>',
  BAIXA: '<span class="badge badge-bad">BAIXA (Bear)</span>',
};

export default {
  title: 'Fábrica de Robôs',
  async mount(root, params) {
    let tab = params.get('tab') || 'matriz';
    root.innerHTML = loading('Carregando Fábrica de Robôs & Arena Multi-Timeframe…');
    const data = await get('/api/robos/overview');

    let selectedSym = params.get('sym') || '^BVSP';
    let selectedTf = params.get('tf') || '1d';

    const renderShell = () => {
      root.innerHTML = `
        <div class="page-head">
          <div>
            <h1>Fábrica de Robôs & Regimes (B3 / MT5)</h1>
            <p class="sub">Mineração completa de canais do YouTube, exaustão de filtros/parâmetros e adaptação causal ao sentimento de mercado sem saber o futuro.</p>
          </div>
          <div class="row wrap">
            <select class="select" id="rl-sym" style="max-width:220px">
              ${data.symbols.filter((s) => data.arena_by_symbol[s.symbol] || ['^BVSP', 'VALE3.SA', 'PETR4.SA'].includes(s.symbol)).map((s) => `<option value="${esc(s.symbol)}" ${s.symbol === selectedSym ? 'selected' : ''}>${esc(s.label)}</option>`).join('')}
            </select>
            <select class="select" id="rl-tf" style="max-width:230px">
              ${data.timeframes.map((t) => `<option value="${esc(t.code)}" ${t.code === selectedTf ? 'selected' : ''}>${esc(t.label)}</option>`).join('')}
            </select>
          </div>
        </div>
        <div class="tabs" role="tablist">${TABS.map(([k, l, ic]) => `<button data-tab="${k}" class="${k === tab ? 'active' : ''}">${icon(ic)} ${esc(l)}</button>`).join('')}</div>
        <div id="rl-body"></div>`;

      root.querySelector('#rl-sym').onchange = (e) => {
        selectedSym = e.target.value;
        const availTfs = Object.keys(data.arena_by_symbol?.[selectedSym]?.by_timeframe || {});
        if (availTfs.length && !availTfs.includes(selectedTf)) {
          selectedTf = availTfs.includes('5m') ? '5m' : availTfs[0];
          root.querySelector('#rl-tf').value = selectedTf;
        }
        renderTab();
      };
      root.querySelector('#rl-tf').onchange = (e) => { selectedTf = e.target.value; renderTab(); };
      root.querySelector('.tabs').onclick = (e) => {
        const b = e.target.closest('[data-tab]');
        if (!b) return;
        tab = b.dataset.tab;
        root.querySelectorAll('[data-tab]').forEach((x) => x.classList.toggle('active', x.dataset.tab === tab));
        renderTab();
      };
      renderTab();
    };

    const getTfSlice = () => {
      const symArena = data.arena_by_symbol?.[selectedSym];
      return symArena?.by_timeframe?.[selectedTf] || null;
    };

    const renderTab = async () => {
      const body = root.querySelector('#rl-body');
      const slice = getTfSlice();

      if (tab === 'matriz') {
        if (!slice) {
          body.innerHTML = `<div class="card card-pad"><p class="muted">Sem dados pré-calculados para ${esc(selectedSym)} [${esc(selectedTf)}].</p></div>`;
          return;
        }
        const comp = slice.meta_causal_selector.comparison;
        const cSpec = slice.meta_causal_selector.causal_specialists;
        const eSpec = slice.meta_causal_selector.expost_specialists;
        const sBot = comp.best_single_bot;
        const cSel = comp.causal_adaptive_selector.metrics;
        const oSel = comp.expost_oracle_selector.metrics;

        body.innerHTML = `
          <div class="banner info">${icon('zap')}
            <div class="grow">
              <strong>Como usar a estratégia de Mês de Alta SEM saber que o mês é de alta?</strong><br>
              Em vez de olhar o fechamento do mês (que tem <em>look-ahead bias</em>), o <strong>Seletor Causal</strong> avalia exclusivamente até a barra <code>t-1</code>:
              <strong>Eficiência Direcional de Kaufman (ER10)</strong>, <strong>ADX(14)</strong>, <strong>Alinhamento EMA 20/50/200</strong> e <strong>Volume Relativo</strong>.
              Quando <code>ER10 &lt; 0.22</code> ou <code>ADX &lt; 18</code>, o mercado está <strong>LATERAL</strong> e o seletor liga robôs de oscilação (Cash Bands, Keltner, VWAP Gradiente). Quando rompe em eficiência direcional, liga os robôs de tendência/pullback!
            </div>
          </div>

          <div class="grid grid-4 section">
            <div class="card tile">
              <div class="tile-label">Buy & Hold (${esc(selectedSym)})</div>
              <div class="tile-value ${f.tone(comp.buy_and_hold_return_pct)}">${f.pct(comp.buy_and_hold_return_pct)}</div>
              <div class="tile-sub">${slice.bars_count} barras (${esc(slice.period_start)} → ${esc(slice.period_end)})</div>
            </div>
            <div class="card tile">
              <div class="tile-label">Melhor Robô Fixo (${esc(sBot.bot_id)})</div>
              <div class="tile-value ${f.tone(sBot.metrics.total_return_pct)}">${sBot.metrics.total_points ? `${f.num(sBot.metrics.total_points, 1)} pts` : f.pct(sBot.metrics.total_return_pct)}</div>
              <div class="tile-sub">${esc(sBot.bot_name)} · Acerto ${f.num(sBot.metrics.win_rate_pct, 1)}% · PF ${f.num(sBot.metrics.profit_factor, 2)}</div>
            </div>
            <div class="card tile">
              <div class="tile-label">Meta-Seletor Causal (Sem Futuro)</div>
              <div class="tile-value ${f.tone(cSel.total_return_pct)}">${cSel.total_points ? `${f.num(cSel.total_points, 1)} pts` : f.pct(cSel.total_return_pct)}</div>
              <div class="tile-sub">Acerto ${f.num(cSel.win_rate_pct, 1)}% · PF ${f.num(cSel.profit_factor, 2)} · DD ${f.num(cSel.max_drawdown_pct, 2)}%</div>
            </div>
            <div class="card tile">
              <div class="tile-label">Oráculo Ex-Post (Sabendo o Mês)</div>
              <div class="tile-value ${f.tone(oSel.total_return_pct)}">${f.pct(oSel.total_return_pct)}</div>
              <div class="tile-sub">Teto teórico · Acerto ${f.num(oSel.win_rate_pct, 1)}% · PF ${f.num(oSel.profit_factor, 2)}</div>
            </div>
          </div>

          <div class="card table-wrap section">
            <div class="card-head"><h3>Qual Robô Ligar em Cada Sentimento Causal de Mercado (${esc(selectedSym)} · ${esc(selectedTf)})</h3><span class="hint">100% operável em tempo real no MT5 (zero look-ahead)</span></div>
            <table class="table">
              <thead><tr><th>Estado Causal (t-1)</th><th>Robô Campeão</th><th>Família</th><th>Filtro Otimizado</th><th class="r">Trades</th><th class="r">Acerto</th><th class="r">Profit Factor</th><th class="r">Retorno no Regime</th><th class="r">Max DD</th></tr></thead>
              <tbody>
                ${['ALTA', 'LATERAL', 'BAIXA'].map((reg) => {
                  const sp = cSpec[reg];
                  const m = sp.regime_metrics;
                  return `<tr>
                    <td>${REGIME_BADGE[reg] || reg}</td>
                    <td><strong>${esc(sp.bot_id)}</strong> — ${esc(sp.bot_name)}</td>
                    <td><code>${esc(sp.family)}</code></td>
                    <td><code>${esc(sp.filter_label)}</code></td>
                    <td class="num r">${m.trades}</td>
                    <td class="num r">${f.num(m.win_rate_pct, 1)}%</td>
                    <td class="num r">${f.num(m.profit_factor, 2)}</td>
                    <td class="num r ${f.tone(m.total_return_pct)}"><strong>${f.pct(m.total_return_pct)}</strong></td>
                    <td class="num r">${f.num(m.max_drawdown_pct, 2)}%</td>
                  </tr>`;
                }).join('')}
              </tbody>
            </table>
          </div>

          <div class="grid grid-2 section">
            <div class="card table-wrap">
              <div class="card-head"><h3>Robô de Acordo com o Volume do Dia</h3></div>
              <table class="table table-compact">
                <thead><tr><th>Perfil de Volume</th><th>Robô Campeão</th><th>Filtro</th><th class="r">Acerto</th><th class="r">Retorno</th></tr></thead>
                <tbody>
                  ${Object.entries(slice.champions_by_volume_profile || {}).map(([vp, vc]) => `<tr>
                    <td><strong>${esc(vp)}</strong></td>
                    <td>${esc(vc.bot_id)} · ${esc(vc.bot_name)}</td>
                    <td><code>${esc(vc.filter_label)}</code></td>
                    <td class="num r">${f.num(vc.metrics.win_rate_pct, 1)}%</td>
                    <td class="num r ${f.tone(vc.metrics.total_return_pct)}">${f.pct(vc.metrics.total_return_pct)}</td>
                  </tr>`).join('')}
                </tbody>
              </table>
            </div>
            <div class="card table-wrap">
              <div class="card-head"><h3>Robô de Acordo com a Direção do Pregão</h3></div>
              <table class="table table-compact">
                <thead><tr><th>Perfil Direcional</th><th>Robô Campeão</th><th>Filtro</th><th class="r">Acerto</th><th class="r">Retorno</th></tr></thead>
                <tbody>
                  ${Object.entries(slice.champions_by_day_direction || {}).map(([dd, dc]) => `<tr>
                    <td><strong>${esc(dd)}</strong></td>
                    <td>${esc(dc.bot_id)} · ${esc(dc.bot_name)}</td>
                    <td><code>${esc(dc.filter_label)}</code></td>
                    <td class="num r">${f.num(dc.metrics.win_rate_pct, 1)}%</td>
                    <td class="num r ${f.tone(dc.metrics.total_return_pct)}">${f.pct(dc.metrics.total_return_pct)}</td>
                  </tr>`).join('')}
                </tbody>
              </table>
            </div>
          </div>`;
      } else if (tab === 'arena') {
        if (!slice) {
          body.innerHTML = `<div class="card card-pad"><p class="muted">Sem dados para este ativo/timeframe.</p></div>`;
          return;
        }
        body.innerHTML = `
          <div class="card table-wrap">
            <div class="card-head">
              <h3>Ranking dos 10 Robôs Após Exaustão de Parâmetros e Filtros (${esc(selectedSym)} · ${esc(selectedTf)})</h3>
              <span class="hint">Comparação entre setup original do vídeo (Baseline) vs. versão com filtros e parâmetros otimizados</span>
            </div>
            <table class="table">
              <thead><tr><th>#</th><th>Robô</th><th>Família</th><th class="r">Combinações</th><th class="r">Retorno Original</th><th class="r">Retorno Otimizado</th><th class="r">Acerto</th><th class="r">PF</th><th class="r">Max DD</th><th>Melhor Filtro & Parâmetros</th></tr></thead>
              <tbody>
                ${slice.bots_ranking.map((b, i) => {
                  const s = b.best_overall.summary;
                  const baseRet = b.baseline.summary.total_return_pct;
                  return `<tr>
                    <td class="num">${i + 1}</td>
                    <td><strong>${esc(b.bot_id)}</strong> — ${esc(b.bot_name)}<div class="cell-sub">${esc(b.thesis.slice(0, 95))}…</div></td>
                    <td><code>${esc(b.family)}</code></td>
                    <td class="num r">${b.combinations_tested}</td>
                    <td class="num r ${f.tone(baseRet)}">${f.pct(baseRet)}</td>
                    <td class="num r ${f.tone(s.total_return_pct)}"><strong>${f.pct(s.total_return_pct)}</strong></td>
                    <td class="num r">${f.num(s.win_rate_pct, 1)}%</td>
                    <td class="num r">${f.num(s.profit_factor, 2)}</td>
                    <td class="num r">${f.num(s.max_drawdown_pct, 1)}%</td>
                    <td><code>${esc(b.best_overall.filter_label)}</code><div class="cell-sub mono">${esc(JSON.stringify(b.best_overall.params))}</div></td>
                  </tr>`;
                }).join('')}
              </tbody>
            </table>
          </div>`;
      } else if (tab === 'canal') {
        const cat = data.channel_catalog || {};
        body.innerHTML = `
          <div class="grid grid-4 section">
            <div class="card tile"><div class="tile-label">Canal Minerado</div><div class="tile-value" style="font-size:1.1rem">${esc(cat.channel_name || '@norisknogainoficial')}</div><div class="tile-sub">Geancarlo Sgorla</div></div>
            <div class="card tile"><div class="tile-label">Vídeos Varridos</div><div class="tile-value">${cat.total_videos_scanned || 250}</div><div class="tile-sub">${cat.strategy_videos_identified || 218} vídeos de estratégias/robôs</div></div>
            <div class="card tile"><div class="tile-label">Transcrições Extraídas</div><div class="tile-value">${cat.transcripts_extracted_count || 23}</div><div class="tile-sub">Regras completas mapeadas</div></div>
            <div class="card tile"><div class="tile-label">Robôs Programados</div><div class="tile-value">${(cat.programmed_bots || []).length}</div><div class="tile-sub">Paramétricos + Filtros</div></div>
          </div>
          <div class="card table-wrap section">
            <div class="card-head"><h3>Famílias de Estratégias nos ${cat.total_videos_scanned || 250} Vídeos do Canal</h3></div>
            <table class="table">
              <thead><tr><th>Família Operacional</th><th class="r">Qtd. Vídeos</th><th>Exemplos de Vídeos Encontrados</th></tr></thead>
              <tbody>
                ${(cat.families_breakdown || []).map((fb) => `<tr>
                  <td><strong>${esc(fb.family)}</strong></td>
                  <td class="num r">${fb.videos_count}</td>
                  <td>${(fb.sample_titles || []).slice(0, 3).map((t) => `<span class="badge badge-plain">${esc(t)}</span>`).join(' ')}</td>
                </tr>`).join('')}
              </tbody>
            </table>
          </div>`;
      } else if (tab === 'mt5') {
        body.innerHTML = `
          <div class="card card-pad stack">
            <h3>Gerador de Expert Advisor MQL5 (.mq5) com Detector Causal de Regime</h3>
            <div class="row wrap">
              <select class="select" id="mt5-bot" style="max-width:360px">
                ${data.bots.map((b) => `<option value="${esc(b.bot_id)}">${esc(b.bot_id)} — ${esc(b.name)}</option>`).join('')}
              </select>
              <button class="btn btn-primary" id="mt5-gen">${icon('download')} Gerar Código MQL5</button>
            </div>
            <pre id="mt5-code" class="mono" style="background:#080d1a;padding:16px;border-radius:8px;overflow:auto;max-height:480px;font-size:12px"></pre>
          </div>`;
        const loadCode = async () => {
          const bid = body.querySelector('#mt5-bot').value;
          const r = await get(`/api/robos/export-mql5/${encodeURIComponent(bid)}?symbol=${encodeURIComponent(selectedSym)}&timeframe=${encodeURIComponent(selectedTf)}`);
          body.querySelector('#mt5-code').textContent = r.mql5_code;
        };
        body.querySelector('#mt5-gen').onclick = loadCode;
        await loadCode();
      }
    };

    renderShell();
  },
};
