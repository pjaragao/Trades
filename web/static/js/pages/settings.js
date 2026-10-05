// Tela CONFIGURAÇÕES
import { get, post, put } from '../api.js';
import * as f from '../format.js';
import { emit, state } from '../state.js';
import { beep, permission, requestPermission } from '../notify.js';
import { confirmDialog, esc, icon, loading, toast, toastError } from '../ui.js';

function execCard(p, sys) {
  const ex = p.execution;
  const a = ex.auto;
  const gate = sys.execution.enabled;
  const num = (k, label, val, hint = '', dec = 0) => `<div class="field"><label>${label}</label><input class="input num" data-k="execution.auto.${k}" value="${dec ? f.num(val, dec) : val}">${hint ? `<span class="hint">${hint}</span>` : ''}</div>`;
  const sw = (k, label, on) => `<label class="switch"><input type="checkbox" data-k="execution.auto.${k}" ${on ? 'checked' : ''}><span class="track"></span>${label}</label>`;
  return `
  <section class="card span-all" id="exec-card">
    <div class="card-head"><h2>${icon('zap')} Execução de ordens (MT5)</h2><span id="exec-health" class="hint"><span class="spinner"></span></span></div>
    <div class="card-body stack">
      <div class="field"><span class="label">Modo</span>
        <div class="segmented" data-seg="execution.mode">
          <button type="button" data-v="off">Desligado (só manual)</button>
          <button type="button" data-v="paper">Simulação</button>
          <button type="button" data-v="live" ${gate ? '' : 'disabled title="Ligue EXECUTION_ENABLED=true (Docker) ou execution.enabled no settings.yaml"'}>Real (MT5)</button>
        </div>
        <span class="hint">${gate ? 'Trava de execução real <strong>liberada</strong> no servidor.' : 'Execução real travada no servidor (EXECUTION_ENABLED / execution.enabled). Use Simulação para testar.'}
          Conector: ${esc(sys.execution.broker === 'mt5_local' ? 'MT5 local (Windows)' : `agente MT5 ${sys.execution.mt5_agent_url || '(MT5_AGENT_URL não definido)'}`)}${sys.execution.broker !== 'mt5_local' ? (sys.execution.agent_token_set ? ' · token definido' : ' · <span class="loss">MT5_AGENT_TOKEN não definido</span>') : ''}.</span></div>
      <div class="field"><span class="label">Tipo de ordem padrão</span>
        <div class="segmented" data-seg="execution.order_type"><button type="button" data-v="limit">Limitada</button><button type="button" data-v="market">A mercado</button></div></div>
      <div class="divider"></div>
      <div class="row-between wrap"><div><h3>Automação</h3><p class="hint">Armada, ela envia sozinha as entradas de sinais novos e as saídas quando o analista encerra — dentro dos limites abaixo.</p></div>
        <label class="switch"><input type="checkbox" data-k="execution.auto.armed" id="armed" ${a.armed ? 'checked' : ''}><span class="track"></span><strong>Armada</strong></label></div>
      <div class="row wrap" style="gap:var(--s5)">${sw('entries', 'Entradas', a.entries)}${sw('exits', 'Saídas', a.exits)}${sw('only_copyable', 'Só analistas copiáveis', a.only_copyable)}</div>
      <div class="form-grid form-grid-3">
        ${num('max_orders_per_day', 'Entradas automáticas por dia', a.max_orders_per_day)}
        ${num('max_daily_loss', 'Perda máxima no dia (R$)', a.max_daily_loss, 'Bloqueia novas entradas', 2)}
        ${num('max_exposure_pct', 'Exposição máxima (% do capital)', a.max_exposure_pct, '', 0)}
        ${num('max_trade_value', 'Valor máximo por ordem (R$)', a.max_trade_value, '', 2)}
        ${num('max_signal_age_minutes', 'Idade máxima do sinal (min)', a.max_signal_age_minutes, 'Não entra em sinal antigo')}
        ${num('cancel_after_minutes', 'Cancelar ordem não executada após (min)', a.cancel_after_minutes)}
      </div>
      <div class="row wrap"><button type="button" class="btn btn-danger" data-act="panic">${icon('alert')} Pânico: desarmar e cancelar ordens abertas</button>
        <a class="btn btn-ghost btn-sm" href="#/carteira">Ver ordens e decisões</a></div>
    </div>
  </section>`;
}

