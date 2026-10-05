// Cliente HTTP da API do Copiloto
export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function api(path, { method = 'GET', body, signal } = {}) {
  const opts = { method, headers: { Accept: 'application/json' }, signal };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (err) {
    if (err.name === 'AbortError') throw err;
    throw new ApiError('Sem conexão com o servidor local do Copiloto.', 0);
  }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (res.status === 401 && data && data.login) {
    location.href = `/login?next=${encodeURIComponent(location.pathname + location.hash)}`;
    throw new ApiError('Faça login novamente.', 401);
  }
  if (!res.ok) {
    throw new ApiError((data && data.error) || `Erro ${res.status}`, res.status);
  }
  return data;
}

export const get = (p, opts) => api(p, opts);
export const post = (p, body) => api(p, { method: 'POST', body: body ?? {} });
export const put = (p, body) => api(p, { method: 'PUT', body: body ?? {} });
export const del = (p) => api(p, { method: 'DELETE' });

export function qs(params) {
  const s = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') s.set(k, v);
  });
  const str = s.toString();
  return str ? `?${str}` : '';
}
