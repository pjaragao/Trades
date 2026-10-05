// Importação de notas de corretagem (XP, Genial e outras no padrão SINACOR)
import { del, get, post } from '../api.js';
import * as f from '../format.js';
import { emit, state } from '../state.js';
import { confirmDialog, esc, icon, loading, openModal, toast, toastError } from '../ui.js';

const ACTIONS = { update: 'Aplicar custos/preço', create: 'Criar execução', skip: 'Ignorar' };

function groupRow(n, g, ni, gi) {
  const ticker = g.ticker
    ? `<span class="ticker">${esc(g.ticker)}</span>${g.resolved_by === 'nome' ? `<span class="cell-sub">${esc(g.spec)}</span>` : ''}`
    : `<input class="input num" style="height:30px;max-width:120px" data-ticker="${ni}:${gi}" placeholder="Ticker" title="${esc(g.spec)}"><span class="cell-sub">${esc(g.spec)}</span>`;
  return `<tr>
    <td>${ticker}${g.day_trade ? ' <span class="badge badge-plain">DT</span>' : ''}</td>
    <td><span class="badge ${g.side === 'BUY' ? 'badge-buy' : 'badge-sell'}">${g.side === 'BUY' ? 'C' : 'V'}</span></td>
    <td class="num r">${f.qty(g.quantity)}</td>
    <td class="num r">${f.price(g.price)}</td>
    <td class="num r">${f.brl(g.value)}</td>
    <td class="num r">${f.brl(g.fees)}</td>
    <td style="min-width:170px"><select class="select" style="height:30px" data-action="${ni}:${gi}" ${n.already_imported ? 'disabled' : ''}>
      ${Object.entries(ACTIONS).filter(([k]) => k !== 'update' || (g.matches && g.matches.length)).map(([k, l]) => `<option value="${k}" ${g.action === k ? 'selected' : ''}>${l}</option>`).join('')}
    </select><span class="cell-sub">${esc(g.match_note || '')}</span></td>
  </tr>`;
}

function noteCard(n, ni) {
  const fees = n.fees || {};
  return `<div class="card mt-4">
    <div class="card-head"><h3>${esc(n.broker)} · nota ${esc(n.number)} · ${n.trade_date ? esc(f.date(n.trade_date + 'T12:00:00-03:00', { year: true })) : 'sem data'}</h3>
      ${n.already_imported ? '<span class="badge">já importada</span>' : `<span class="hint">${esc(n.file)}</span>`}</div>
    ${n.warnings.length ? `<div class="card-body"><ul class="notes">${n.warnings.map((w) => `<li class="note warning">${icon('alert')}<span>${esc(w)}</span></li>`).join('')}</ul></div>` : ''}
    <div class="table-wrap"><table class="table"><thead><tr><th>Ativo</th><th>Lado</th><th class="r">Qtd</th><th class="r">Preço médio</th><th class="r">Valor</th><th class="r">Custos rateados</th><th>O que fazer</th></tr></thead>
      <tbody>${n.groups.map((g, gi) => groupRow(n, g, ni, gi)).join('')}</tbody></table></div>
    <div class="card-foot"><dl class="kv">
      <dt>Taxas B3 (liquidação + registro + emolumentos…)</dt><dd>${f.brl(n.b3_fees)}</dd>
      <dt>Corretagem + ISS + outros</dt><dd>${f.brl(n.broker_fees)}</dd>
      <dt>Custos totais</dt><dd>${f.brl(n.total_costs)} (${n.gross_value ? f.pct(n.total_costs / n.gross_value * 100, { sign: false, dec: 3 }) : '—'} do volume)</dd>
      <dt>IRRF ("dedo-duro")</dt><dd>${f.brl(n.irrf)}</dd>
      <dt>Líquido${n.settlement_date ? ` para ${esc(n.settlement_date)}` : ''}</dt><dd>${f.brl(n.net_value)}</dd>
    </dl></div>
  </div>`;
}

