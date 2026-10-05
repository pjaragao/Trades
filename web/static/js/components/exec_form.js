// Formulário "Executei" / "Registrar saída" / execução manual / edição
import { post, put } from '../api.js';
import * as f from '../format.js';
import { estimateFees } from '../state.js';
import { esc, icon, openModal, toast } from '../ui.js';

const TITLES = {
  entry: 'Registrar entrada executada',
  exit: 'Registrar saída executada',
  manual: 'Registrar operação',
  edit: 'Editar execução',
  add: 'Registrar execução',
};

function defaults({ mode, signal, ticket, position, execution }) {
  const now = f.localInputValue();
  if (mode === 'edit' && execution) {
    return {
      ticker: execution.ticker, side: execution.side, quantity: execution.quantity, price: execution.price,
      fees: execution.fees, executed_at: f.localInputValue(new Date(execution.executed_at)), note: execution.note || '',
      signal_id: execution.signal_id, asset_class: execution.asset_class, feesTouched: true,
    };
  }
  if (mode === 'exit' && position) {
    const ref = signal && signal.preco_saida != null ? signal.preco_saida : position.last_price;
    return {
      ticker: position.ticker, side: position.side === 'LONG' ? 'SELL' : 'BUY', quantity: position.quantity,
      price: ref ?? '', executed_at: now, note: '', signal_id: signal ? signal.id : null, asset_class: position.asset_class,
    };
  }
  if ((mode === 'entry' || mode === 'add') && signal) {
    return {
      ticker: signal.ticker, side: signal.lado, quantity: ticket ? ticket.quantity : '', price: ticket ? ticket.limit_price : (signal.preco_atual ?? signal.preco_entrada),
      executed_at: now, note: '', signal_id: signal.id, asset_class: signal.asset_class,
    };
  }
  if (mode === 'add' && position) {
    return { ticker: position.ticker, side: position.side === 'LONG' ? 'BUY' : 'SELL', quantity: '', price: position.last_price ?? '', executed_at: now, note: '', signal_id: position.signal?.id || null, asset_class: position.asset_class };
  }
  return { ticker: '', side: 'BUY', quantity: '', price: '', executed_at: now, note: '', signal_id: null, asset_class: null };
}

function guessAsset(ticker) {
  const t = String(ticker || '').toUpperCase();
  if (/^[A-Z]{4}[A-X]\d{1,4}/.test(t)) return 'OPCAO';
  if (/^[A-Z]{4}\d{1,2}F?$/.test(t)) return 'ACAO';
  if (/FUT$|^WIN|^WDO|^IND|^DOL/.test(t)) return 'FUTURO';
  return 'OUTRO';
}

