"""
Histórico real de um analista do TradingFloors numa classe de ativo: o que a Máquina do Tempo chama de "história"
(o original re-roda o setup nos pregões passados; aqui o "setup" é copiar aquele analista).

O TradingFloors não publica stop nem alvo (stop_loss/take_profit vêm sempre vazios na API), então o plano sugerido
sai de como o próprio analista costuma sair:
  stop     = 75º percentil das perdas dele (3 de 4 perdas fecharam antes disso; exige ≥ 5 perdas)
  alvo     = mediana dos ganhos
  horizonte = mediana de dias carregados
E o t da média (média / erro padrão) diz se o resultado médio se distingue de sorte — mesma régua da auditoria do
robo_lab: t < 2 não é edge comprovado.
"""
import math
import statistics
from typing import Any, Dict, List, Optional, Tuple

from src.core import db
from src.core.b3_tickers import ASSET_CLASS_LABELS
from src.core.market_hours import to_brt
from src.services.performance import _ret_pct, _stats

FIELDS = ("trader", "asset_class", "ticker", "lado", "preco_entrada", "preco_saida", "timestamp_entrada",
          "timestamp_saida", "status")
MIN_PLAN_SAMPLE = 20
MIN_LOSSES = 5          # com menos perdas que isso o percentil das perdas não diz nada


def load_closed(conn=None, use_api: bool = True) -> Tuple[List[Dict[str, Any]], str]:
    """Sinais encerrados do banco do Copiloto; banco vazio (ex.: máquina de desenvolvimento) -> API do TradingFloors."""
    with db.connection(conn) as c:
        rows = [dict(r) for r in c.execute(f"SELECT {', '.join(FIELDS)} FROM signals WHERE status = 'CLOSED'")]
    if rows or not use_api:
        return rows, "banco do Copiloto"
    from src.integrations import tradingfloors as tf

    client = tf.get_client()
    if not client.configured:
        return [], "nenhuma (banco vazio e TradingFloors sem login)"
    trades, opcoes = client.fetch_all()
    sigs = [s for s in tf.merge_rows(trades, opcoes) if s.get("status") == "CLOSED"]
    return [{k: s.get(k) for k in FIELDS} for s in sigs], "API do TradingFloors"


def _quantile(vals: List[float], q: float) -> Optional[float]:
    if not vals:
        return None
    s = sorted(vals)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def _edge_label(n: int, t: Optional[float]) -> str:
    if n < MIN_PLAN_SAMPLE:
        return f"amostra pequena ({n} operações): nada se conclui"
    if t is None or t < 1:
        return "sem edge visível (t < 1)"
    if t < 2:
        return "edge fraco (1 ≤ t < 2): pode ser sorte"
    return "edge estatístico (t ≥ 2)"


