"""
Trades semelhantes em aberto: um sinal novo no mesmo ativo-objeto de uma posição minha.

Ex.: Sanita compra ROXOK135 (CALL de ROXO34) e eu já tenho ROXOJ12 (CALL de ROXO34, sinal do Ferri) — mesmo racional.
O sinal continua aparecendo, com um aviso mostrando a posição parecida.

Direção (exposição ao ativo-objeto): comprar ação/CALL ou vender PUT = alta; vender ação/CALL ou comprar PUT = baixa.
Relações: same_ticker (mesmo ativo) · same_direction (mesmo objeto, mesma direção: aumenta a exposição) ·
opposite (mesmo objeto, direção contrária).
"""
from typing import Any, Dict, List, Optional

from src.core import b3_tickers

ORDER = {"same_ticker": 0, "same_direction": 1, "opposite": 2}


def root(ticker: Optional[str]) -> str:
    """Raiz de 4 letras da empresa (ROXOJ12, ROXOK135 e ROXO34 -> ROXO)."""
    return b3_tickers.clean_ticker(ticker)[:4]


def option_kind(ticker: str, hint: Optional[str] = None) -> Optional[str]:
    if hint and str(hint).upper() in ("CALL", "PUT"):
        return str(hint).upper()
    info = b3_tickers.decode_option(ticker)
    return info["kind"] if info else None


def direction(ticker: str, asset_class: Optional[str], long: bool, kind_hint: Optional[str] = None) -> int:
    """+1 = ganha com a alta do ativo-objeto; -1 = ganha com a queda."""
    sign = 1 if long else -1
    if (asset_class or b3_tickers.asset_class(None, ticker)) == "OPCAO" and option_kind(ticker, kind_hint) == "PUT":
        sign = -sign
    return sign


def find(sig: Dict[str, Any], positions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Posições abertas parecidas com o sinal (exceto as já vinculadas a ele)."""
    r = root(sig.get("ticker"))
    if not r:
        return []
    sig_dir = direction(sig["ticker"], sig.get("asset_class"), sig.get("lado") == "BUY", sig.get("opcao_tipo"))
    out = []
    for p in positions:
        if root(p["ticker"]) != r or sig.get("id") in (p.get("signal_ids") or []):
            continue
        p_dir = direction(p["ticker"], p.get("asset_class"), p["side"] == "LONG")
        relation = "same_ticker" if p["ticker"] == sig["ticker"] else ("same_direction" if p_dir == sig_dir else "opposite")
        psig = p.get("signal") or {}
        info = b3_tickers.decode_option(p["ticker"]) if p.get("asset_class") == "OPCAO" else None
        out.append({
            "relation": relation,
            "ticker": p["ticker"],
            "cycle_id": p.get("cycle_id"),
            "side": p["side"],
            "kind": info["kind"] if info else None,
            "underlying": (info or {}).get("underlying") or b3_tickers.underlying_of(p["ticker"]),
            "expiration": psig.get("expiration") or (info or {}).get("expiration"),
            "quantity": p.get("quantity"),
            "avg_price": p.get("avg_price"),
            "last_price": p.get("last_price"),
            "unrealized_pnl": p.get("unrealized_pnl"),
            "unrealized_pct": p.get("unrealized_pct"),
            "trader": psig.get("trader"),
            "signal_guessed": bool(p.get("signal_guessed")),
            "opened_at": p.get("opened_at"),
        })
    out.sort(key=lambda x: ORDER[x["relation"]])
    return out


def describe(items: List[Dict[str, Any]]) -> str:
    """Texto curto para alertas: 'semelhante a ROXOJ12 (Ferri) em carteira'."""
    if not items:
        return ""
    s = items[0]
    who = f" ({s['trader']})" if s.get("trader") else ""
    label = {"same_ticker": "você já tem", "same_direction": "semelhante a", "opposite": "contrário a"}[s["relation"]]
    return f"{label} {s['ticker']}{who} em carteira"


__all__ = ["find", "describe", "direction", "root"]
