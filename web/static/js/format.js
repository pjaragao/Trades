// Formatação pt-BR de números, moeda, percentuais e datas
const nf = (min, max) => new Intl.NumberFormat('pt-BR', { minimumFractionDigits: min, maximumFractionDigits: max });
const NF = { 0: nf(0, 0), 2: nf(2, 2), 4: nf(2, 4) };

export function brl(v, { sign = false, dec = 2 } = {}) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const f = (dec === 2 ? NF[2] : nf(dec, dec)).format(Math.abs(n));
  const s = n < 0 ? '−' : (sign && n > 0 ? '+' : '');
  return `${s}R$ ${f}`;
}

export function num(v, dec = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  return nf(dec, dec).format(Number(v));
}

// Preço: até 4 casas (opções baratas), sem casas para índices/futuros grandes
export function price(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  if (Math.abs(n) >= 10000) return NF[0].format(n);
  return NF[4].format(n);
}

export function qty(v) {
  if (v === null || v === undefined) return '—';
  const n = Number(v);
  return Number.isInteger(n) ? NF[0].format(n) : nf(0, 4).format(n);
}

export function pct(v, { sign = true, dec = 1 } = {}) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  const n = Number(v);
  const s = n > 0 && sign ? '+' : (n < 0 ? '−' : '');
  return `${s}${nf(dec, dec).format(Math.abs(n))}%`;
}

export const tone = (v) => (v === null || v === undefined ? '' : Number(v) > 0 ? 'gain' : Number(v) < 0 ? 'loss' : 'muted');

function toDate(v) {
  if (!v) return null;
  const d = v instanceof Date ? v : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

const TZ = 'America/Sao_Paulo';
export function isDateOnly(v) {
  const d = toDate(v);
  if (!d) return false;
  const parts = new Intl.DateTimeFormat('pt-BR', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false }).format(d);
  return parts === '00:00';
}

export function date(v, opts = {}) {
  const d = toDate(v);
  if (!d) return '—';
  return new Intl.DateTimeFormat('pt-BR', { timeZone: TZ, day: '2-digit', month: '2-digit', ...(opts.year ? { year: '2-digit' } : {}) }).format(d);
}

export function dateTime(v) {
  const d = toDate(v);
  if (!d) return '—';
  if (isDateOnly(v)) return date(v);
  return new Intl.DateTimeFormat('pt-BR', { timeZone: TZ, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).format(d);
}

export function time(v) {
  const d = toDate(v);
  if (!d) return '—';
  return new Intl.DateTimeFormat('pt-BR', { timeZone: TZ, hour: '2-digit', minute: '2-digit' }).format(d);
}

export function ago(v) {
  const d = toDate(v);
  if (!d) return '—';
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  if (s < 45) return 'agora';
  if (s < 3600) return `há ${Math.round(s / 60)} min`;
  if (isDateOnly(v)) {
    const days = Math.round(s / 86400);
    return days <= 0 ? 'hoje' : days === 1 ? 'ontem' : `há ${days} dias`;
  }
  if (s < 86400) return `há ${Math.round(s / 3600)} h`;
  const days = Math.round(s / 86400);
  return days === 1 ? 'ontem' : `há ${days} dias`;
}

export function secondsAgo(sec) {
  if (sec === null || sec === undefined) return '—';
  if (sec < 60) return `há ${sec}s`;
  if (sec < 3600) return `há ${Math.round(sec / 60)} min`;
  return `há ${Math.round(sec / 3600)} h`;
}

export function longToday() {
  const s = new Intl.DateTimeFormat('pt-BR', { timeZone: TZ, weekday: 'long', day: 'numeric', month: 'long' }).format(new Date());
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Valor para <input type="datetime-local"> no fuso de Brasília
export function localInputValue(d = new Date()) {
  const p = new Intl.DateTimeFormat('sv-SE', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(d);
  return p.replace(' ', 'T');
}

export function parseNum(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).trim().replace(/\s/g, '').replace(/R\$/i, '');
  if (!s) return null;
  // aceita 1.234,56 · 2.600 (milhar pt-BR) · 1234.56
  let normalized = s;
  if (s.includes(',')) normalized = s.replace(/\./g, '').replace(',', '.');
  else if (/^-?\d{1,3}(\.\d{3})+$/.test(s)) normalized = s.replace(/\./g, '');
  const n = Number(normalized);
  return Number.isFinite(n) ? n : null;
}

export const ASSET_LABELS = {
  OPCAO: 'Opções', ACAO: 'Ações/FIIs', FUTURO: 'Futuros', FOREX: 'Forex',
  INDICE: 'Índices/CFDs', COMMODITY: 'Commodities', CRIPTO: 'Cripto', OUTRO: 'Outros',
};
