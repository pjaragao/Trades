#!/usr/bin/env python3
"""Tamanho pelo risco + checagem pré-trade (src/services/pretrade.py) — skill copiloto-risco.

    python .claude/skills/copiloto-risco/risco.py PETR4 --entrada 38.50 --stop 37.20 --alvo 41
    python .claude/skills/copiloto-risco/risco.py PETRK420 --entrada 0.85 --stop 0.50 --alvo 1.30 --trader Sanita
    python .claude/skills/copiloto-risco/risco.py PETR4 --entrada 38.50 --stop 37.20 --risco-max 50 --conta paper
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Quantidade pelo risco e APROVADO/BLOQUEADO antes de copiar um trade.")
    ap.add_argument("ticker")
    ap.add_argument("--lado", choices=["compra", "venda"], default="compra")
    ap.add_argument("--entrada", type=float, required=True)
    ap.add_argument("--stop", type=float)
    ap.add_argument("--alvo", type=float)
    ap.add_argument("--stop-pct", type=float, help="stop em %% da entrada, se não houver --stop")
    ap.add_argument("--alvo-pct", type=float, help="alvo em %% da entrada, se não houver --alvo")
    ap.add_argument("--trader", help="usa o acerto histórico do analista na conferência do R:R")
    ap.add_argument("--vencimento", help="opções: AAAA-MM-DD (padrão: decodificado do ticker)")
    ap.add_argument("--conta", choices=["real", "paper"], default="real")
    ap.add_argument("--limites", help="JSON de limites (padrão: limites.json desta skill)")
    ap.add_argument("--risco-max", type=float, help="sobrescreve risco_max_trade (R$)")
    ap.add_argument("--perda-dia", type=float, help="sobrescreve perda_max_dia (R$)")
    ap.add_argument("--db", help="banco do Copiloto (padrão: COPILOTO_DB ou database/app.db)")
    ap.add_argument("--sem-api", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    from src.core import db
    from src.lab import signal_review as sr

    if args.db:
        db.configure(Path(args.db))
    limits = sr.load_limits(args.limites)
    if args.risco_max is not None:
        limits["risco_max_trade"] = args.risco_max
    if args.perda_dia is not None:
        limits["perda_max_dia"] = args.perda_dia
    sig = sr.manual_signal(args.ticker, "SELL" if args.lado == "venda" else "BUY", args.entrada, args.trader,
                           expiration=args.vencimento)
    rv = sr.review(sig, entry=args.entrada, stop=args.stop, target=args.alvo, stop_pct=args.stop_pct,
                   target_pct=args.alvo_pct, simulate=False, limits=limits, account=args.conta,
                   use_api=not args.sem_api)
    if args.json:
        print(json.dumps({k: rv.get(k) for k in ("check", "ticket", "analyst")}, ensure_ascii=False, indent=2, default=str))
    else:
        from src.services import pretrade

        print(pretrade.report(rv["check"]))
        if rv.get("ticket"):
            print("\nBoleta (copiar no Home Broker):\n" + rv["ticket"]["copy_text"])
            for w in rv["ticket"]["warnings"]:
                print(f"! {w}")
    return 0 if rv["check"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
