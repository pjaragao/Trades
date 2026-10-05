"""
Fontes de cotação do feed ao vivo (src/services/quotes.py).

- Mt5Quotes   : terminal MetaTrader 5 da corretora (agente HTTP no Windows, ou MT5 local) — tempo real,
                com bid/ask, para ações e opções.
- BrapiQuotes : brapi.dev — só ações (o plano gratuito não tem opções nem futuros), dados renovados a cada
                30 min, um ativo por requisição e 15.000 requisições numa janela móvel de 30 dias. O ritmo das
                consultas é dimensionado em src/services/quotes.py (BrapiBudget).

Cada fonte devolve {ticker: {'bid', 'ask', 'last', 'time', 'change_pct'} | None} e levanta ProviderError
quando a fonte inteira está fora do ar.
"""
import logging
from typing import Any, Dict, List, Optional, Set

import requests

from src.core import b3_tickers
from src.core.config import execution_flags

log = logging.getLogger("copiloto.market_data")


class ProviderError(Exception):
    """A fonte de cotações não respondeu (agente fora do ar, token inválido...)."""


class Mt5Quotes:
    name = "mt5"
    label = "MT5"
    realtime = True
    delay_minutes = 0

    def __init__(self, broker=None):
        if broker is not None:
            self._broker = broker
            return
        ex = execution_flags()
        if ex["broker"] == "mt5_local":
            from src.execution.brokers import get_broker

            self._broker = get_broker("real")  # mesma conexão do MT5 usada nas ordens
        else:
            from src.execution.brokers.mt5_remote import Mt5RemoteBroker

            self._broker = Mt5RemoteBroker(ex["mt5_agent_url"], ex["mt5_agent_token"], timeout=5)

    def supports(self, ticker: str) -> bool:
        return b3_tickers.asset_class(None, ticker) in ("ACAO", "OPCAO")

    def fetch(self, tickers: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        from src.execution.brokers.base import BrokerError

        try:
            return self._broker.quotes(tickers)
        except BrokerError as exc:
            raise ProviderError(str(exc)) from exc


class BrapiQuotes:
    """
    Depois de cada `fetch`, o feed lê:
      remaining / limit : requisições restantes na janela de 30 dias (cabeçalhos x-ratelimit-*)
      unsupported       : ativos recusados (fora do plano ou inexistentes) — não insistir
      retry_after       : segundos para esperar (HTTP 429: cota esgotada ou requisições simultâneas)
    """

    name = "brapi"
    label = "brapi"
    realtime = False
    delay_minutes = 30
    URL = "https://brapi.dev/api/quote/{}"

    def __init__(self, token: str, session: Optional[requests.Session] = None, on_request=None):
        if not token:
            raise ProviderError("BRAPI_TOKEN não configurado (crie um token grátis em brapi.dev)")
        self.session = session or requests.Session()
        # token no cabeçalho (não vai parar em logs de URL)
        self.session.headers.update({"Authorization": f"Bearer {token}", "User-Agent": "copiloto-de-trades"})
        self.on_request = on_request
        self.remaining: Optional[int] = None
        self.limit: Optional[int] = None
        self.unsupported: Set[str] = set()
        self.retry_after: Optional[float] = None

    def supports(self, ticker: str) -> bool:
        return b3_tickers.asset_class(None, ticker) == "ACAO"

    def _read_limits(self, resp) -> None:
        h = resp.headers or {}
        for attr, key in (("remaining", "x-ratelimit-remaining"), ("limit", "x-ratelimit-limit")):
            try:
                if h.get(key) is not None:
                    setattr(self, attr, int(h.get(key)))
            except (TypeError, ValueError):
                pass

    def fetch(self, tickers: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        out: Dict[str, Optional[Dict[str, Any]]] = {}
        self.unsupported, self.retry_after = set(), None
        for t in tickers:  # plano gratuito: um ativo por requisição, uma de cada vez
            try:
                resp = self.session.get(self.URL.format(t), timeout=10)
            except requests.RequestException as exc:
                raise ProviderError(f"brapi.dev inacessível ({exc.__class__.__name__})") from exc
            if self.on_request:
                self.on_request()
            self._read_limits(resp)
            if resp.status_code == 401:
                raise ProviderError("brapi.dev recusou o token (confira BRAPI_TOKEN)")
            if resp.status_code == 429:
                try:
                    self.retry_after = float(resp.headers.get("retry-after") or 0) or None
                except (TypeError, ValueError):
                    self.retry_after = None
                self.retry_after = self.retry_after or 3600.0
                break
            if resp.status_code in (400, 403, 404):  # fora do plano / não é ação / inexistente
                self.unsupported.add(t)
                out[t] = None
                continue
            if resp.status_code != 200:
                out[t] = None
                continue
            try:
                r = (resp.json().get("results") or [None])[0]
            except ValueError:
                r = None
            price = r.get("regularMarketPrice") if r else None
            out[t] = {"bid": None, "ask": None, "last": float(price), "time": r.get("regularMarketTime"),
                      "change_pct": r.get("regularMarketChangePercent")} if price else None
        return out


def make_providers(flags: Dict[str, Any], on_brapi_request=None):
    """(fonte em tempo real | None, fonte atrasada | None) conforme market_data_flags()."""
    rt = Mt5Quotes() if flags["mt5"] else None
    slow = BrapiQuotes(flags["brapi_token"], on_request=on_brapi_request) if flags["brapi"] else None
    return rt, slow


__all__ = ["ProviderError", "Mt5Quotes", "BrapiQuotes", "make_providers"]
