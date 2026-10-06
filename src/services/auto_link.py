"""
Baixa automática de sinais que eu já executei.

O aviso do analista costuma chegar antes no WhatsApp do que na API do TradingFloors (ex.: entrada às 12:19, linha na
API às 12:20:33) — muitas vezes eu já executei e registrei a ordem quando o sinal aparece aqui. Duas checagens:

1. Sinal novo (monitor): execuções reais do mesmo ativo e lado, ainda sem sinal, executadas ou registradas desde
   `follow.match_minutes` (padrão 30) antes da entrada do analista -> vinculadas ao sinal, que fica "executado".
   Ordens abertas (MT5/simulação) do mesmo ativo e lado também passam a apontar para o sinal.
2. Execução registrada sem sinal (tela ou nota de corretagem): se houver sinal aberto do mesmo ativo e lado, com
   entrada entre `follow.fresh_hours` antes e `match_minutes` depois da execução -> vinculada e "executado".

Só vincula execuções que abrem/aumentam posição no sentido do sinal (uma venda que zera uma compra não é entrada
num sinal de venda).
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.core.config import get_prefs, now_iso
from src.core.market_hours import is_date_only, now_brt, to_brt
from src.services import journal

EPS = 1e-6


def match_minutes(prefs: Dict[str, Any]) -> int:
    return int(prefs["follow"].get("match_minutes", 30))


def signal_anchor(sig: Dict[str, Any]) -> Optional[datetime]:
    """Hora da entrada do analista; se o TradingFloors só informou a data, a hora em que o sinal apareceu aqui."""
    entry = sig.get("timestamp_entrada")
    if entry and not is_date_only(entry):
        return to_brt(entry)
    return to_brt(sig.get("first_seen_at")) or to_brt(entry)


def _opens_position(c, ex: Dict[str, Any]) -> bool:
    """A execução abre/aumenta posição no seu sentido (não é saída de uma posição contrária)?"""
    t = to_brt(ex["executed_at"])
    rows = [dict(r) for r in c.execute("SELECT * FROM executions WHERE ticker = ? AND account = ? AND id != ?",
                                       (ex["ticker"], ex["account"], ex["id"]))]
    before = [r for r in rows if t is None or (to_brt(r["executed_at"]), r["id"]) < (t, ex["id"])]
    pos = sum(p["qty"] for p in journal.compute_ledger(before)["positions"])
    return pos > -EPS if ex["side"] == "BUY" else pos < EPS


def _mark_executed(c, signal_id: str, reason: str) -> None:
    c.execute(
        "INSERT INTO decisions(signal_id, status, reason, decided_at) VALUES(?, 'executed', ?, ?) "
        "ON CONFLICT(signal_id) DO UPDATE SET status = 'executed', reason = COALESCE(decisions.reason, excluded.reason), "
        "remind_at = NULL, decided_at = excluded.decided_at",
        (signal_id, reason, now_iso()),
    )


def link_new_signal(c, sig: Dict[str, Any], prefs: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Sinal acabou de aparecer: houve execução minha nos minutos anteriores? Vincula e dá baixa."""
    prefs = prefs or get_prefs(c)
    anchor = signal_anchor(sig)
    if anchor is None or sig.get("status") != "OPEN" or match_minutes(prefs) <= 0:
        return None
    minutes = timedelta(minutes=match_minutes(prefs))
    start, recent = anchor - minutes, now_brt() - minutes
    rows = [dict(r) for r in c.execute(
        "SELECT * FROM executions WHERE account = 'real' AND signal_id IS NULL AND ticker = ? AND side = ? ORDER BY executed_at, id",
        (sig["ticker"], sig["lado"]))]

    def in_window(r) -> bool:
        t, created = to_brt(r["executed_at"]), to_brt(r["created_at"])
        # executada desde 30 min antes da entrada do analista, ou registrada nos últimos 30 min (mesmo dia da entrada)
        return bool(t and (t >= start or (created and created >= recent and t.date() == anchor.date())))

    matched = [r for r in rows if in_window(r) and _opens_position(c, r)]
    orders = [dict(r) for r in c.execute(
        "SELECT id, created_at FROM orders WHERE signal_id IS NULL AND ticker = ? AND side = ? AND status IN ('sending', 'open', 'partial')",
        (sig["ticker"], sig["lado"]))]
    orders = [o for o in orders if (to_brt(o["created_at"]) or anchor) >= start]
    if not matched and not orders:
        return None
    for r in matched:
        c.execute("UPDATE executions SET signal_id = ? WHERE id = ?", (sig["id"], r["id"]))
    for o in orders:
        c.execute("UPDATE orders SET signal_id = ? WHERE id = ?", (sig["id"], o["id"]))
    if matched:
        _mark_executed(c, sig["id"], "Baixa automática: executado antes de o sinal chegar ao Copiloto")
    qty = sum(r["quantity"] for r in matched)
    avg = sum(r["quantity"] * r["price"] for r in matched) / qty if qty else None
    first = min((to_brt(r["executed_at"]) for r in matched), default=None)
    return {"signal_id": sig["id"], "executions": [r["id"] for r in matched], "orders": [o["id"] for o in orders],
            "quantity": qty, "avg_price": round(avg, 6) if avg else None, "executed_at": first.isoformat() if first else None}


