"""
Diário de execuções (o que eu fiz no Home Broker) e o motor de posições/P&L.

Regras (iguais às da apuração de IR na B3):
- Preço médio de aquisição inclui custos (corretagem + taxas); na venda os custos reduzem o valor líquido.
- Por ativo e por dia, compras e vendas no mesmo dia formam DAY TRADE pela menor quantidade
  (preço médio de compra do dia x preço médio de venda do dia). O excedente vai para a posição SWING.
- Posições e P&L são sempre derivados das execuções — nada de status duplicado.
"""
from collections import defaultdict
from typing import Any, Dict, List, Optional

from src.core import b3_tickers, db
from src.core.config import get_prefs, now_iso
from src.core.market_hours import to_brt

EPS = 1e-9


# ---------------------------------------------------------------------------
# Custos
# ---------------------------------------------------------------------------

def estimate_fees(asset_class: str, gross_value: float, prefs: Optional[Dict[str, Any]] = None) -> float:
    costs = (prefs or get_prefs())["costs"]
    pct = costs["b3_fee_pct"].get(asset_class, costs["b3_fee_pct"].get("OUTRO", 0.0))
    return round(float(costs.get("brokerage_per_order", 0.0)) + abs(gross_value) * pct / 100.0, 2)


# ---------------------------------------------------------------------------
# Motor de posições
# ---------------------------------------------------------------------------

class _TickerBook:
    def __init__(self, ticker: str, asset_class: str):
        self.ticker = ticker
        self.asset_class = asset_class
        self.qty = 0.0          # >0 comprado, <0 vendido
        self.avg = 0.0          # custo unitário (comprado) ou receita líquida unitária (vendido)
        self.cycle: Optional[Dict[str, Any]] = None
        self.cycles: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []

    # ciclo = da posição zerada até zerar de novo (uma "operação" no diário)
    def _ensure_cycle(self, when: str, direction: str) -> Dict[str, Any]:
        if self.cycle is None:
            self.cycle = {
                "id": f"{self.ticker}#{len(self.cycles) + 1}",
                "ticker": self.ticker,
                "asset_class": self.asset_class,
                "direction": direction,
                "opened_at": when,
                "closed_at": None,
                "status": "OPEN",
                "buy_qty": 0.0, "buy_value": 0.0,
                "sell_qty": 0.0, "sell_value": 0.0,
                "fees": 0.0,
                "realized_pnl": 0.0,
                "day_trade_pnl": 0.0,
                "signal_ids": [],
                "execution_ids": [],
            }
            self.cycles.append(self.cycle)
        return self.cycle

    def _event(self, day: str, kind: str, qty: float, cost: float, proceeds: float, sale_gross: float) -> None:
        pnl = proceeds - cost
        cyc = self.cycle
        self.events.append({
            "date": day, "ticker": self.ticker, "asset_class": self.asset_class, "kind": kind,
            "qty": round(qty, 6), "cost": round(cost, 2), "proceeds": round(proceeds, 2),
            "sale_gross": round(sale_gross, 2), "pnl": round(pnl, 2),
            "cycle_id": cyc["id"] if cyc else None,
            "signal_ids": list(cyc["signal_ids"]) if cyc else [],
        })
        if cyc:
            cyc["realized_pnl"] += pnl
            if kind == "day":
                cyc["day_trade_pnl"] += pnl

    def _buy(self, day: str, q: float, unit: float) -> None:
        if self.qty < -EPS:
            cover = min(q, -self.qty)
            self._event(day, "swing", cover, cover * unit, cover * self.avg, cover * self.avg)
            self.qty += cover
            q -= cover
            if abs(self.qty) < EPS:
                self.qty, self.avg = 0.0, 0.0
        if q > EPS:
            self.avg = (self.qty * self.avg + q * unit) / (self.qty + q)
            self.qty += q

    def _sell(self, day: str, q: float, unit: float, gross_unit: float) -> None:
        if self.qty > EPS:
            out = min(q, self.qty)
            self._event(day, "swing", out, out * self.avg, out * unit, out * gross_unit)
            self.qty -= out
            q -= out
            if abs(self.qty) < EPS:
                self.qty, self.avg = 0.0, 0.0
        if q > EPS:
            short = -self.qty
            self.avg = (short * self.avg + q * unit) / (short + q)
            self.qty -= q

    def process_day(self, day: str, execs: List[Dict[str, Any]]) -> None:
        buys = [e for e in execs if e["side"] == "BUY"]
        sells = [e for e in execs if e["side"] == "SELL"]
        qb = sum(e["quantity"] for e in buys)
        qs = sum(e["quantity"] for e in sells)

        first_side = execs[0]["side"]
        cyc = self._ensure_cycle(execs[0]["executed_at"], "LONG" if (self.qty > EPS or (abs(self.qty) < EPS and first_side == "BUY")) else "SHORT")
        for e in execs:
            if e.get("signal_id") and e["signal_id"] not in cyc["signal_ids"]:
                cyc["signal_ids"].append(e["signal_id"])
            cyc["execution_ids"].append(e["id"])
            cyc["fees"] += e["fees"]
            if e["side"] == "BUY":
                cyc["buy_qty"] += e["quantity"]
                cyc["buy_value"] += e["quantity"] * e["price"]
            else:
                cyc["sell_qty"] += e["quantity"]
                cyc["sell_value"] += e["quantity"] * e["price"]

        buy_unit = (sum(e["quantity"] * e["price"] for e in buys) + sum(e["fees"] for e in buys)) / qb if qb else 0.0
        sell_unit = (sum(e["quantity"] * e["price"] for e in sells) - sum(e["fees"] for e in sells)) / qs if qs else 0.0
        sell_gross_unit = sum(e["quantity"] * e["price"] for e in sells) / qs if qs else 0.0

        dt = min(qb, qs)
        if dt > EPS:
            self._event(day, "day", dt, dt * buy_unit, dt * sell_unit, dt * sell_gross_unit)
        if qb - dt > EPS:
            self._buy(day, qb - dt, buy_unit)
        if qs - dt > EPS:
            self._sell(day, qs - dt, sell_unit, sell_gross_unit)

        if abs(self.qty) < EPS:
            cyc["status"] = "CLOSED"
            cyc["closed_at"] = execs[-1]["executed_at"]
            self.cycle = None


