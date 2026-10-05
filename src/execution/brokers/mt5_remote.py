"""
Cliente HTTP do agente MT5 (src/execution/agent.py), que roda no Windows ao lado do terminal.
É o caminho usado quando o Copiloto roda em Docker/Linux.
"""
from typing import Any, Dict, Optional

import requests

from src.execution.brokers.base import Broker, BrokerError


class Mt5RemoteBroker(Broker):
    name = "mt5"

    def __init__(self, base_url: str, token: str, timeout: int = 15, session: Optional[requests.Session] = None):
        if not base_url:
            raise BrokerError("MT5_AGENT_URL não configurado (endereço do agente MT5 no Windows)")
        if not token:
            raise BrokerError("MT5_AGENT_TOKEN não configurado")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def _call(self, method: str, path: str, **kw) -> Dict[str, Any]:
        try:
            resp = self.session.request(method, f"{self.base_url}{path}", timeout=self.timeout, **kw)
        except requests.RequestException as exc:
            raise BrokerError(f"Agente MT5 inacessível em {self.base_url} ({exc.__class__.__name__})") from exc
        if resp.status_code == 401:
            raise BrokerError("Agente MT5 recusou o token (confira MT5_AGENT_TOKEN nos dois lados)")
        try:
            data = resp.json()
        except ValueError as exc:
            raise BrokerError(f"Resposta inválida do agente MT5 (HTTP {resp.status_code})") from exc
        if resp.status_code >= 500 or (resp.status_code >= 400 and "error" in data):
            raise BrokerError(data.get("error") or f"Erro no agente MT5 (HTTP {resp.status_code})")
        if resp.status_code >= 400:
            raise BrokerError(f"Erro no agente MT5 (HTTP {resp.status_code})")
        return data

    def health(self) -> Dict[str, Any]:
        try:
            return self._call("GET", "/health")
        except BrokerError as exc:
            return {"ok": False, "connected": False, "message": str(exc), "account": None}

    def quote(self, symbol: str):
        return self._call("GET", f"/quote/{symbol}").get("quote")

    def quotes(self, symbols):
        if not symbols:
            return {}
        try:
            return self._call("GET", "/quotes", params={"symbols": ",".join(symbols)}).get("quotes") or {}
        except BrokerError as exc:
            if "HTTP 404" not in str(exc):
                raise
            return super().quotes(symbols)  # agente de versão anterior, sem /quotes

    def place_order(self, symbol, side, quantity, order_type, limit_price, comment=""):
        return self._call("POST", "/orders", json={
            "symbol": symbol, "side": side, "quantity": quantity, "order_type": order_type,
            "limit_price": limit_price, "comment": comment,
        })

    def order_status(self, broker_order_id: str, symbol: str) -> Dict[str, Any]:
        return self._call("GET", f"/orders/{broker_order_id}", params={"symbol": symbol})

    def cancel_order(self, broker_order_id: str, symbol: str) -> Dict[str, Any]:
        return self._call("POST", f"/orders/{broker_order_id}/cancel", json={"symbol": symbol})
