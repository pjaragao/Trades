#!/usr/bin/env python3
"""CLI da Máquina do Tempo (src/lab/timemachine.py) — skill copiloto-maquina-do-tempo.

    python .claude/skills/copiloto-maquina-do-tempo/maquina.py PETR4 --entrada 38.50
    python .claude/skills/copiloto-maquina-do-tempo/maquina.py PETR4 --entrada 38.50 --stop 37.20 --alvo 41
    python .claude/skills/copiloto-maquina-do-tempo/maquina.py PETR4 --lado venda --entrada 38.5 --modo intraday --hora 11:30
    python .claude/skills/copiloto-maquina-do-tempo/maquina.py PETRK420 --entrada 0.85 --strike 42 --alvo-pct 50
    python .claude/skills/copiloto-maquina-do-tempo/maquina.py WINZ26 --entrada 131000 --stop 130500 --csv win_5m.csv --modo intraday --hora 10:30
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def selic() -> float:
    try:
        from src.lab import rates

        return float(rates.get_rates()["selic"]["value"])
    except Exception:  # noqa: BLE001 — sem rede/banco: o padrão do módulo
        return 15.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Replays Monte Carlo de um trade na B3 (alvo primeiro x stop primeiro).")
    ap.add_argument("ticker")
    ap.add_argument("--lado", choices=["compra", "venda"], default="compra")
    ap.add_argument("--entrada", type=float, required=True, help="preço de entrada (prêmio, se opção)")
    ap.add_argument("--stop", type=float)
    ap.add_argument("--alvo", type=float)
    ap.add_argument("--alvo-r", type=float, default=2.0, help="alvo em múltiplos do risco quando --alvo/--alvo-pct faltam (padrão 2)")
    ap.add_argument("--stop-pct", type=float, help="stop em %% da entrada (ex.: do histórico do analista)")
    ap.add_argument("--alvo-pct", type=float, help="alvo em %% da entrada")
    ap.add_argument("--stop-atr", type=float, help="stop em ATR14 (padrão 1,5 no swing, 0,5 no intraday)")
    ap.add_argument("--modo", choices=["swing", "intraday"], default="swing")
    ap.add_argument("--dias", type=int, help="horizonte em pregões no swing (padrão 10)")
    ap.add_argument("--hora", help="hora da entrada no intraday (HH:MM, Brasília)")
    ap.add_argument("--ate", help="zerar até (HH:MM); padrão 10 min antes do fechamento")
    ap.add_argument("--data", help="data do plano AAAA-MM-DD (padrão hoje); o histórico usa só pregões anteriores")
    ap.add_argument("--replays", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=19)
    ap.add_argument("--csv", help="barras de um CSV (export do MT5) em vez do Yahoo")
    ap.add_argument("--strike", type=float)
    ap.add_argument("--vencimento", help="AAAA-MM-DD (padrão: decodificado do ticker)")
    ap.add_argument("--tipo", choices=["call", "put"])
    ap.add_argument("--subjacente", type=float, help="preço atual do ativo-objeto (padrão: último do Yahoo)")
    ap.add_argument("--selic", type=float, help="Selic anual em %% (padrão: Banco Central)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    from src.core import b3_tickers
    from src.lab import timemachine as tm

    is_option = b3_tickers.asset_class(None, args.ticker) == "OPCAO"
    try:
        res = tm.run(
            ticker=args.ticker, side="SELL" if args.lado == "venda" else "BUY", entry=args.entrada,
            stop=args.stop, target=args.alvo, mode=args.modo, horizon=args.dias, entry_time=args.hora, until=args.ate,
            as_of=date.fromisoformat(args.data) if args.data else None,
            bars=tm.load_csv(args.csv) if args.csv else None, replays=args.replays, seed=args.seed,
            stop_atr=args.stop_atr, target_r=args.alvo_r, stop_pct=args.stop_pct, target_pct=args.alvo_pct,
            strike=args.strike, expiration=args.vencimento, option_kind=args.tipo, spot=args.subjacente,
            rate=(args.selic if args.selic is not None else selic()) if is_option else None,
        )
    except tm.TMError as exc:
        print(f"Máquina do Tempo: {exc}")
        return 2
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str) if args.json else tm.report(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
