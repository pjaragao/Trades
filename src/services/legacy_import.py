"""
Importa uma única vez o histórico do cache antigo (database/backtest_cache.db).

A API atual do TradingFloors já devolve quase todo o histórico pela tabela `trades`; o cache antigo
só acrescenta operações de opções antigas que sumiram de `opcoes_trades`. Linhas que já existem
(mesmo id, ou mesmo ativo+analista+lado no mesmo dia) são ignoradas para não duplicar.
"""
import json
import sqlite3
from pathlib import Path
from typing import Dict, Optional

from src.core.config import DATABASE_DIR, now_iso
from src.core.market_hours import to_brt
from src.integrations.tradingfloors import normalize_row

LEGACY_CACHE = DATABASE_DIR / "backtest_cache.db"


def import_legacy_cache(conn, path: Optional[Path] = None) -> Dict[str, int]:
    stats = {"read": 0, "imported": 0, "skipped": 0}
    path = path or LEGACY_CACHE
    if not Path(path).exists():
        return stats

    existing_ids = {r[0] for r in conn.execute("SELECT id FROM signals")}
    existing_ids |= {r[0] for r in conn.execute("SELECT trades_id FROM signals WHERE trades_id IS NOT NULL")}
    existing_ids |= {r[0] for r in conn.execute("SELECT j.value FROM signals s, json_each(s.linked_ids) j")}
    keys = set()
    for r in conn.execute("SELECT ticker, lower(trader), lado, timestamp_entrada FROM signals"):
        dt = to_brt(r[3])
        keys.add((r[0], r[1], r[2], dt.date().isoformat() if dt else None))

    src = sqlite3.connect(str(path))
    src.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in src.execute("SELECT * FROM historical_trades")]
    finally:
        src.close()

    now = now_iso()
    for raw in rows:
        stats["read"] += 1
        sig = normalize_row({**raw, "trader_nome": raw.get("trader_nome")}, raw.get("source_table") or "trades")
        dt = to_brt(sig["timestamp_entrada"])
        key = (sig["ticker"], sig["trader"].lower(), sig["lado"], dt.date().isoformat() if dt else None)
        # Abertos no cache antigo e ausentes da API atual estão desatualizados: não importa.
        if raw["id"] in existing_ids or key in keys or sig["status"] == "OPEN":
            stats["skipped"] += 1
            continue
        keys.add(key)
        conn.execute(
            "INSERT INTO signals (id, source, trades_id, linked_ids, produto, tipo_ativo, asset_class, ticker, underlying, "
            "opcao_tipo, strike, expiration, trader, lado, quantidade, preco_entrada, preco_saida, pnl_realizado, pnl_pontos, "
            "timestamp_entrada, timestamp_saida, status, first_seen_at, closed_seen_at, updated_at, is_baseline, raw_json) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                raw["id"], "legacy", None, "[]", sig["produto"], sig["tipo_ativo"], sig["asset_class"], sig["ticker"],
                sig["underlying"], sig["opcao_tipo"], sig["strike"], sig["expiration"], sig["trader"], sig["lado"],
                sig["quantidade"], sig["preco_entrada"], sig["preco_saida"], sig["pnl_realizado"], sig["pnl_pontos"],
                sig["timestamp_entrada"], sig["timestamp_saida"], sig["status"], now,
                now if sig["status"] == "CLOSED" else None, now, 1, json.dumps([raw], ensure_ascii=False, default=str),
            ),
        )
        stats["imported"] += 1
    return stats
