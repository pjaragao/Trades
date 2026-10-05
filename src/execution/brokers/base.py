"""
Interface comum dos conectores de execução.

Todos devolvem dicionários simples (serializáveis em JSON), para funcionar igual localmente
e através do agente HTTP que roda no Windows ao lado do terminal MT5.

Status de ordem: open | partial | filled | cancelled | rejected | expired
"""
from typing import Any, Dict, List, Optional


class BrokerError(Exception):
    """Falha de comunicação com o conector (agente fora do ar, MT5 desconectado...)."""


class Broker:
    name = "base"

    def health(self) -> Dict[str, Any]:
        """{'ok': bool, 'connected': bool, 'message': str, 'account': {...}}"""
        raise NotImplementedError

    def quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """{'bid', 'ask', 'last', 'time', 'change_pct'?} ou None"""
        raise NotImplementedError

    def quotes(self, symbols: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """Várias cotações de uma vez (conectores podem otimizar)."""
        return {s: self.quote(s) for s in symbols}

    def place_order(self, symbol: str, side: str, quantity: float, order_type: str,
                    limit_price: Optional[float], comment: str = "") -> Dict[str, Any]:
        """
        {'accepted': bool, 'broker_order_id': str|None, 'status': str, 'message': str,
         'fills': [{'id', 'quantity', 'price', 'fees', 'time'}]}
        """
        raise NotImplementedError

    def order_status(self, broker_order_id: str, symbol: str) -> Dict[str, Any]:
        """{'status': str, 'filled_qty': float, 'fills': [...], 'message': str}"""
        raise NotImplementedError

    def cancel_order(self, broker_order_id: str, symbol: str) -> Dict[str, Any]:
        """{'ok': bool, 'message': str}"""
        raise NotImplementedError


def fills_total(fills: List[Dict[str, Any]]) -> float:
    return sum(float(f["quantity"]) for f in fills)