export async function openNotesImport() {
  const m = openModal({ title: 'Importar notas de corretagem', wide: true, body: loading() });
  let existing = { notes: [], calibration: null };
  try { existing = await get('/api/notes'); } catch { /* segue */ }
  const cal = existing.calibration;
  m.setBody(`
    <p class="muted">Envie os PDFs das notas (XP, Genial ou outra corretora no padrão SINACOR). O Copiloto lê os negócios e os custos,
      aplica os <strong>custos reais</strong> às suas execuções (rateados pelo valor), cria as que faltam e recalcula as taxas estimadas.</p>
    <div class="form-grid mt-4">
      <div class="field"><label for="nf">Arquivos PDF</label><input id="nf" class="input" type="file" accept="application/pdf" multiple style="padding-top:7px"></div>
      <div class="field"><label for="np">Senha do PDF <span class="faint">(se houver)</span></label><input id="np" class="input" type="password" autocomplete="off" placeholder="XP: 3 primeiros dígitos do CPF">
        <span class="hint">Usada só para abrir o arquivo; não é guardada.</span></div>
    </div>
    <div class="row mt-3"><button class="btn btn-primary" id="nread">${icon('download')} Ler notas</button><span id="nstatus" class="muted"></span></div>
    <div id="npreview"></div>
    ${existing.notes.length ? `<div class="section mt-5"><div class="section-title"><h3>Notas já importadas</h3>
      ${cal && Object.keys(cal.classes || {}).length ? `<span class="hint">Taxas calibradas: ${Object.entries(cal.classes).map(([k, v]) => `${esc(f.ASSET_LABELS[k] || k)} ${f.num(v.pct, 4)}%`).join(' · ')}${cal.brokerage_per_order != null ? ` · corretagem/ordem ${f.brl(cal.brokerage_per_order)}` : ''}</span>` : ''}</div>
      <div class="card table-wrap"><table class="table"><thead><tr><th>Pregão</th><th>Corretora</th><th>Nota</th><th class="r">Volume</th><th class="r">Custos</th><th class="r">IRRF</th><th class="r">Execuções</th><th></th></tr></thead><tbody>
      ${existing.notes.map((n) => `<tr><td>${esc(f.date(n.trade_date + 'T12:00:00-03:00', { year: true }))}</td><td>${esc(n.broker)}</td><td>${esc(n.number)}</td>
        <td class="num r">${f.brl(n.gross_value)}</td><td class="num r">${f.brl(n.total_costs)}</td><td class="num r">${f.brl(n.irrf)}</td><td class="num r">${n.executions}</td>
        <td class="r"><button class="btn btn-sm btn-ghost btn-icon" data-del-note="${n.id}" title="Desfazer importação">${icon('trash')}</button></td></tr>`).join('')}
      </tbody></table></div></div>` : ''}`);

  let preview = null;
  const el = (s) => m.el.querySelector(s);

  el('#nread').onclick = async () => {
    const files = el('#nf').files;
    if (!files.length) { toast('Escolha ao menos um PDF.', 'warning'); return; }
    const fd = new FormData();
    [...files].forEach((file) => fd.append('files', file));
    if (el('#np').value) fd.append('password', el('#np').value);
    el('#nstatus').innerHTML = '<span class="spinner"></span> lendo…';
    try {
      const res = await fetch('/api/notes/parse', { method: 'POST', body: fd });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || `Erro ${res.status}`);
      preview = data;
      el('#nstatus').textContent = `${data.notes.length} nota(s) lida(s)${data.errors.length ? ` · ${data.errors.length} arquivo(s) com problema` : ''}`;
      el('#npreview').innerHTML = `
        ${data.errors.map((e) => `<div class="note danger mt-3">${icon('alert')}<span>${esc(e.file)}: ${esc(e.error)}</span></div>`).join('')}
        ${data.notes.map(noteCard).join('')}
        ${data.notes.length ? `<div class="row-between wrap mt-4">
          <label class="check"><input type="checkbox" id="ncal" checked> Atualizar minhas taxas estimadas (B3 e corretagem) com base nas notas</label>
          <button class="btn btn-primary" id="napply">${icon('check')} Importar</button></div>` : ''}`;
      const apply = el('#napply');
      if (apply) apply.onclick = doApply;
    } catch (err) {
      el('#nstatus').textContent = '';
      toastError(err);
    }
  };

  async function doApply() {
    m.el.querySelectorAll('[data-action]').forEach((s) => {
      const [ni, gi] = s.dataset.action.split(':').map(Number);
      preview.notes[ni].groups[gi].action = s.value;
    });
    m.el.querySelectorAll('[data-ticker]').forEach((inp) => {
      const [ni, gi] = inp.dataset.ticker.split(':').map(Number);
      const t = inp.value.trim().toUpperCase();
      if (t) preview.notes[ni].groups[gi].ticker = t;
    });
    const btn = el('#napply');
    btn.disabled = true;
    try {
      const r = await post('/api/notes/apply', { preview, update_estimates: el('#ncal').checked });
      m.close();
      toast(`${r.notes} nota(s) importada(s): ${r.updated} execução(ões) com custo real, ${r.created} criada(s)${r.errors.length ? `, ${r.errors.length} com erro` : ''}.`, r.errors.length ? 'warning' : 'success', 8000);
      if (r.errors.length) r.errors.forEach((e) => toast(e, 'error', 10000));
      if (r.calibration && r.calibration.applied) {
        const s = await get('/api/settings');
        state.prefs = s.prefs;
      }
      emit('data-changed');
    } catch (err) {
      btn.disabled = false;
      toastError(err);
    }
  }

  m.el.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-del-note]');
    if (!b) return;
    const ok = await confirmDialog({ title: 'Desfazer importação', message: 'Apagar as execuções criadas por esta nota e desvincular as demais (os custos já aplicados permanecem)?', confirmText: 'Desfazer', danger: true });
    if (!ok) return;
    try { await del(`/api/notes/${b.dataset.delNote}`); m.close(); toast('Importação desfeita', 'info'); emit('data-changed'); } catch (err) { toastError(err); }
  });
}