def _exec_day(e: Dict[str, Any]) -> str:
    dt = to_brt(e["executed_at"])
    return dt.date().isoformat() if dt else str(e["executed_at"])[:10]


def compute_ledger(executions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Processa execuções e devolve posições abertas, ciclos (operações) e eventos realizados."""
    by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in executions:
        by_ticker[e["ticker"]].append({
            **e,
            "quantity": float(e["quantity"]),
            "price": float(e["price"]),
            "fees": float(e.get("fees") or 0.0),
        })

    books: List[_TickerBook] = []
    for ticker, rows in by_ticker.items():
        rows.sort(key=lambda r: (to_brt(r["executed_at"]) or r["executed_at"], r.get("id") or 0))
        book = _TickerBook(ticker, rows[0].get("asset_class") or b3_tickers.asset_class(None, ticker))
        days: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in rows:
            days[_exec_day(r)].append(r)
        for day in sorted(days):
            book.process_day(day, days[day])
        books.append(book)

    positions, cycles, events = [], [], []
    for b in books:
        for c in b.cycles:
            cycles.append(_finish_cycle(c))
        events.extend(b.events)
        if abs(b.qty) > EPS:
            positions.append({
                "ticker": b.ticker,
                "asset_class": b.asset_class,
                "qty": round(b.qty, 6),
                "side": "LONG" if b.qty > 0 else "SHORT",
                "avg_price": round(b.avg, 6),
                "invested": round(abs(b.qty) * b.avg, 2),
                "cycle_id": b.cycle["id"] if b.cycle else None,
                "opened_at": b.cycle["opened_at"] if b.cycle else None,
                "signal_ids": list(b.cycle["signal_ids"]) if b.cycle else [],
                "realized_in_cycle": round(b.cycle["realized_pnl"], 2) if b.cycle else 0.0,
            })
    events.sort(key=lambda ev: ev["date"])
    cycles.sort(key=lambda c: c["opened_at"])
    return {"positions": positions, "cycles": cycles, "events": events}


def _finish_cycle(c: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(c)
    out["avg_buy"] = round(c["buy_value"] / c["buy_qty"], 6) if c["buy_qty"] else None
    out["avg_sell"] = round(c["sell_value"] / c["sell_qty"], 6) if c["sell_qty"] else None
    base = c["buy_value"] if c["direction"] == "LONG" else c["sell_value"]
    out["realized_pnl"] = round(c["realized_pnl"], 2)
    out["day_trade_pnl"] = round(c["day_trade_pnl"], 2)
    out["fees"] = round(c["fees"], 2)
    out["return_pct"] = round(c["realized_pnl"] / base * 100, 2) if base and c["status"] == "CLOSED" else None
    out["buy_value"] = round(c["buy_value"], 2)
    out["sell_value"] = round(c["sell_value"], 2)
    return out


# ---------------------------------------------------------------------------
# CRUD de execuções
# ---------------------------------------------------------------------------

def list_executions(ticker: Optional[str] = None, signal_id: Optional[str] = None, conn=None) -> List[Dict[str, Any]]:
    sql, params = "SELECT * FROM executions", []
    where = []
    if ticker:
        where.append("ticker = ?")
        params.append(b3_tickers.clean_ticker(ticker))
    if signal_id:
        where.append("signal_id = ?")
        params.append(signal_id)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY executed_at, id"
    with db.connection(conn) as c:
        return [dict(r) for r in c.execute(sql, params)]


def _clean_execution(data: Dict[str, Any]) -> Dict[str, Any]:
    ticker = b3_tickers.clean_ticker(data.get("ticker"))
    side = str(data.get("side") or "").upper()
    if side in ("COMPRA", "C"):
        side = "BUY"
    if side in ("VENDA", "V"):
        side = "SELL"
    if not ticker:
        raise ValueError("Informe o ativo.")
    if side not in ("BUY", "SELL"):
        raise ValueError("Lado deve ser compra ou venda.")
    try:
        qty = float(data.get("quantity"))
        price = float(data.get("price"))
        fees = float(data.get("fees") or 0)
    except (TypeError, ValueError):
        raise ValueError("Quantidade, preço e custos precisam ser números.")
    if qty <= 0:
        raise ValueError("Quantidade deve ser maior que zero.")
    if price < 0 or fees < 0:
        raise ValueError("Preço e custos não podem ser negativos.")
    executed_at = _parse_local(data.get("executed_at"))
    if executed_at is None:
        raise ValueError("Data/hora da execução inválida.")
    asset = data.get("asset_class") or b3_tickers.asset_class(None, ticker)
    return {
        "signal_id": data.get("signal_id") or None,
        "ticker": ticker,
        "side": side,
        "quantity": qty,
        "price": price,
        "fees": round(fees, 2),
        "executed_at": executed_at.isoformat(timespec="seconds"),
        "asset_class": asset,
        "note": (str(data.get("note") or "").strip() or None),
    }


def _parse_local(value: Any):
    """Data/hora digitada pelo usuário: sem fuso = horário de Brasília."""
    from datetime import datetime

    from src.core.market_hours import BRT

    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=BRT)
    return dt.astimezone(BRT)


def _position_after(conn, ticker: str, extra: Optional[Dict[str, Any]] = None, exclude_id: Optional[int] = None) -> float:
    rows = [dict(r) for r in conn.execute("SELECT * FROM executions WHERE ticker = ?", (ticker,)) if r["id"] != exclude_id]
    if extra:
        rows.append({**extra, "id": 10**12})
    ledger = compute_ledger(rows)
    return sum(p["qty"] for p in ledger["positions"])


def add_execution(data: Dict[str, Any], allow_short: bool = False, conn=None) -> Dict[str, Any]:
    clean = _clean_execution(data)
    with db.transaction(conn) as c:
        if clean["signal_id"] and not c.execute("SELECT 1 FROM signals WHERE id = ?", (clean["signal_id"],)).fetchone():
            raise ValueError("Sinal vinculado não existe.")
        if clean["side"] == "SELL" and not allow_short and _position_after(c, clean["ticker"], clean) < -EPS:
            raise ValueError("Essa venda deixa a posição vendida (a descoberto). Confira a quantidade ou marque 'venda a descoberto'.")
        cur = c.execute(
            "INSERT INTO executions(signal_id, ticker, side, quantity, price, fees, executed_at, asset_class, note, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (clean["signal_id"], clean["ticker"], clean["side"], clean["quantity"], clean["price"], clean["fees"],
             clean["executed_at"], clean["asset_class"], clean["note"], now_iso()),
        )
        exec_id = cur.lastrowid
        if clean["signal_id"] and clean["side"] == ("BUY" if _signal_side(c, clean["signal_id"]) == "BUY" else "SELL"):
            c.execute(
                "INSERT INTO decisions(signal_id, status, decided_at) VALUES(?, 'executed', ?) "
                "ON CONFLICT(signal_id) DO UPDATE SET status = 'executed', remind_at = NULL, decided_at = excluded.decided_at",
                (clean["signal_id"], now_iso()),
            )
        return dict(c.execute("SELECT * FROM executions WHERE id = ?", (exec_id,)).fetchone())


def _signal_side(conn, signal_id: str) -> Optional[str]:
    row = conn.execute("SELECT lado FROM signals WHERE id = ?", (signal_id,)).fetchone()
    return row["lado"] if row else None


def update_execution(exec_id: int, data: Dict[str, Any], allow_short: bool = False, conn=None) -> Dict[str, Any]:
    with db.transaction(conn) as c:
        current = c.execute("SELECT * FROM executions WHERE id = ?", (exec_id,)).fetchone()
        if not current:
            raise KeyError(exec_id)
        clean = _clean_execution({**dict(current), **data})
        if not allow_short:
            for ticker in {current["ticker"], clean["ticker"]}:
                extra = clean if ticker == clean["ticker"] else None
                if _position_after(c, ticker, extra, exclude_id=exec_id) < -EPS:
                    raise ValueError("Com essa alteração a posição fica vendida (a descoberto). Confira as quantidades.")
        c.execute(
            "UPDATE executions SET signal_id=?, ticker=?, side=?, quantity=?, price=?, fees=?, executed_at=?, asset_class=?, note=? WHERE id=?",
            (clean["signal_id"], clean["ticker"], clean["side"], clean["quantity"], clean["price"], clean["fees"],
             clean["executed_at"], clean["asset_class"], clean["note"], exec_id),
        )
        return dict(c.execute("SELECT * FROM executions WHERE id = ?", (exec_id,)).fetchone())


def delete_execution(exec_id: int, conn=None) -> None:
    with db.transaction(conn) as c:
        row = c.execute("SELECT * FROM executions WHERE id = ?", (exec_id,)).fetchone()
        if not row:
            raise KeyError(exec_id)
        c.execute("DELETE FROM executions WHERE id = ?", (exec_id,))
        if row["signal_id"] and not c.execute("SELECT 1 FROM executions WHERE signal_id = ?", (row["signal_id"],)).fetchone():
            c.execute("DELETE FROM decisions WHERE signal_id = ? AND status = 'executed'", (row["signal_id"],))


def ledger(conn=None) -> Dict[str, Any]:
    return compute_ledger(list_executions(conn=conn))
