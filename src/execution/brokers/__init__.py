"""Conectores de execução: conta simulada, MT5 local (Windows) e MT5 remoto (agente HTTP)."""
from src.core.config import execution_flags
from src.execution.brokers.base import Broker, BrokerError
from src.execution.brokers.paper import PaperBroker

_cache = {}


def get_broker(account: str) -> Broker:
    """'paper' -> conta simulada; 'real' -> MT5 conforme execution.broker (mt5_remote | mt5_local)."""
    if account == "paper":
        return PaperBroker()
    flags = execution_flags()
    kind = flags["broker"]
    key = (kind, flags["mt5_agent_url"], flags["mt5_agent_token"], flags["mt5_terminal_path"])
    if key not in _cache:
        if kind == "mt5_local":
            from src.execution.brokers.mt5_local import Mt5LocalBroker

            _cache.clear()
            _cache[key] = Mt5LocalBroker(flags["mt5_terminal_path"], flags["magic_number"])
        else:
            from src.execution.brokers.mt5_remote import Mt5RemoteBroker

            _cache.clear()
            _cache[key] = Mt5RemoteBroker(flags["mt5_agent_url"], flags["mt5_agent_token"])
    return _cache[key]


__all__ = ["Broker", "BrokerError", "PaperBroker", "get_broker"]
