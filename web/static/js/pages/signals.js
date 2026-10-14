// Tela SINAIS — "O que os analistas estão fazendo?"
import { get, qs } from '../api.js';
import * as f from '../format.js';
import { on, state } from '../state.js';
import { decisionBadge, openSignalModal } from '../components/signal_modal.js';
import { avatar, copyableBadge, debounce, esc, icon, loading } from '../ui.js';

const PAGE = 50;

function retCell(s) {
  const v = s.status === 'CLOSED' ? s.return_final_pct : s.return_now_pct;
  const live = s.status === 'OPEN' ? ` data-lret="${esc(s.ticker)}" data-entry="${s.preco_entrada || ''}" data-side="${esc(s.lado)}"` : '';
  return `<span class="${f.tone(v)}"${live}>${f.pct(v)}</span>`;
}

function priceNow(s) {
  if (s.status === 'CLOSED') return f.brl(s.preco_saida);
  return `<span data-lp="${esc(s.ticker)}">${s.preco_atual === null ? '—' : f.brl(s.preco_atual)}</span>`;
}

function rows(items) {
  return items.map((s) => `
    <tr class="clickable" data-sid="${esc(s.id)}">
      <td class="nowrap">${esc(f.dateTime(s.timestamp_entrada))}<span class="cell-sub">${esc(f.ago(s.timestamp_entrada))}</span></td>
      <td><div class="trader-cell">${avatar(s.trader)}<div>${esc(s.trader)}<span class="cell-sub">${copyableBadge(s.profile)}</span></div></div></td>
      <td class="nowrap"><span class="ticker">${esc(s.ticker)}</span> <span class="badge ${s.lado === 'SELL' ? 'badge-sell' : 'badge-buy'}">${s.lado === 'SELL' ? 'V' : 'C'}</span>
        <span class="cell-sub">${esc(f.ASSET_LABELS[s.asset_class] || '')}${s.underlying && s.underlying !== s.ticker ? ` · ${esc(s.underlying)}` : ''}${s.expiration ? ` · vence ${esc(f.date(s.expiration + 'T12:00:00-03:00'))}` : ''}</span></td>
      <td class="num r">${f.brl(s.preco_entrada)}</td>
      <td class="num r">${priceNow(s)}${s.status === 'CLOSED' ? `<span class="cell-sub">${esc(f.dateTime(s.timestamp_saida))}</span>` : ''}</td>
      <td class="num r">${retCell(s)}</td>
      <td>${s.status === 'OPEN' ? decisionBadge(s.decision) : (s.decision ? decisionBadge(s.decision) : '<span class="badge">Encerrado</span>')}${s.price_return ? ` <span class="badge badge-ok" title="Preço voltou após ${esc(s.price_return.duration_formatted)}">Voltou</span>` : ''}</td>
    </tr>`).join('');
}

function mobileItems(items) {
  return items.map((s) => `
    <div class="sig-item" data-sid="${esc(s.id)}">
      <div><span class="ticker">${esc(s.ticker)}</span> <span class="badge ${s.lado === 'SELL' ? 'badge-sell' : 'badge-buy'}">${s.lado === 'SELL' ? 'V' : 'C'}</span>${s.price_return ? ' <span class="badge badge-ok">Voltou</span>' : ''}</div>
      <div class="num r">${retCell(s)}</div>
      <div class="muted" style="font-size:var(--fs-xs)">${esc(s.trader)} · ${esc(f.ago(s.timestamp_entrada))}</div>
      <div style="text-align:right">${s.status === 'OPEN' ? decisionBadge(s.decision) : '<span class="badge">Encerrado</span>'}</div>
    </div>`).join('');
}

function analystsPanel(profiles, followed, followedClasses) {
  const byTrader = new Map();
  profiles.forEach((p) => {
    if (!byTrader.has(p.trader)) byTrader.set(p.trader, []);
    byTrader.get(p.trader).push(p);
  });
  const list = [...byTrader.entries()]
    // perfil principal: classe que eu sigo com mais operações; senão, a com mais operações
    .map(([t, ps]) => {
      const rank = (p) => (followedClasses.has(p.asset_class) ? 1e6 : 0) + (p.open || 0) * 1000 + (p.closed || 0);
      return { t, main: ps.sort((a, b) => rank(b) - rank(a))[0], follow: followed.has(t.toLowerCase()) };
    })
    .sort((a, b) => (b.follow - a.follow) || ((b.main.closed || 0) - (a.main.closed || 0)));
  return `<div class="card analyst-list">
    <div class="card-head"><h3>${icon('eye')} Analistas</h3><a class="btn btn-sm btn-ghost" href="#/configuracoes">Seguir…</a></div>
    ${list.map(({ t, main, follow }) => `
      <div class="analyst">
        ${avatar(t)}
        <div><div class="row wrap"><strong>${esc(t)}</strong>${follow ? '<span class="badge badge-info badge-plain">seguindo</span>' : ''}</div>
          <div class="analyst-stats"><span>${esc(main.asset_label)}</span><span>acerto <b>${main.win_rate === null ? '—' : f.pct(main.win_rate, { sign: false, dec: 0 })}</b></span><span>médio <b>${f.pct(main.avg_return_pct)}</b></span><span>abertos <b>${main.open}</b></span></div></div>
        ${copyableBadge(main)}
      </div>`).join('')}
    <div class="card-foot hint">Selo "Copiável" = costuma manter a posição por mais de um pregão. Baseado no histórico do TradingFloors.</div>
  </div>`;
}

