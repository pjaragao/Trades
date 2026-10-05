"""
Cliente da API do TradingFloors (Supabase REST) + normalização/deduplicação de sinais.

Fontes:
- `trades`        : tabela canônica — todos os produtos, inclusive opções (tipo_ativo OPCOES),
                    com saída, P&L, stop/alvo. Cada linha é um sinal distinto.
- `opcoes_trades` : só as opções ABERTAS, com `preco_atual`, `strike` e `opcao_tipo`.
                    Linhas somem daqui quando a operação é encerrada.

`merge_rows()` é o ÚNICO lugar com regra de deduplicação: cada linha de `opcoes_trades`
enriquece a linha de `trades` correspondente (via `opcao_id`, ou ticker+analista+lado),
e só vira sinal próprio se não houver correspondente.
"""
import json
import threading
import time
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

from src.core import b3_tickers
from src.core.market_hours import to_brt
from src.utils import normalize_trader_name


class TFError(Exception):
    """Falha de comunicação/autenticação com o TradingFloors."""


class TradingFloorsAPI:
    PAGE = 1000

    def __init__(self, supabase_url: str, anon_key: str, email: str, password: str, timeout: int = 15):
        self.url = supabase_url.rstrip("/")
        self.anon_key = anon_key
        self.email = email
        self.password = password
        self.timeout = timeout
        self._session = requests.Session()
        self._lock = threading.Lock()
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._expires_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.url and self.anon_key and self.email and self.password)

    # ------------------------------------------------------------------ auth
    def _auth(self, grant: str, payload: Dict[str, Any]) -> None:
        resp = self._session.post(
            f"{self.url}/auth/v1/token?grant_type={grant}",
            headers={"apikey": self.anon_key, "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise TFError(f"Autenticação recusada (HTTP {resp.status_code})")
        data = resp.json()
        self._access_token = data.get("access_token")
        self._refresh_token = data.get("refresh_token") or self._refresh_token
        self._expires_at = time.time() + int(data.get("expires_in", 3600)) - 120

    def _token(self) -> str:
        with self._lock:
            if self._access_token and time.time() < self._expires_at:
                return self._access_token
            if not self.configured:
                raise TFError("Credenciais do TradingFloors não configuradas (config/.env)")
            try:
                if self._refresh_token:
                    try:
                        self._auth("refresh_token", {"refresh_token": self._refresh_token})
                        return self._access_token  # type: ignore[return-value]
                    except TFError:
                        self._refresh_token = None
                self._auth("password", {"email": self.email, "password": self.password})
            except requests.RequestException as exc:
                raise TFError(f"Sem conexão com o TradingFloors: {exc.__class__.__name__}") from exc
            return self._access_token  # type: ignore[return-value]

    def invalidate(self) -> None:
        with self._lock:
            self._access_token = None
            self._expires_at = 0.0

    # ------------------------------------------------------------------ REST
    def _get(self, path: str, params: Dict[str, str]) -> List[Dict[str, Any]]:
        for attempt in (1, 2):
            headers = {"apikey": self.anon_key, "Authorization": f"Bearer {self._token()}"}
            try:
                resp = self._session.get(f"{self.url}/rest/v1/{path}", headers=headers, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                raise TFError(f"Sem conexão com o TradingFloors: {exc.__class__.__name__}") from exc
            if resp.status_code == 401 and attempt == 1:
                self.invalidate()
                continue
            if resp.status_code != 200:
                raise TFError(f"Erro ao consultar {path} (HTTP {resp.status_code})")
            return resp.json()
        raise TFError("Sessão expirada")

    def _get_all(self, path: str, params: Dict[str, str]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        offset = 0
        while True:
            page = self._get(path, {**params, "offset": str(offset), "limit": str(self.PAGE)})
            rows.extend(page)
            if len(page) < self.PAGE:
                return rows
            offset += self.PAGE

    def fetch_open(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        params = {"select": "*", "status": "eq.OPEN", "order": "timestamp_entrada.desc"}
        return self._get_all("trades", params), self._get_all("opcoes_trades", params)

    def fetch_trades_updated_since(self, iso_ts: str) -> List[Dict[str, Any]]:
        return self._get_all("trades", {"select": "*", "updated_at": f"gte.{iso_ts}", "order": "updated_at.asc"})

    def fetch_trades_by_ids(self, ids: Iterable[str]) -> List[Dict[str, Any]]:
        ids = [i for i in ids if i]
        out: List[Dict[str, Any]] = []
        for i in range(0, len(ids), 50):
            chunk = ",".join(ids[i:i + 50])
            out.extend(self._get("trades", {"select": "*", "id": f"in.({chunk})"}))
        return out

    def fetch_recent_closed(self, ticker: str, trader_raw_hint: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        return self._get("trades", {
            "select": "*", "ticker": f"eq.{ticker}", "status": "eq.CLOSED",
            "order": "timestamp_saida.desc", "limit": str(limit),
        })

    def fetch_all(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        params = {"select": "*", "order": "timestamp_entrada.asc"}
        return self._get_all("trades", params), self._get_all("opcoes_trades", params)


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------

def _f(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status(value: Any) -> str:
    s = str(value or "OPEN").strip().upper()
    return "CLOSED" if s in ("CLOSED", "ENCERRADO", "FECHADO") else "OPEN"


def _side(value: Any) -> str:
    s = str(value or "BUY").strip().upper()
    return "SELL" if s in ("SELL", "VENDA", "V") else "BUY"


def _entry_date(row: Dict[str, Any]) -> Optional[date]:
    dt = to_brt(row.get("timestamp_entrada"))
    return dt.date() if dt else None


def normalize_row(row: Dict[str, Any], source: str) -> Dict[str, Any]:
    ticker = b3_tickers.clean_ticker(row.get("ticker"))
    tipo = row.get("tipo_ativo") or ("OPCOES" if source == "opcoes_trades" else None)
    asset = b3_tickers.asset_class(tipo, ticker)
    produto = row.get("produto") or ("Opções" if source == "opcoes_trades" else "Trading Floor")

    sig: Dict[str, Any] = {
        "id": row.get("id"),
        "source": source,
        "trades_id": row.get("id") if source == "trades" else None,
        "linked_ids": [],
        "produto": produto,
        "tipo_ativo": tipo,
        "asset_class": asset,
        "ticker": ticker,
        "underlying": None,
        "opcao_tipo": row.get("opcao_tipo"),
        "strike": _f(row.get("strike")),
        "expiration": None,
        "trader": normalize_trader_name(row.get("trader_nome")),
        "lado": _side(row.get("lado")),
        "quantidade": _f(row.get("quantidade")),
        "preco_entrada": _f(row.get("preco_entrada")),
        "stop_loss": _f(row.get("stop_loss")),
        "take_profit": _f(row.get("take_profit")),
        "preco_atual": _f(row.get("preco_atual")),
        "preco_saida": _f(row.get("preco_saida")),
        "pnl_realizado": _f(row.get("pnl_realizado")),
        "pnl_pontos": _f(row.get("pnl_pontos")),
        "timestamp_entrada": row.get("timestamp_entrada"),
        "timestamp_saida": row.get("timestamp_saida"),
        "status": _status(row.get("status")),
        "opcao_ref": row.get("opcao_id"),
        "raw": [row],
    }
    _enrich_ticker(sig)
    return sig


def _enrich_ticker(sig: Dict[str, Any]) -> None:
    if sig["asset_class"] == "OPCAO":
        info = b3_tickers.decode_option(sig["ticker"], _entry_date(sig))
        if info:
            sig["underlying"] = info["underlying"]
            sig["expiration"] = info["expiration"]
            if not sig.get("opcao_tipo"):
                sig["opcao_tipo"] = info["kind"]
    elif sig["asset_class"] == "ACAO":
        sig["underlying"] = b3_tickers.underlying_of(sig["ticker"])


def _key(sig: Dict[str, Any]) -> Tuple[str, str, str]:
    return (sig["ticker"], sig["trader"].lower(), sig["lado"])


def _absorb(target: Dict[str, Any], opt: Dict[str, Any]) -> None:
    """Enriquece o sinal canônico (de `trades`) com os dados vivos de `opcoes_trades`."""
    if opt["id"] not in target["linked_ids"] and opt["id"] != target["id"]:
        target["linked_ids"].append(opt["id"])
    if opt.get("preco_atual") is not None:
        target["preco_atual"] = opt["preco_atual"]
    for field in ("strike", "opcao_tipo"):
        if opt.get(field) is not None and target.get(field) is None:
            target[field] = opt[field]
    if target["asset_class"] != "OPCAO":
        target["asset_class"] = "OPCAO"
        _enrich_ticker(target)
    produtos = [p.strip() for p in str(target.get("produto") or "").split("/") if p.strip()]
    if "Opções" not in produtos:
        produtos.append("Opções")
        target["produto"] = " / ".join(produtos)
    target["raw"].append(opt["raw"][0])


def merge_rows(trades_rows: Iterable[Dict[str, Any]], opcoes_rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Une as duas tabelas em uma lista de sinais sem duplicatas."""
    signals: List[Dict[str, Any]] = [normalize_row(r, "trades") for r in trades_rows if r.get("id")]
    by_id = {s["id"]: s for s in signals}
    by_opcao_ref = {s["opcao_ref"]: s for s in signals if s.get("opcao_ref")}

    by_key: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    for s in signals:
        by_key.setdefault(_key(s), []).append(s)

    for row in opcoes_rows:
        if not row.get("id"):
            continue
        opt = normalize_row(row, "opcoes_trades")
        if opt["id"] in by_id:
            continue
        target = by_opcao_ref.get(opt["id"])
        if target is None:
            target = _closest(by_key.get(_key(opt), []), opt)
        if target is not None:
            _absorb(target, opt)
            continue
        signals.append(opt)
        by_id[opt["id"]] = opt
        by_key.setdefault(_key(opt), []).append(opt)

    for s in signals:
        s.pop("opcao_ref", None)
    return signals


def _closest(candidates: List[Dict[str, Any]], opt: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Mesmo ticker/analista/lado: prefere o de mesmo status e entrada mais próxima (até 3 dias)."""
    opt_dt = to_brt(opt.get("timestamp_entrada"))
    best, best_score = None, None
    for c in candidates:
        c_dt = to_brt(c.get("timestamp_entrada"))
        if opt_dt is None or c_dt is None:
            continue
        gap_days = abs((c_dt - opt_dt).total_seconds()) / 86400
        if gap_days > 3:
            continue
        score = (0 if c["status"] == opt["status"] else 1, gap_days)
        if best_score is None or score < best_score:
            best, best_score = c, score
    return best


def signal_to_db_row(sig: Dict[str, Any]) -> Dict[str, Any]:
    row = {k: v for k, v in sig.items() if k not in ("raw", "linked_ids")}
    row["linked_ids"] = json.dumps(sig.get("linked_ids") or [])
    row["raw_json"] = json.dumps(sig.get("raw") or [], ensure_ascii=False, default=str)
    return row


# ---------------------------------------------------------------------------
# Instância compartilhada (token em cache entre requisições)
# ---------------------------------------------------------------------------

_client: Optional[TradingFloorsAPI] = None
_client_lock = threading.Lock()


def get_client(reload: bool = False) -> TradingFloorsAPI:
    global _client
    from src.core.config import tf_settings

    with _client_lock:
        if _client is None or reload:
            url, key, email, pwd = tf_settings()
            _client = TradingFloorsAPI(url, key, email, pwd)
        return _client
