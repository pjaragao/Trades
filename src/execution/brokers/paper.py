"""
Conta simulada (paper trading): preenche ordens pelas cotações conhecidas (TradingFloors/MT5/manual).

- Limite de compra é preenchido quando a cotação está <= limite (no menor dos dois preços);
  limite de venda quando a cotação está >= limite. Sem cotação conhecida, preenche no limite.
- Ordem a mercado preenche na cotação; sem cotação, é rejeitada.
O estado das ordens vive na própria tabela `orders` do Copiloto.
"""
import uuid
from typing import Any, Dict, Optional

from src.core import db
from src.core.config import now_iso
from src.execution.brokers.base import Broker


class PaperBroker(Broker):
    name = "paper"

    def health(self) -> Dict[str, Any]:
        return {"ok": True, "connected": True, "message": "Conta simulada", "account": {"login": "SIMULAÇÃO", "company": "Copiloto"}}

    def quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        with db.connection() as c:
            row = c.execute("SELECT price, updated_at FROM quotes WHERE ticker = ?", (symbol,)).fetchone()
        if not row:
            return None
        return {"bid": row["price"], "ask": row["price"], "last": row["price"], "time": row["updated_at"]}

    def _try_fill(self, side: str, quantity: float, order_type: str, limit_price: Optional[float], symbol: str):
        q = self.quote(symbol)
        px = q["last"] if q else None
        if order_type == "market":
            return px
        if px is None:
            return limit_price
        if side == "BUY" and px <= limit_price:
            return min(px, limit_price)
        if side == "SELL" and px >= limit_price:
            return max(px, limit_price)
        return None

    def _fill(self, quantity: float, price: float) -> Dict[str, Any]:
        return {"id": f"paper-{uuid.uuid4().hex[:10]}", "quantity": quantity, "price": round(price, 4), "fees": 0.0, "time": now_iso()}

    def place_order(self, symbol, side, quantity, order_type, limit_price, comment=""):
        oid = f"P{uuid.uuid4().hex[:10]}"
        price = self._try_fill(side, quantity, order_type, limit_price, symbol)
        if price is None and order_type == "market":
            return {"accepted": False, "broker_order_id": None, "status": "rejected", "message": "Sem cotação para ordem a mercado (simulação)", "fills": []}
        if price is None:
            return {"accepted": True, "broker_order_id": oid, "status": "open", "message": "Aguardando o preço atingir o limite (simulação)", "fills": []}
        return {"accepted": True, "broker_order_id": oid, "status": "filled", "message": "Executada (simulação)", "fills": [self._fill(quantity, price)]}

    def order_status(self, broker_order_id: str, symbol: str) -> Dict[str, Any]:
        with db.connection() as c:
            o = c.execute("SELECT * FROM orders WHERE broker_order_id = ? AND broker = 'paper'", (broker_order_id,)).fetchone()
        if not o:
            return {"status": "rejected", "filled_qty": 0, "fills": [], "message": "Ordem simulada não encontrada"}
        if o["status"] in ("filled", "cancelled", "rejected", "expired"):
            return {"status": o["status"], "filled_qty": o["filled_qty"], "fills": [], "message": ""}
        remaining = o["quantity"] - (o["filled_qty"] or 0)
        price = self._try_fill(o["side"], remaining, o["order_type"], o["limit_price"], symbol)
        if price is None:
            return {"status": "open", "filled_qty": o["filled_qty"], "fills": [], "message": "Aguardando preço (simulação)"}
        return {"status": "filled", "filled_qty": o["quantity"], "fills": [self._fill(remaining, price)], "message": "Executada (simulação)"}

    def cancel_order(self, broker_order_id: str, symbol: str) -> Dict[str, Any]:
        return {"ok": True, "message": "Cancelada (simulação)"}
