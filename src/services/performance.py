"""
Estatísticas por analista a partir do histórico de sinais (TradingFloors) e "copiável manualmente?".

Copiável = o analista costuma carregar a posição de um pregão para outro. Scalps intraday
(entrada e saída no mesmo dia) chegam atrasados quando copiados à mão.
"""
import statistics
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from src.core import db
from src.core.b3_tickers import ASSET_CLASS_LABELS
from src.core.market_hours import to_brt

MIN_SAMPLE = 5
_cache: Dict[str, Tuple[float, Any]] = {}
CACHE_SECONDS = 300


def _ret_pct(row) -> Optional[float]:
    entry, exit_ = row["preco_entrada"], row["preco_saida"]
    if not entry or exit_ is None or entry <= 0:
        return None
    sign = 1 if row["lado"] == "BUY" else -1
    return sign * (exit_ / entry - 1) * 100


def copyable_label(same_day_share: Optional[float], median_days: Optional[float], n: int) -> str:
    if n < MIN_SAMPLE or same_day_share is None:
        return "unknown"
    if same_day_share >= 0.6:
        return "no"
    if same_day_share < 0.4 and (median_days or 0) >= 1:
        return "yes"
    return "partial"


def _stats(rows: List[Any]) -> Dict[str, Any]:
    rets, holds, same_day = [], [], 0
    for r in rows:
        ret = _ret_pct(r)
        if ret is not None:
            rets.append(ret)
        e, s = to_brt(r["timestamp_entrada"]), to_brt(r["timestamp_saida"])
        if e and s:
            holds.append(max(0.0, (s - e).total_seconds() / 86400))
            if e.date() == s.date():
                same_day += 1
    n = len(rets)
    wins = [x for x in rets if x > 0]
    losses = [x for x in rets if x <= 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    same_share = same_day / len(holds) if holds else None
    median_days = statistics.median(holds) if holds else None
    return {
        "closed": n,
        "win_rate": round(len(wins) / n * 100, 1) if n else None,
        "avg_return_pct": round(sum(rets) / n, 2) if n else None,
        "avg_win_pct": round(gross_win / len(wins), 2) if wins else None,
        "avg_loss_pct": round(-gross_loss / len(losses), 2) if losses else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else (None if not wins else 99.0),
        "median_hold_days": round(median_days, 1) if median_days is not None else None,
        "same_day_share": round(same_share * 100, 1) if same_share is not None else None,
        "copyable": copyable_label(same_share, median_days, n),
    }


def trader_profiles(conn=None, use_cache: bool = True) -> List[Dict[str, Any]]:
    """Uma linha por (analista, classe de ativo), mais um agregado por analista."""
    key = str(db.db_path())
    if use_cache and key in _cache and time.time() - _cache[key][0] < CACHE_SECONDS:
        return _cache[key][1]

    with db.connection(conn) as c:
        rows = c.execute(
            "SELECT trader, asset_class, lado, preco_entrada, preco_saida, timestamp_entrada, timestamp_saida, status FROM signals"
        ).fetchall()

    groups: Dict[Tuple[str, str], List[Any]] = defaultdict(list)
    open_counts: Dict[Tuple[str, str], int] = defaultdict(int)
    last_signal: Dict[Tuple[str, str], str] = {}
    for r in rows:
        k = (r["trader"], r["asset_class"])
        if r["status"] == "CLOSED":
            groups[k].append(r)
        else:
            open_counts[k] += 1
        ts = r["timestamp_entrada"] or ""
        if ts > last_signal.get(k, ""):
            last_signal[k] = ts

    profiles = []
    for k in set(groups) | set(open_counts):
        trader, asset = k
        st = _stats(groups.get(k, []))
        profiles.append({
            "trader": trader,
            "asset_class": asset,
            "asset_label": ASSET_CLASS_LABELS.get(asset, asset),
            "open": open_counts.get(k, 0),
            "last_signal_at": last_signal.get(k),
            **st,
        })
    profiles.sort(key=lambda p: (p["trader"], -(p["closed"] or 0)))
    _cache[key] = (time.time(), profiles)
    return profiles


def profile_for(trader: str, asset_class: str, conn=None) -> Optional[Dict[str, Any]]:
    for p in trader_profiles(conn):
        if p["trader"].lower() == str(trader).lower() and p["asset_class"] == asset_class:
            return p
    return None


def invalidate_cache() -> None:
    _cache.clear()