def link_execution(c, exec_id: int, prefs: Optional[Dict[str, Any]] = None, until_end_of_day: bool = False) -> Optional[Dict[str, Any]]:
    """
    Execução registrada sem sinal: há sinal aberto do mesmo ativo/lado (entrada recente) ainda sem baixa? Vincula.
    until_end_of_day: execução de nota de corretagem (sem hora real) — aceita sinal até o fim do pregão.
    """
    prefs = prefs or get_prefs(c)
    if match_minutes(prefs) <= 0:  # baixa automática desligada
        return None
    row = c.execute("SELECT * FROM executions WHERE id = ?", (exec_id,)).fetchone()
    if not row:
        return None
    ex = dict(row)
    if ex["signal_id"] or ex["account"] != "real":
        return None
    t = to_brt(ex["executed_at"])
    if t is None or not _opens_position(c, ex):
        return None
    earliest = t - timedelta(hours=int(prefs["follow"].get("fresh_hours", 72)))
    latest = t.replace(hour=23, minute=59, second=59) if until_end_of_day else t + timedelta(minutes=match_minutes(prefs))
    from src.services.signals import is_followed

    cands = []
    for r in c.execute(
        "SELECT s.*, d.status AS decision_status FROM signals s LEFT JOIN decisions d ON d.signal_id = s.id "
        "WHERE s.status = 'OPEN' AND s.ticker = ? AND s.lado = ?", (ex["ticker"], ex["side"])):
        s = dict(r)
        if s["decision_status"] in ("executed", "ignored"):
            continue
        a = signal_anchor(s)
        if a is None or not (earliest <= a <= latest):
            continue
        cands.append((is_followed(s, prefs), a, s))
    if not cands:
        return None
    cands.sort(key=lambda x: (x[0], x[1]), reverse=True)  # analista seguido primeiro, depois o mais recente
    sig = cands[0][2]
    c.execute("UPDATE executions SET signal_id = ? WHERE id = ?", (sig["id"], exec_id))
    _mark_executed(c, sig["id"], "Baixa automática: execução registrada vinculada ao sinal")
    return {"signal_id": sig["id"], "trader": sig["trader"], "ticker": sig["ticker"], "preco_entrada": sig["preco_entrada"],
            "execution_id": exec_id}


def sweep(c, prefs: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """A cada ciclo do monitor: execuções recentes (até fresh_hours) ainda sem sinal que casam com um sinal aberto."""
    prefs = prefs or get_prefs(c)
    if match_minutes(prefs) <= 0:
        return []
    since = now_brt() - timedelta(hours=int(prefs["follow"].get("fresh_hours", 72)))
    out = []
    for r in c.execute("SELECT id, executed_at FROM executions WHERE account = 'real' AND signal_id IS NULL").fetchall():
        t = to_brt(r["executed_at"])
        if t and t >= since:
            link = link_execution(c, r["id"], prefs)
            if link:
                out.append(link)
    return out


__all__ = ["link_new_signal", "link_execution", "sweep", "signal_anchor", "match_minutes"]
