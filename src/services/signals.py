"""
Armazenamento e consulta de sinais + minhas decisões sobre eles.

`upsert_signals()` recebe a lista já mesclada por `tradingfloors.merge_rows()` e a reconcilia com o
banco, casando ids brutos (id canônico, trades_id, linked_ids) para nunca duplicar um sinal entre
polls — inclusive quando `opcoes_trades` mantém aberta uma opção já encerrada em `trades`.
"""
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from src.core import db
from src.core.config import get_prefs, now_iso
from src.core.market_hours import now_brt, to_brt
from src.integrations.tradingfloors import signal_to_db_row
from src.services.quotes import fallback_reason, live_quote, upsert_tradingfloors_quote

AUTHORITATIVE_FIELDS = [
    "produto", "tipo_ativo", "asset_class", "ticker", "underlying", "expiration", "trader", "lado",
    "quantidade", "preco_entrada", "stop_loss", "take_profit", "preco_saida", "pnl_realizado",
    "pnl_pontos", "timestamp_entrada", "timestamp_saida", "status",
]
KEY_MATCH_WINDOW_DAYS = 3

INSERT_COLUMNS = [
    "id", "source", "trades_id", "linked_ids", "produto", "tipo_ativo", "asset_class", "ticker", "underlying",
    "opcao_tipo", "strike", "expiration", "trader", "lado", "quantidade", "preco_entrada", "stop_loss",
    "take_profit", "preco_atual", "preco_atual_at", "preco_saida", "pnl_realizado", "pnl_pontos",
    "timestamp_entrada", "timestamp_saida", "status", "first_seen_at", "closed_seen_at", "updated_at",
    "is_baseline", "raw_json",
]


# ---------------------------------------------------------------------------
# Reconciliação
# ---------------------------------------------------------------------------

def _gap_days(a: Any, b: Any) -> Optional[float]:
    da, dbt = to_brt(a), to_brt(b)
    if da is None or dbt is None:
        return None
    return abs((da - dbt).total_seconds()) / 86400


