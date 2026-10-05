"""
Conector direto ao terminal MetaTrader 5 (pacote `MetaTrader5`, só no Windows).

Usado pelo agente (src/execution/agent.py) ou pelo próprio Copiloto quando roda no Windows.
A API do MT5 não é thread-safe: todas as chamadas passam por um lock.

Horários: o MT5 devolve o horário do SERVIDOR da corretora como se fosse UTC. Nas corretoras da B3 o
servidor usa o horário de Brasília (MT5_SERVER_UTC_OFFSET, padrão -3); se o resultado cair no
futuro, o servidor está em UTC e o valor é usado direto.
"""
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.execution.brokers.base import Broker, BrokerError

STATE_MAP = {0: "open", 1: "open", 2: "cancelled", 3: "partial", 4: "filled", 5: "rejected", 6: "expired", 7: "open", 8: "open", 9: "open"}


class Mt5LocalBroker(Broker):
    name = "mt5"

    def __init__(self, terminal_path: str = "", magic: int = 998877, mt5_module=None, server_utc_offset: Optional[float] = None):
        self.terminal_path = terminal_path
        self.magic = magic
        self._mt5 = mt5_module
        self._lock = threading.RLock()
        self._initialized = False
        self._selected: set = set()
        if server_utc_offset is None:
            try:
                server_utc_offset = float(os.getenv("MT5_SERVER_UTC_OFFSET") or -3)
            except ValueError:
                server_utc_offset = -3.0
        self.server_tz = timezone(timedelta(hours=server_utc_offset))

    def _ts(self, value: float) -> str:
        """Horário do servidor MT5 -> ISO em UTC."""
        raw = datetime.fromtimestamp(float(value), timezone.utc)
        local = raw.replace(tzinfo=self.server_tz).astimezone(timezone.utc)
        if local > datetime.now(timezone.utc) + timedelta(minutes=10):
            local = raw
        return local.isoformat(timespec="seconds")

    # ------------------------------------------------------------------ conexão
    @property
    def mt5(self):
        if self._mt5 is None:
            try:
                import MetaTrader5 as mt5  # type: ignore
            except ImportError as exc:
                raise BrokerError("Pacote MetaTrader5 não instalado (só funciona no Windows: pip install MetaTrader5)") from exc
            self._mt5 = mt5
        return self._mt5

    def _ensure(self) -> None:
        mt5 = self.mt5
        if self._initialized:
            info = mt5.terminal_info()
            if info is not None and getattr(info, "connected", True):
                return
            self._initialized = False
        kwargs = {"path": self.terminal_path} if self.terminal_path else {}
        if not mt5.initialize(**kwargs):
            raise BrokerError(f"Não foi possível conectar ao terminal MT5: {mt5.last_error()}")
        self._initialized = True
        self._selected.clear()

    def health(self) -> Dict[str, Any]:
        with self._lock:
            try:
                self._ensure()
            except BrokerError as exc:
                return {"ok": False, "connected": False, "message": str(exc), "account": None}
            mt5 = self.mt5
            acc = mt5.account_info()
            term = mt5.terminal_info()
            if acc is None:
                return {"ok": False, "connected": False, "message": "Terminal aberto, mas sem conta logada", "account": None}
            trade_ok = bool(getattr(term, "trade_allowed", True)) and bool(getattr(acc, "trade_allowed", True))
            return {
                "ok": trade_ok,
                "connected": True,
                "message": "Conectado" if trade_ok else "Negociação automática desabilitada no terminal (botão Algo Trading)",
                "account": {
                    "login": acc.login, "server": getattr(acc, "server", ""), "company": getattr(acc, "company", ""),
                    "balance": getattr(acc, "balance", None), "equity": getattr(acc, "equity", None),
                    "margin_free": getattr(acc, "margin_free", None), "currency": getattr(acc, "currency", "BRL"),
                    "trade_allowed": trade_ok,
                },
            }

    def _tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        mt5 = self.mt5
        if symbol not in self._selected:
            if not mt5.symbol_select(symbol, True):  # símbolo inexistente nesta corretora
                return None
            self._selected.add(symbol)
        t = mt5.symbol_info_tick(symbol)
        if not t:
            return None
        bid, ask, last = (t.bid or None), (t.ask or None), (getattr(t, "last", 0) or None)
        if not (bid or ask or last):  # recém-adicionado ao Market Watch, ainda sem dados
            return None
        info = mt5.symbol_info(symbol)
        change = getattr(info, "price_change", None) if info is not None else None
        return {"bid": bid, "ask": ask, "last": last, "time": self._ts(t.time) if t.time else None,
                "change_pct": round(float(change), 2) if change not in (None, 0) else None}

    def quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._ensure()
            return self._tick(symbol)

    def quotes(self, symbols: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        with self._lock:
            self._ensure()
            return {s: self._tick(s) for s in symbols}

    # ------------------------------------------------------------------ ordens
    def place_order(self, symbol, side, quantity, order_type, limit_price, comment=""):
        with self._lock:
            self._ensure()
            mt5 = self.mt5
            if not mt5.symbol_select(symbol, True):
                return {"accepted": False, "broker_order_id": None, "status": "rejected", "message": f"Símbolo {symbol} não encontrado no MT5", "fills": []}
            buy = side == "BUY"
            req: Dict[str, Any] = {
                "symbol": symbol,
                "volume": float(quantity),
                "magic": self.magic,
                "comment": (comment or "Copiloto")[:31],
                "type_time": mt5.ORDER_TIME_DAY,
                "type_filling": mt5.ORDER_FILLING_RETURN,
            }
            if order_type == "market":
                tick = mt5.symbol_info_tick(symbol)
                req.update(action=mt5.TRADE_ACTION_DEAL, type=mt5.ORDER_TYPE_BUY if buy else mt5.ORDER_TYPE_SELL,
                           price=float((tick.ask if buy else tick.bid) if tick else 0.0), deviation=50)
            else:
                req.update(action=mt5.TRADE_ACTION_PENDING, type=mt5.ORDER_TYPE_BUY_LIMIT if buy else mt5.ORDER_TYPE_SELL_LIMIT,
                           price=float(limit_price))
            res = mt5.order_send(req)
            if res is None:
                return {"accepted": False, "broker_order_id": None, "status": "rejected", "message": f"MT5 sem resposta: {mt5.last_error()}", "fills": []}
            ok_codes = {mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED, getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)}
            if res.retcode not in ok_codes:
                return {"accepted": False, "broker_order_id": str(res.order) if res.order else None, "status": "rejected",
                        "message": f"MT5 recusou (retcode {res.retcode}): {res.comment}", "fills": []}
            oid = str(res.order or res.deal)
        st = self.order_status(oid, symbol)
        return {"accepted": True, "broker_order_id": oid, "status": st["status"], "message": res.comment or st.get("message", ""), "fills": st["fills"]}

    def _deals_for(self, ticket: int, symbol: str) -> List[Dict[str, Any]]:
        mt5 = self.mt5
        now = datetime.now()
        deals = mt5.history_deals_get(now - timedelta(days=7), now + timedelta(days=2), group=symbol) or []
        out = []
        for d in deals:
            if int(getattr(d, "order", 0)) != ticket:
                continue
            fees = abs(float(getattr(d, "commission", 0) or 0)) + abs(float(getattr(d, "fee", 0) or 0))
            out.append({"id": str(d.ticket), "quantity": float(d.volume), "price": float(d.price), "fees": round(fees, 2),
                        "time": self._ts(d.time)})
        return out

    def order_status(self, broker_order_id: str, symbol: str) -> Dict[str, Any]:
        with self._lock:
            self._ensure()
            mt5 = self.mt5
            ticket = int(broker_order_id)
            fills = self._deals_for(ticket, symbol)
            filled = sum(f["quantity"] for f in fills)
            live = mt5.orders_get(ticket=ticket)
            if live:
                o = live[0]
                status = "partial" if filled > 0 or o.volume_current < o.volume_initial else "open"
                return {"status": status, "filled_qty": filled, "fills": fills, "message": ""}
            hist = mt5.history_orders_get(ticket=ticket)
            if hist:
                status = STATE_MAP.get(int(hist[0].state), "open")
                # cancelada/expirada com preenchimento parcial: filled_qty indica o quanto executou
                return {"status": status, "filled_qty": filled, "fills": fills, "message": ""}
            if fills:  # ordem a mercado: só há o negócio
                return {"status": "filled", "filled_qty": filled, "fills": fills, "message": ""}
            return {"status": "open", "filled_qty": 0.0, "fills": [], "message": "Ordem ainda não aparece no histórico"}

    def cancel_order(self, broker_order_id: str, symbol: str) -> Dict[str, Any]:
        with self._lock:
            self._ensure()
            mt5 = self.mt5
            res = mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": int(broker_order_id)})
            ok = res is not None and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED)
            return {"ok": ok, "message": "Cancelada" if ok else f"Falha ao cancelar: {getattr(res, 'comment', mt5.last_error())}"}