export default {
  title: 'Sinais',
  async mount(root, params) {
    const filters = {
      status: params.get('status') || 'open',
      scope: params.get('scope') || 'followed',
      trader: params.get('trader') || '',
      asset_class: params.get('asset_class') || '',
      decision: params.get('decision') || '',
      q: '',
      offset: 0,
    };
    root.innerHTML = `
      <div class="page-head"><div><h1>Sinais</h1><p class="sub">Tudo o que os analistas abriram e encerraram, com sua decisão em cada um.</p></div></div>
      <div class="layout-side">
        <div>
          <div class="toolbar">
            <div class="segmented" data-filter="status">
              <button data-v="open">Abertos</button><button data-v="closed">Encerrados</button><button data-v="all">Todos</button>
            </div>
            <div class="segmented" data-filter="scope">
              <button data-v="followed">Que sigo</button><button data-v="all">Todos analistas</button>
            </div>
          </div>
          <div class="toolbar">
            <select class="select" data-filter="trader"><option value="">Todos os analistas</option></select>
            <select class="select" data-filter="asset_class"><option value="">Todas as classes</option>
              ${Object.entries(f.ASSET_LABELS).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select>
            <select class="select" data-filter="decision"><option value="">Qualquer decisão</option><option value="none">Sem decisão</option><option value="returned">Voltou ao preço</option><option value="executed">Executados</option><option value="ignored">Ignorados</option><option value="snoozed">Adiados</option></select>
            <div class="input-group grow"><span class="prefix">${icon('search')}</span><input class="input" data-filter="q" placeholder="Buscar ativo (ex.: BBAS)"></div>
          </div>
          <div class="card" id="sig-list">${loading()}</div>
        </div>
        <aside id="analysts">${loading()}</aside>
      </div>`;

    const listEl = root.querySelector('#sig-list');
    const syncControls = () => {
      root.querySelectorAll('.segmented[data-filter]').forEach((seg) => {
        seg.querySelectorAll('button').forEach((b) => b.classList.toggle('active', b.dataset.v === filters[seg.dataset.filter]));
      });
      root.querySelectorAll('select[data-filter]').forEach((s) => { s.value = filters[s.dataset.filter]; });
    };

    let ctrl;
    const load = async () => {
      ctrl && ctrl.abort();
      ctrl = new AbortController();
      listEl.innerHTML = loading();
      try {
        const data = await get(`/api/signals${qs({ ...filters, limit: PAGE })}`, { signal: ctrl.signal });
        const sel = root.querySelector('select[data-filter=trader]');
        if (sel.options.length <= 1) {
          sel.innerHTML = '<option value="">Todos os analistas</option>' + data.traders.map((t) => `<option>${esc(t)}</option>`).join('');
          sel.value = filters.trader;
        }
        if (!data.items.length) {
          listEl.innerHTML = `<div class="empty"><div class="empty-icon">${icon('inbox', 'icon-lg')}</div><h3>Nenhum sinal com esses filtros</h3>
            <p>${filters.scope === 'followed' ? 'Você está vendo só os analistas que segue. <button class="link-btn" data-scope-all>Ver todos</button>' : ''}</p></div>`;
          return;
        }
        const end = Math.min(filters.offset + PAGE, data.total);
        listEl.innerHTML = `
          <div class="table-wrap sig-table"><table class="table">
            <thead><tr><th>Entrada</th><th>Analista</th><th>Ativo</th><th class="r">Entrada</th><th class="r">${filters.status === 'closed' ? 'Saída' : 'Atual / saída'}</th><th class="r">Retorno</th><th>Decisão</th></tr></thead>
            <tbody>${rows(data.items)}</tbody></table></div>
          <div class="sig-mobile">${mobileItems(data.items)}</div>
          <div class="pager"><span>${filters.offset + 1}–${end} de ${data.total}</span>
            <span class="row"><button class="btn btn-sm" data-page="-1" ${filters.offset ? '' : 'disabled'}>Anterior</button>
            <button class="btn btn-sm" data-page="1" ${end < data.total ? '' : 'disabled'}>Próxima</button></span></div>`;
      } catch (e) {
        if (e.name !== 'AbortError') listEl.innerHTML = `<div class="banner danger">${icon('alert')}<div class="grow">${esc(e.message)}</div></div>`;
      }
    };

    const loadAnalysts = async () => {
      try {
        const profiles = await get('/api/traders');
        const followed = new Set((state.prefs?.follow?.traders || []).map((t) => t.toLowerCase()));
        const classes = new Set(state.prefs?.follow?.asset_classes || []);
        root.querySelector('#analysts').innerHTML = analystsPanel(profiles.filter((p) => p.closed || p.open), followed, classes);
      } catch { root.querySelector('#analysts').innerHTML = ''; }
    };

    root.addEventListener('click', (e) => {
      const seg = e.target.closest('.segmented[data-filter] button');
      if (seg) {
        filters[seg.parentElement.dataset.filter] = seg.dataset.v;
        filters.offset = 0;
        syncControls();
        load();
        return;
      }
      const pg = e.target.closest('[data-page]');
      if (pg) { filters.offset = Math.max(0, filters.offset + Number(pg.dataset.page) * PAGE); load(); return; }
      if (e.target.closest('[data-scope-all]')) { filters.scope = 'all'; syncControls(); load(); return; }
      const row = e.target.closest('[data-sid]');
      if (row) openSignalModal(row.dataset.sid);
    });
    root.addEventListener('change', (e) => {
      const s = e.target.closest('select[data-filter]');
      if (!s) return;
      filters[s.dataset.filter] = s.value;
      filters.offset = 0;
      load();
    });
    const search = debounce((v) => { filters.q = v; filters.offset = 0; load(); }, 300);
    root.querySelector('input[data-filter=q]').addEventListener('input', (e) => search(e.target.value.trim()));

    syncControls();
    await Promise.all([load(), loadAnalysts()]);
    const off = on('data-changed', load);
    return () => off();
  },
};