def find_existing(conn, sig: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    raw_ids = [i for i in [sig["id"], sig.get("trades_id"), *sig.get("linked_ids", [])] if i]
    marks = ",".join("?" * len(raw_ids))
    row = conn.execute(f"SELECT * FROM signals WHERE id IN ({marks}) OR trades_id IN ({marks})", raw_ids + raw_ids).fetchone()
    if row:
        return dict(row)
    row = conn.execute(
        f"SELECT s.* FROM signals s, json_each(s.linked_ids) j WHERE j.value IN ({marks}) LIMIT 1", raw_ids
    ).fetchone()
    if row:
        return dict(row)

    # Casamento por ticker+analista+lado só quando um dos lados veio apenas de `opcoes_trades`
    # (linhas distintas de `trades` com a mesma chave são operações diferentes, ex.: scalps do dia).
    only_opcoes = sig.get("trades_id") is None
    sql = "SELECT * FROM signals WHERE ticker = ? AND lower(trader) = ? AND lado = ?"
    if not only_opcoes:
        sql += " AND trades_id IS NULL"
    best, best_score = None, None
    for cand in conn.execute(sql, (sig["ticker"], sig["trader"].lower(), sig["lado"])):
        gap = _gap_days(cand["timestamp_entrada"], sig.get("timestamp_entrada"))
        if gap is None or gap > KEY_MATCH_WINDOW_DAYS:
            continue
        score = (0 if cand["status"] == sig["status"] else 1, gap)
        if best_score is None or score < best_score:
            best, best_score = dict(cand), score
    return best


def upsert_signals(conn, merged: Iterable[Dict[str, Any]], baseline: bool = False) -> Dict[str, List[str]]:
    """
    Grava/atualiza sinais. Retorna ids canônicos: new (abertos inéditos), new_closed, closed (transição OPEN→CLOSED),
    updated, e `seen` ({id canônico: status}) para o monitor saber quais abertos não vieram no poll.
    """
    result: Dict[str, Any] = {"new": [], "new_closed": [], "closed": [], "updated": [], "seen": {}}
    now = now_iso()

    for sig in merged:
        row = signal_to_db_row(sig)
        existing = find_existing(conn, sig)

        if existing is not None and existing["id"] in result["seen"] and sig.get("trades_id") is None:
            # Linha extra de `opcoes_trades` para um sinal já processado neste lote: só o preço importa.
            _upsert_quote(conn, existing["ticker"], row.get("preco_atual"), now)
            continue

        if existing is None:
            row.update({
                "first_seen_at": now,
                "closed_seen_at": now if row["status"] == "CLOSED" else None,
                "updated_at": now,
                "preco_atual_at": now if row.get("preco_atual") is not None else None,
                "is_baseline": 1 if baseline else 0,
            })
            conn.execute(
                f"INSERT INTO signals ({','.join(INSERT_COLUMNS)}) VALUES ({','.join('?' * len(INSERT_COLUMNS))})",
                [row.get(c) for c in INSERT_COLUMNS],
            )
            _upsert_quote(conn, row["ticker"], row.get("preco_atual"), now)
            result["new_closed" if row["status"] == "CLOSED" else "new"].append(row["id"])
            result["seen"][row["id"]] = row["status"]
            continue

        updates: Dict[str, Any] = {}
        authoritative = sig.get("trades_id") is not None or existing.get("trades_id") is None
        if authoritative:
            for f in AUTHORITATIVE_FIELDS:
                updates[f] = row.get(f)
            updates["produto"] = _union_produto(existing.get("produto"), row.get("produto"))
            if sig.get("trades_id"):
                updates["trades_id"] = sig["trades_id"]
            updates["raw_json"] = row["raw_json"]
        for f in ("strike", "opcao_tipo"):
            if row.get(f) is not None:
                updates[f] = row[f]
        if row.get("preco_atual") is not None:
            updates["preco_atual"] = row["preco_atual"]
            updates["preco_atual_at"] = now

        linked = set(json.loads(existing.get("linked_ids") or "[]"))
        linked.update(sig.get("linked_ids") or [])
        if sig["id"] != existing["id"]:
            linked.add(sig["id"])
        linked.discard(existing["id"])
        updates["linked_ids"] = json.dumps(sorted(linked))

        new_status = updates.get("status", existing["status"])
        if existing["status"] == "OPEN" and new_status == "CLOSED":
            updates["closed_seen_at"] = now
            result["closed"].append(existing["id"])
        elif existing["status"] == "CLOSED" and new_status == "OPEN":
            updates["closed_seen_at"] = None

        changed = {k: v for k, v in updates.items() if existing.get(k) != v and k != "preco_atual_at"}
        if changed:
            updates["updated_at"] = now
            sets = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE signals SET {sets} WHERE id = ?", [*updates.values(), existing["id"]])
            result["updated"].append(existing["id"])
        elif "preco_atual_at" in updates:
            conn.execute("UPDATE signals SET preco_atual_at = ? WHERE id = ?", (now, existing["id"]))
        _upsert_quote(conn, existing["ticker"], row.get("preco_atual"), now)
        result["seen"][existing["id"]] = new_status

    return result


def _union_produto(old: Optional[str], new: Optional[str]) -> Optional[str]:
    parts: List[str] = []
    for value in (old, new):
        for p in str(value or "").split("/"):
            p = p.strip()
            if p and p not in parts:
                parts.append(p)
    return " / ".join(parts) or None


def mark_closed(conn, signal_id: str, preco_saida: Optional[float] = None, note: Optional[str] = None) -> None:
    now = now_iso()
    conn.execute(
        "UPDATE signals SET status = 'CLOSED', preco_saida = COALESCE(?, preco_saida), "
        "timestamp_saida = COALESCE(timestamp_saida, ?), closed_seen_at = ?, updated_at = ? WHERE id = ? AND status = 'OPEN'",
        (preco_saida, now, now, now, signal_id),
    )


def _upsert_quote(conn, ticker: str, price: Optional[float], now: str) -> None:
    upsert_tradingfloors_quote(conn, ticker, price, now)


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------

def is_followed(sig: Dict[str, Any], prefs: Optional[Dict[str, Any]] = None) -> bool:
    follow = (prefs or get_prefs())["follow"]
    traders = {t.lower() for t in follow.get("traders") or []}
    classes = set(follow.get("asset_classes") or [])
    if traders and str(sig.get("trader", "")).lower() not in traders:
        return False
    if classes and sig.get("asset_class") not in classes:
        return False
    return True


def signal_return_pct(sig: Dict[str, Any], price: Optional[float]) -> Optional[float]:
    entry = sig.get("preco_entrada")
    if price is None or not entry:
        return None
    sign = 1 if sig.get("lado") == "BUY" else -1
    return round(sign * (float(price) / float(entry) - 1) * 100, 2)


def hydrate(row: Dict[str, Any], prefs: Dict[str, Any], decision: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    sig = dict(row)
    sig["linked_ids"] = json.loads(sig.get("linked_ids") or "[]")
    sig.pop("raw_json", None)
    entry_dt = to_brt(sig.get("timestamp_entrada"))
    now = now_brt()
    sig["age_hours"] = round((now - entry_dt).total_seconds() / 3600, 1) if entry_dt else None
    sig["followed"] = is_followed(sig, prefs)
    # cotação ao vivo (MT5/brapi) substitui o preço do TradingFloors, que tem atraso desconhecido
    sig["quote"] = live_quote(sig.get("ticker")) if sig["status"] == "OPEN" else None
    sig["quote_fallback"] = fallback_reason(sig.get("ticker")) if sig["status"] == "OPEN" and not sig["quote"] else None
    if sig["quote"]:
        sig["preco_atual"] = sig["quote"]["price"]
        sig["preco_atual_at"] = sig["quote"]["at"]
    sig["return_now_pct"] = signal_return_pct(sig, sig.get("preco_atual")) if sig["status"] == "OPEN" else None
    sig["return_final_pct"] = signal_return_pct(sig, sig.get("preco_saida")) if sig["status"] == "CLOSED" else None
    if sig.get("expiration"):
        try:
            exp = datetime.fromisoformat(sig["expiration"]).date()
            sig["days_to_expiration"] = (exp - now.date()).days
        except ValueError:
            sig["days_to_expiration"] = None
    sig["decision"] = decision
    return sig


def _decisions_for(conn, ids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not ids:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        for r in conn.execute(f"SELECT * FROM decisions WHERE signal_id IN ({','.join('?' * len(chunk))})", chunk):
            out[r["signal_id"]] = dict(r)
    return out


def get_signal(signal_id: str, conn=None) -> Optional[Dict[str, Any]]:
    prefs = get_prefs(conn)
    with db.connection(conn) as c:
        row = c.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
        if not row:
            return None
        dec = c.execute("SELECT * FROM decisions WHERE signal_id = ?", (signal_id,)).fetchone()
        return hydrate(dict(row), prefs, dict(dec) if dec else None)


def list_signals(
    status: str = "open",
    scope: str = "followed",
    trader: Optional[str] = None,
    asset_class: Optional[str] = None,
    decision: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    conn=None,
) -> Dict[str, Any]:
    prefs = get_prefs(conn)
    where, params = [], []
    if status in ("open", "closed"):
        where.append("s.status = ?")
        params.append(status.upper())
    if trader:
        where.append("lower(s.trader) = ?")
        params.append(trader.lower())
    if asset_class:
        where.append("s.asset_class = ?")
        params.append(asset_class)
    if q:
        where.append("(s.ticker LIKE ? OR s.underlying LIKE ?)")
        params += [f"%{q.upper()}%", f"%{q.upper()}%"]
    if scope == "followed":
        follow = prefs["follow"]
        if follow.get("traders"):
            where.append(f"lower(s.trader) IN ({','.join('?' * len(follow['traders']))})")
            params += [t.lower() for t in follow["traders"]]
        if follow.get("asset_classes"):
            where.append(f"s.asset_class IN ({','.join('?' * len(follow['asset_classes']))})")
            params += follow["asset_classes"]
    if decision == "none":
        where.append("d.signal_id IS NULL")
    elif decision == "returned":
        where.append("s.id IN (SELECT signal_id FROM signal_price_returns)")
    elif decision in ("executed", "ignored", "snoozed"):
        where.append("d.status = ?")
        params.append(decision)

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    base = f"FROM signals s LEFT JOIN decisions d ON d.signal_id = s.id{clause}"
    order = "s.timestamp_entrada DESC" if status != "closed" else "COALESCE(s.timestamp_saida, s.closed_seen_at) DESC"
    with db.connection(conn) as c:
        total = c.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
        rows = [dict(r) for r in c.execute(f"SELECT s.* {base} ORDER BY {order} LIMIT ? OFFSET ?", params + [limit, offset])]
        decisions = _decisions_for(c, [r["id"] for r in rows])
        ret_map = {}
        if rows:
            for r in c.execute(f"SELECT * FROM signal_price_returns WHERE signal_id IN ({','.join('?' * len(rows))}) ORDER BY returned_at DESC", [r["id"] for r in rows]):
                ret_map.setdefault(r["signal_id"], dict(r))
        traders = [r[0] for r in c.execute("SELECT DISTINCT trader FROM signals ORDER BY trader")]
    from src.services.price_returns import fmt_duration
    items = []
    for r in rows:
        h = hydrate(r, prefs, decisions.get(r["id"]))
        if r["id"] in ret_map:
            ret_item = ret_map[r["id"]]
            ret_item["duration_formatted"] = fmt_duration(ret_item.get("duration_seconds", 0))
            h["price_return"] = ret_item
        items.append(h)
    return {"total": total, "limit": limit, "offset": offset, "items": items, "traders": traders}


def open_followed(conn=None) -> List[Dict[str, Any]]:
    return list_signals(status="open", scope="followed", limit=1000, conn=conn)["items"]


# ---------------------------------------------------------------------------
# Decisões
# ---------------------------------------------------------------------------

def set_decision(signal_id: str, status: str, reason: Optional[str] = None, remind_minutes: Optional[int] = None, conn=None) -> Dict[str, Any]:
    if status not in ("executed", "ignored", "snoozed"):
        raise ValueError("status inválido")
    remind_at = None
    if status == "snoozed":
        remind_at = (now_brt() + timedelta(minutes=int(remind_minutes or 60))).isoformat(timespec="seconds")
    with db.transaction(conn) as c:
        if not c.execute("SELECT 1 FROM signals WHERE id = ?", (signal_id,)).fetchone():
            raise KeyError(signal_id)
        c.execute(
            "INSERT INTO decisions(signal_id, status, reason, remind_at, decided_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(signal_id) DO UPDATE SET status = excluded.status, reason = excluded.reason, "
            "remind_at = excluded.remind_at, decided_at = excluded.decided_at",
            (signal_id, status, (reason or "").strip() or None, remind_at, now_iso()),
        )
    return {"signal_id": signal_id, "status": status, "reason": reason, "remind_at": remind_at}


def clear_decision(signal_id: str, conn=None) -> None:
    with db.transaction(conn) as c:
        c.execute("DELETE FROM decisions WHERE signal_id = ?", (signal_id,))