export default {
  title: 'Configurações',
  async mount(root) {
    root.innerHTML = loading();
    let data;
    let traders = [];
    try {
      [data, traders] = await Promise.all([get('/api/settings'), get('/api/traders')]);
    } catch (e) {
      root.innerHTML = `<div class="banner danger">${icon('alert')}<div class="grow">${esc(e.message)}</div></div>`;
      return;
    }
    const p = structuredClone(data.prefs);
    const sys = data.system;

    // agrega estatísticas por analista para os chips de "seguir"
    // perfil principal de cada analista: classe que eu sigo, com mais sinais abertos/encerrados
    const tStats = new Map();
    const followedClasses = new Set(p.follow.asset_classes);
    const rank = (t) => (followedClasses.has(t.asset_class) ? 1e6 : 0) + (t.open || 0) * 1000 + (t.closed || 0);
    traders.forEach((t) => {
      const cur = tStats.get(t.trader) || { closed: 0 };
      cur.closed += t.closed || 0;
      if (!cur.main || rank(t) > rank(cur.main)) cur.main = t;
      tStats.set(t.trader, cur);
    });
    const allTraders = sys.traders.filter((t) => t && t !== 'Desconhecido');
    const followed = new Set(p.follow.traders.map((t) => t.toLowerCase()));
    const classes = new Set(p.follow.asset_classes);

    const notifState = () => {
      const perm = permission();
      if (perm === 'granted') return '<span class="badge badge-ok">Permitidas</span>';
      if (perm === 'denied') return '<span class="badge badge-bad">Bloqueadas no navegador</span>';
      if (perm === 'unsupported') return '<span class="badge">Não suportado</span>';
      return '<button class="btn btn-sm" data-act="perm">Permitir notificações</button>';
    };

    root.innerHTML = `
      <div class="page-head"><div><h1>Configurações</h1><p class="sub">Suas regras de tamanho de posição, quem seguir, custos e alertas.</p></div></div>
      <form id="settings" class="settings-grid" novalidate>
        <section class="card">
          <div class="card-head"><h2>${icon('wallet')} Capital e tamanho da posição</h2></div>
          <div class="card-body form-grid">
            <div class="field"><label for="cap">Capital total do projeto</label>
              <div class="input-group"><span class="prefix">R$</span><input id="cap" class="input num" data-k="capital.total" value="${f.num(p.capital.total)}"></div></div>
            <div class="field"><span class="label">Regra de tamanho</span>
              <div class="segmented" data-seg="sizing.mode">
                <button type="button" data-v="fixed_capital">Valor fixo</button><button type="button" data-v="pct_capital">% do capital</button></div></div>
            <div class="field" data-show="fixed_capital"><label for="vpt">Valor por trade</label>
              <div class="input-group"><span class="prefix">R$</span><input id="vpt" class="input num" data-k="sizing.value_per_trade" value="${f.num(p.sizing.value_per_trade)}"></div></div>
            <div class="field" data-show="pct_capital"><label for="ppt">% do capital por trade</label>
              <input id="ppt" class="input num" data-k="sizing.pct_per_trade" value="${f.num(p.sizing.pct_per_trade, 1)}"></div>
            <div class="field"><label for="slip">Slippage máximo aceitável (%)</label>
              <input id="slip" class="input num" data-k="sizing.max_slippage_pct" value="${f.num(p.sizing.max_slippage_pct, 1)}">
              <span class="hint">Acima disso a boleta trava o preço limite e avisa.</span></div>
            <div class="field"><label for="lot">Lote padrão (opções/ações)</label>
              <input id="lot" class="input num" data-k="sizing.lot_step" value="${p.sizing.lot_step}"></div>
          </div>
        </section>

        <section class="card">
          <div class="card-head"><h2>${icon('eye')} Quem seguir</h2></div>
          <div class="card-body stack">
            <div class="field"><span class="label">Analistas (nenhum marcado = todos)</span>
              <div class="pick-list" id="pick-traders">${allTraders.map((t) => {
                const st = tStats.get(t);
                const cp = st?.main?.copyable;
                const mark = cp === 'yes' ? '●' : cp === 'no' ? '○' : '◐';
                return `<button type="button" class="pick ${followed.has(t.toLowerCase()) ? 'on' : ''}" data-trader="${esc(t)}" title="${st ? `${st.closed} operações · ${esc(st.main.asset_label)}` : ''}">${esc(t)} <span class="pick-meta" title="● copiável · ◐ parcial · ○ intraday">${mark}</span></button>`;
              }).join('')}</div>
              <span class="hint">● copiável manualmente · ◐ parcial · ○ majoritariamente intraday (difícil copiar à mão)</span></div>
            <div class="field"><span class="label">Classes de ativo</span>
              <div class="pick-list" id="pick-classes">${Object.entries(sys.asset_classes).map(([k, v]) => `<button type="button" class="pick ${classes.has(k) ? 'on' : ''}" data-class="${k}">${esc(v)}</button>`).join('')}</div></div>
            <div class="field"><label for="fresh">Sinal conta como "novo" por até (horas)</label>
              <input id="fresh" class="input num" data-k="follow.fresh_hours" value="${p.follow.fresh_hours}" style="max-width:140px">
              <span class="hint">Depois disso, sem decisão, ele vai para a caixa de Sinais em vez da tela Hoje.</span></div>
          </div>
        </section>

        <section class="card">
          <div class="card-head"><h2>${icon('shield')} Custos <span class="badge badge-est">Estimativa</span></h2></div>
          <div class="card-body form-grid">
            <div class="field span-2"><label for="brk">Corretagem por ordem</label>
              <div class="input-group"><span class="prefix">R$</span><input id="brk" class="input num" data-k="costs.brokerage_per_order" value="${f.num(p.costs.brokerage_per_order)}"></div></div>
            ${['OPCAO', 'ACAO'].map((k) => `<div class="field"><label for="fee-${k}">Taxas B3 — ${esc(sys.asset_classes[k])} (%)</label>
              <input id="fee-${k}" class="input num" data-k="costs.b3_fee_pct.${k}" value="${f.num(p.costs.b3_fee_pct[k] ?? 0, 4)}"></div>`).join('')}
            <p class="hint span-2">Usado para pré-preencher custos na boleta e no "Executei". Sempre confira na nota de corretagem.</p>
          </div>
        </section>

        <section class="card">
          <div class="card-head"><h2>${icon('bell')} Alertas</h2></div>
          <div class="card-body stack">
            <div class="row-between"><label class="switch"><input type="checkbox" data-k="alerts.browser" ${p.alerts.browser ? 'checked' : ''}><span class="track"></span>Notificação do navegador</label><span id="perm">${notifState()}</span></div>
            <div class="row-between"><label class="switch"><input type="checkbox" data-k="alerts.sound" ${p.alerts.sound ? 'checked' : ''}><span class="track"></span>Som</label>
              <button type="button" class="btn btn-sm btn-ghost" data-act="beep">${icon('volume')} Testar</button></div>
            <div class="row-between"><label class="switch"><input type="checkbox" data-k="alerts.telegram" ${p.alerts.telegram ? 'checked' : ''}><span class="track"></span>Telegram no celular</label>
              ${sys.telegram_configured ? '<button type="button" class="btn btn-sm btn-ghost" data-act="tg">Enviar teste</button>' : '<span class="badge">não configurado</span>'}</div>
            ${sys.telegram_configured ? '' : `<p class="hint">Para o Telegram: crie um bot com o @BotFather, mande uma mensagem para ele e coloque <code>TELEGRAM_BOT_TOKEN</code> e <code>TELEGRAM_CHAT_ID</code> em <code>config/.env</code>. Reinicie o app.</p>`}
            <p class="hint">Mantenha esta aba aberta (pode ficar em segundo plano) para receber os avisos do navegador.</p>
          </div>
        </section>

        ${execCard(p, sys)}

        <section class="card">
          <div class="card-head"><h2>${icon('copy')} Corretora / boleta</h2></div>
          <div class="card-body form-grid">
            <div class="field"><label for="bname">Corretora</label><input id="bname" class="input" data-k="broker.name" value="${esc(p.broker.name)}" placeholder="Ex.: XP, Clear, BTG…"></div>
            <div class="field"><label for="bval">Validade padrão da ordem</label><input id="bval" class="input" data-k="broker.order_validity" value="${esc(p.broker.order_validity)}"></div>
          </div>
        </section>

        <section class="card">
          <div class="card-head"><h2>${icon('settings')} Sistema</h2></div>
          <div class="card-body">
            <dl class="kv">
              <dt>TradingFloors</dt><dd>${sys.tf_configured ? esc(sys.tf_email) : '<span class="loss">não configurado (config/.env)</span>'}</dd>
              <dt>Monitor de sinais</dt><dd>a cada ${sys.poll_seconds}s no pregão</dd>
              <dt>Trava da execução real</dt><dd>${sys.execution.enabled ? '<span class="warn-text">liberada</span>' : 'travada (EXECUTION_ENABLED)'}</dd>
              <dt>Banco de dados</dt><dd style="word-break:break-all">${esc(sys.db_path)}</dd>
            </dl>
            <div class="row wrap mt-4">
              <button type="button" class="btn btn-sm" data-act="history">${icon('refresh')} Ressincronizar histórico</button>
            </div>
          </div>
        </section>
      </form>
      <div class="save-bar"><button class="btn btn-primary" id="save">${icon('check')} Salvar configurações</button></div>`;

    const form = root.querySelector('#settings');
    const setPath = (obj, path, val) => {
      const keys = path.split('.');
      let o = obj;
      keys.slice(0, -1).forEach((k) => { o[k] = o[k] ?? {}; o = o[k]; });
      o[keys[keys.length - 1]] = val;
    };
    const syncSeg = () => {
      form.querySelectorAll('[data-seg]').forEach((seg) => {
        const v = seg.dataset.seg.split('.').reduce((o, k) => o?.[k], p);
        seg.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.v === v));
      });
      form.querySelectorAll('[data-show]').forEach((el) => { el.hidden = el.dataset.show !== p.sizing.mode; });
    };
    syncSeg();

    get('/api/execution').then((ex) => {
      const h = ex.state.health;
      const el = root.querySelector('#exec-health');
      if (!el) return;
      if (ex.state.mode === 'off') { el.innerHTML = '<span class="badge">desligado</span>'; return; }
      if (!h) { el.textContent = ''; return; }
      el.innerHTML = h.ok
        ? `<span class="badge badge-ok badge-plain">${esc(ex.state.mode === 'paper' ? 'Simulação pronta' : `MT5 conectado · ${h.account?.login ?? ''} ${h.account?.company ?? ''}`)}</span>${ex.state.armed ? ' <span class="badge badge-warn">AUTOMAÇÃO ARMADA</span>' : ''}`
        : `<span class="badge badge-bad badge-plain" title="${esc(h.message)}">${esc(h.message)}</span>`;
    }).catch(() => {});

    form.addEventListener('click', async (e) => {
      const seg = e.target.closest('[data-seg] button');
      if (seg) { setPath(p, seg.parentElement.dataset.seg, seg.dataset.v); syncSeg(); return; }
      const tr = e.target.closest('[data-trader]');
      if (tr) { tr.classList.toggle('on'); return; }
      const cl = e.target.closest('[data-class]');
      if (cl) { cl.classList.toggle('on'); return; }
      const act = e.target.closest('[data-act]');
      if (!act) return;
      if (act.dataset.act === 'beep') beep();
      if (act.dataset.act === 'perm') { await requestPermission(); root.querySelector('#perm').innerHTML = notifState(); }
      if (act.dataset.act === 'tg') {
        try { await post('/api/alerts/test-telegram'); toast('Mensagem de teste enviada ao Telegram', 'success'); } catch (err) { toastError(err); }
      }
      if (act.dataset.act === 'panic') {
        const ok = await confirmDialog({ title: 'Pânico', message: 'Desarmar a automação e cancelar todas as ordens abertas?', confirmText: 'Desarmar e cancelar', danger: true });
        if (!ok) return;
        try {
          const r = await post('/api/execution/panic', {});
          toast(`Automação desarmada. ${r.cancelled} ordem(ns) cancelada(s).`, 'warning');
          form.querySelector('#armed').checked = false;
          p.execution.auto.armed = false;
          emit('data-changed');
        } catch (err) { toastError(err); }
      }
      if (act.dataset.act === 'history') {
        act.disabled = true;
        try {
          const r = await post('/api/sync/history');
          toast(r.ok ? `Histórico sincronizado (${r.result?.signals ?? 0} sinais)` : 'Não foi possível sincronizar agora', r.ok ? 'success' : 'warning');
        } catch (err) { toastError(err); }
        act.disabled = false;
      }
    });

    root.querySelector('#save').addEventListener('click', async () => {
      form.querySelectorAll('[data-k]').forEach((inp) => {
        const k = inp.dataset.k;
        if (inp.type === 'checkbox') return setPath(p, k, inp.checked);
        const isText = k.startsWith('broker.');
        setPath(p, k, isText ? inp.value : f.parseNum(inp.value));
      });
      p.follow.traders = [...form.querySelectorAll('#pick-traders .pick.on')].map((b) => b.dataset.trader);
      p.follow.asset_classes = [...form.querySelectorAll('#pick-classes .pick.on')].map((b) => b.dataset.class);
      if (p.execution.auto.armed && !data.prefs.execution.auto.armed) {
        const live = p.execution.mode === 'live';
        const ok = await confirmDialog({
          title: live ? 'Armar automação REAL' : 'Armar automação (simulação)',
          message: live ? 'A automação vai enviar ordens REAIS ao MetaTrader 5 sem pedir confirmação, dentro dos limites configurados. Continuar?'
            : 'A automação vai enviar ordens na conta simulada sozinha. Continuar?',
          confirmText: live ? 'Sim, armar com dinheiro real' : 'Armar simulação', danger: live,
        });
        if (!ok) return;
      }
      try {
        const r = await put('/api/settings', p);
        state.prefs = r.prefs;
        data.prefs = structuredClone(r.prefs);
        toast('Configurações salvas', 'success');
        emit('data-changed');
      } catch (err) { toastError(err); }
    });
  },
};
