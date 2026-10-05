// Estado global simples + barramento de eventos
const listeners = new Map();

export const state = {
  status: null,    // /api/status
  prefs: null,     // preferências do usuário
  system: null,    // info de sistema (/api/settings)
};

export function on(evt, fn) {
  if (!listeners.has(evt)) listeners.set(evt, new Set());
  listeners.get(evt).add(fn);
  return () => listeners.get(evt).delete(fn);
}

export function emit(evt, payload) {
  (listeners.get(evt) || []).forEach((fn) => {
    try { fn(payload); } catch (e) { console.error(e); }
  });
}

// Custos estimados no navegador (mesma regra do backend: corretagem + % B3)
export function estimateFees(assetClass, gross) {
  const costs = state.prefs?.costs;
  if (!costs || !gross) return 0;
  const pctMap = costs.b3_fee_pct || {};
  const pct = pctMap[assetClass] ?? pctMap.OUTRO ?? 0;
  return Math.round((Number(costs.brokerage_per_order || 0) + Math.abs(gross) * pct / 100) * 100) / 100;
}