def summarize(rows: List[Dict[str, Any]], trader: str, asset_class: Optional[str] = None,
              since: Optional[str] = None) -> Dict[str, Any]:
    sel = [r for r in rows
           if str(r.get("trader") or "").lower() == trader.lower()
           and (asset_class is None or r.get("asset_class") == asset_class)
           and (not since or (r.get("timestamp_entrada") or "") >= since)]
    base = _stats(sel)
    rets = [x for x in (_ret_pct(r) for r in sel) if x is not None]
    wins = [x for x in rets if x > 0]
    losses = [-x for x in rets if x < 0]
    holds = []
    for r in sel:
        e, s = to_brt(r.get("timestamp_entrada")), to_brt(r.get("timestamp_saida"))
        if e and s:
            holds.append(max(0.0, (s - e).total_seconds() / 86400))
    n = len(rets)
    sd = statistics.stdev(rets) if n >= 2 else None
    t = (sum(rets) / n) / (sd / math.sqrt(n)) if sd else None
    ordered = sorted((r for r in sel if _ret_pct(r) is not None), key=lambda r: r.get("timestamp_saida") or "")
    entries = [e for e in (to_brt(r.get("timestamp_entrada")) for r in sel) if e]
    plan = None
    if n >= MIN_PLAN_SAMPLE and wins:
        plan = {
            "stop_pct": round(_quantile(losses, 0.75), 2) if len(losses) >= MIN_LOSSES else None,
            "target_pct": round(statistics.median(wins), 2),
            "horizon_days": max(1, math.ceil(statistics.median(holds))) if holds else None,
            "losses": len(losses),
        }
    return {
        "trader": trader,
        "asset_class": asset_class,
        "asset_label": ASSET_CLASS_LABELS.get(asset_class, asset_class or "todas"),
        **base,
        "median_return_pct": round(statistics.median(rets), 2) if rets else None,
        "median_win_pct": round(statistics.median(wins), 2) if wins else None,
        "median_loss_pct": round(-statistics.median(losses), 2) if losses else None,
        "p75_loss_pct": round(-_quantile(losses, 0.75), 2) if losses else None,
        "worst_pct": round(min(rets), 2) if rets else None,
        "hold_days_p25_p50_p75": [round(_quantile(holds, q), 1) for q in (0.25, 0.5, 0.75)] if holds else None,
        "t_stat": round(t, 2) if t is not None else None,
        "edge": _edge_label(n, t),
        "last10": "".join("G" if _ret_pct(r) > 0 else "P" for r in ordered[-10:]),
        "first_date": min(entries).date().isoformat() if entries else None,
        "plan": plan,
    }


def ranking(rows: List[Dict[str, Any]], asset_class: Optional[str] = None, min_n: int = 10) -> List[Dict[str, Any]]:
    traders = sorted({r["trader"] for r in rows if r.get("trader") and (asset_class is None or r.get("asset_class") == asset_class)})
    out = [summarize(rows, t, asset_class) for t in traders]
    out = [s for s in out if (s["closed"] or 0) >= min_n]
    out.sort(key=lambda s: (s["t_stat"] is None, -(s["t_stat"] or 0)))
    return out


def _n(v: Optional[float], d: int = 1, suffix: str = "") -> str:
    return "—" if v is None else f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".") + suffix


def report(s: Dict[str, Any]) -> str:
    copy = {"yes": "sim (carrega posição)", "partial": "em parte", "no": "não (intraday: cópia manual chega atrasada)",
            "unknown": "indefinido (pouca amostra)"}[s["copyable"]]
    hold = s["hold_days_p25_p50_p75"]
    lines = [
        f"{s['trader']} · {s['asset_label']} — {s['closed']} operações encerradas" + (f" desde {s['first_date']}" if s.get("first_date") else ""),
        f"  acerto {_n(s['win_rate'])}% · retorno médio {_n(s['avg_return_pct'], 2, '%')} · mediano {_n(s['median_return_pct'], 2, '%')} · fator de lucro {_n(s['profit_factor'], 2)}",
        f"  ganho mediano {_n(s['median_win_pct'], 2, '%')} · perda mediana {_n(s['median_loss_pct'], 2, '%')} · 75% das perdas até {_n(s['p75_loss_pct'], 2, '%')} · pior {_n(s['worst_pct'], 2, '%')}",
        f"  dias carregados (p25/p50/p75): {' / '.join(_n(h) for h in hold) if hold else '—'} · mesmo dia {_n(s['same_day_share'])}% · copiável à mão: {copy}",
        f"  últimas 10: {s['last10'] or '—'} (G = ganho, P = perda/zero) · t = {_n(s['t_stat'], 2)} → {s['edge']}",
    ]
    if s["plan"]:
        p = s["plan"]
        stop = _n(p["stop_pct"], 1, "%") if p["stop_pct"] is not None else f"— (só {p['losses']} perda(s): use o ATR)"
        lines.append(f"  Plano a partir do histórico: stop {stop} · alvo {_n(p['target_pct'], 1, '%')} · horizonte {p['horizon_days']} dia(s)")
    else:
        lines.append(f"  Sem plano a partir do histórico (precisa de ≥ {MIN_PLAN_SAMPLE} operações e algum ganho).")
    return "\n".join(lines)


__all__ = ["load_closed", "summarize", "ranking", "report"]
