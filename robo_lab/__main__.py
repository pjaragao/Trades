"""
CLI Principal do Módulo Robo Lab.
Exemplos de uso:
  python -m robo_lab catalog
  python -m robo_lab arena --symbols ^BVSP VALE3.SA PETR4.SA --timeframes 5m 15m 60m 1d 1wk
  python -m robo_lab export-mt5 --bot NRNG-001 --symbol WIN$N --timeframe 15m
"""

import argparse
import json
import sys

from robo_lab.backtester.reports import generate_full_research_report
from robo_lab.ingestion.youtube_channel_miner import build_channel_strategy_catalog
from robo_lab.strategies.mt5_exporter import generate_mql5_ea_code


def main():
    parser = argparse.ArgumentParser(description="Robo Lab — Fábrica de Robôs & Regimes de Mercado (B3 / MT5)")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("catalog", help="Constrói e exibe o catálogo de vídeos e robôs do canal @norisknogainoficial")

    p_arena = sub.add_parser("arena", help="Executa backtest multi-timeframe com exaustão de filtros e seletor causal")
    p_arena.add_argument("--symbols", nargs="+", default=["^BVSP", "VALE3.SA", "PETR4.SA"])
    p_arena.add_argument("--timeframes", nargs="+", default=["5m", "15m", "60m", "1d", "1wk"])
    p_arena.add_argument("--start", default="2020-01-01")
    p_arena.add_argument("--max-combos", type=int, default=6)

    p_mt5 = sub.add_parser("export-mt5", help="Gera código MQL5 (.mq5) para um robô com detector causal embutido")
    p_mt5.add_argument("--bot", default="NRNG-001")
    p_mt5.add_argument("--symbol", default="WIN$N")
    p_mt5.add_argument("--timeframe", default="15m")

    args = parser.parse_args()

    if args.cmd == "catalog":
        cat = build_channel_strategy_catalog("norisknogainoficial")
        print(f"Canal: {cat.get('channel_name')} ({cat.get('total_videos_scanned')} vídeos, {cat.get('strategy_videos_identified')} de estratégias)")
        for f in cat.get("families_breakdown", []):
            print(f" - {f['family']}: {f['videos_count']} vídeos")
    elif args.cmd == "export-mt5":
        code = generate_mql5_ea_code(args.bot, args.symbol, args.timeframe)
        print(code)
    else:
        syms = getattr(args, "symbols", ["^BVSP", "VALE3.SA", "PETR4.SA"])
        tfs = getattr(args, "timeframes", ["5m", "15m", "60m", "1d", "1wk"])
        start = getattr(args, "start", "2020-01-01")
        combos = getattr(args, "max_combos", 6)
        res = generate_full_research_report(symbols=syms, timeframes=tfs, start_date=start, max_param_combos=combos)
        print(f"\n[OK] Relatório JSON salvo em: {res['json_path']}")
        print(f"[OK] Relatório Markdown salvo em: {res['md_path']}")


if __name__ == "__main__":
    main()