export function openExecutionForm(opts) {
  const { mode = 'manual', signal, position, onSaved } = opts;
  const d = defaults(opts);
  let feesTouched = !!d.feesTouched;
  const lockTicker = mode === 'entry' || mode === 'exit' || (mode === 'add');
  const ref = mode === 'exit' ? (signal?.preco_saida ?? null) : (signal?.preco_entrada ?? null);
  const refLabel = mode === 'exit' ? 'saída do analista' : 'entrada do analista';

  const body = `
    <form id="exec-form" class="stack" novalidate>
      ${signal ? `<div class="banner info">${icon('info')}<div class="grow">Vinculado ao sinal de <strong>${esc(signal.trader)}</strong> em ${esc(signal.ticker)}${ref != null ? ` · ${refLabel} ${f.brl(ref)}` : ''}</div></div>` : ''}
      <div class="form-grid">
        <div class="field">
          <label for="ef-ticker">Ativo</label>
          <input id="ef-ticker" name="ticker" class="input num" value="${esc(d.ticker)}" ${lockTicker ? 'readonly' : 'autofocus'} autocomplete="off" style="text-transform:uppercase" required>
        </div>
        <div class="field">
          <span class="label">Lado</span>
          <div class="segmented" role="radiogroup" id="ef-side">
            <button type="button" data-side="BUY" class="${d.side === 'BUY' ? 'active' : ''}">Compra</button>
            <button type="button" data-side="SELL" class="${d.side === 'SELL' ? 'active' : ''}">Venda</button>
          </div>
        </div>
        <div class="field">
          <label for="ef-qty">Quantidade executada</label>
          <input id="ef-qty" name="quantity" class="input num" inputmode="numeric" value="${d.quantity === '' ? '' : f.qty(d.quantity)}" ${lockTicker ? 'autofocus' : ''} required>
        </div>
        <div class="field">
          <label for="ef-price">Preço médio executado (R$)</label>
          <input id="ef-price" name="price" class="input num" inputmode="decimal" value="${d.price === '' || d.price == null ? '' : f.num(d.price, 2)}" required>
        </div>
        <div class="field">
          <label for="ef-when">Data e hora</label>
          <input id="ef-when" name="executed_at" class="input" type="datetime-local" value="${esc(d.executed_at)}" required>
        </div>
        <div class="field">
          <label for="ef-fees">Custos (corretagem + taxas)</label>
          <div class="input-group"><span class="prefix">R$</span>
            <input id="ef-fees" name="fees" class="input num" inputmode="decimal" value="${f.num(d.fees ?? 0, 2)}"></div>
          <span class="hint" id="ef-fees-hint">${feesTouched ? 'Valor informado' : 'Estimado pelas suas taxas — ajuste pela nota de corretagem'}</span>
        </div>
        <div class="field span-2">
          <label for="ef-note">Observação <span class="faint">(opcional)</span></label>
          <input id="ef-note" name="note" class="input" value="${esc(d.note)}" placeholder="Ex.: executei metade, resto amanhã">
        </div>
      </div>
      <div class="copy-box" id="ef-summary"></div>
      <label class="check" id="ef-short-wrap" ${mode === 'manual' ? '' : 'hidden'}><input type="checkbox" id="ef-short"> Permitir venda a descoberto</label>
      <div class="note danger" id="ef-error" hidden></div>
    </form>`;
  const m = openModal({
    title: TITLES[mode] || TITLES.manual,
    body,
    foot: `<button class="btn btn-ghost" data-close>Cancelar</button>
           <button class="btn ${mode === 'exit' ? 'btn-warn' : 'btn-primary'}" id="ef-submit">${icon('check')} Salvar</button>`,
  });
  m.el.querySelector('.modal-foot [data-close]').onclick = m.close;

  const el = (id) => m.el.querySelector(id);
  let side = d.side;

  const recompute = () => {
    const q = f.parseNum(el('#ef-qty').value) || 0;
    const p = f.parseNum(el('#ef-price').value) || 0;
    const ticker = el('#ef-ticker').value.trim().toUpperCase();
    const asset = d.asset_class || guessAsset(ticker);
    const gross = q * p;
    if (!feesTouched) el('#ef-fees').value = f.num(estimateFees(asset, gross), 2);
    const fees = f.parseNum(el('#ef-fees').value) || 0;
    const total = side === 'BUY' ? gross + fees : gross - fees;
    let cmp = '';
    if (ref && p) {
      const diff = (p / ref - 1) * 100;
      const worse = (mode === 'exit') ? (side === 'SELL' ? diff < 0 : diff > 0) : (side === 'BUY' ? diff > 0 : diff < 0);
      cmp = `\nvs. ${refLabel}: ${f.pct(diff)} ${Math.abs(diff) < 0.05 ? '(igual)' : worse ? '(pior que o analista)' : '(melhor que o analista)'}`;
    }
    el('#ef-summary').textContent = `${side === 'BUY' ? 'COMPRA' : 'VENDA'} ${f.qty(q)} ${ticker || '—'} @ ${f.brl(p)}\n${side === 'BUY' ? 'Total pago' : 'Total recebido'}: ${f.brl(total)} (custos ${f.brl(fees)})${cmp}`;
  };

  el('#ef-side').addEventListener('click', (e) => {
    const b = e.target.closest('[data-side]');
    if (!b) return;
    side = b.dataset.side;
    el('#ef-side').querySelectorAll('button').forEach((x) => x.classList.toggle('active', x === b));
    recompute();
  });
  el('#ef-fees').addEventListener('input', () => { feesTouched = true; el('#ef-fees-hint').textContent = 'Valor informado'; recompute(); });
  ['#ef-qty', '#ef-price', '#ef-ticker'].forEach((s) => el(s).addEventListener('input', recompute));
  recompute();

  const submit = async (ev) => {
    ev && ev.preventDefault();
    const btn = el('#ef-submit');
    const err = el('#ef-error');
    err.hidden = true;
    const payload = {
      ticker: el('#ef-ticker').value.trim().toUpperCase(),
      side,
      quantity: f.parseNum(el('#ef-qty').value),
      price: f.parseNum(el('#ef-price').value),
      fees: f.parseNum(el('#ef-fees').value) || 0,
      executed_at: el('#ef-when').value,
      note: el('#ef-note').value,
      signal_id: d.signal_id || null,
      allow_short: el('#ef-short').checked,
    };
    if (d.asset_class) payload.asset_class = d.asset_class;
    if (!payload.ticker || !payload.quantity || payload.price === null) {
      err.textContent = 'Preencha ativo, quantidade e preço.';
      err.hidden = false;
      return;
    }
    btn.disabled = true;
    try {
      if (mode === 'edit') await put(`/api/executions/${opts.execution.id}`, payload);
      else await post('/api/executions', payload);
      m.close();
      toast(mode === 'exit' ? 'Saída registrada. Resultado lançado em Resultados.' : mode === 'entry' ? 'Entrada registrada. Acompanhe na Carteira.' : 'Execução salva.', 'success');
      onSaved && onSaved();
    } catch (e) {
      err.textContent = e.message;
      err.hidden = false;
      if (/descoberto/i.test(e.message)) el('#ef-short-wrap').hidden = false;
    } finally {
      btn.disabled = false;
    }
  };
  el('#ef-submit').addEventListener('click', submit);
  el('#exec-form').addEventListener('submit', submit);
  return m;
}
