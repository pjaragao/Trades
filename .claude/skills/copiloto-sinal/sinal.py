#!/usr/bin/env python3
"""Revisão completa de um sinal antes de copiar (src/lab/signal_review.py) — skill copiloto-sinal.

    python .claude/skills/copiloto-sinal/sinal.py --abertos                 # sinais abertos dos analistas seguidos
    python .claude/skills/copiloto-sinal/sinal.py --id 1a2b3c               # revisão de um sinal (id ou prefixo)
    python .claude/skills/copiloto-sinal/sinal.py --id 1a2b3c --entrada 0.92 --stop 0.60
    python .claude/skills/copiloto-sinal/sinal.py PETR4 --lado compra --entrada 38.50 --trader "Artur Horta"
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Histórico do analista + Máquina do Tempo + risco + boleta para um sinal.")
    ap.add_argument("ticker", nargs="?", help="sinal manual (sem --id)")
    ap.add_argument("--abertos", action="store_true", help="lista os sinais abertos")
    ap.add_argument("--todos", action="store_true", help="com --abertos: inclui analistas/classes não seguidos")
    ap.add_argument("--id", help="id do sinal (ou o começo dele)")
    ap.add_argument("--lado", choices=["compra", "venda"], default="compra")
    ap.add_argument("--trader")
    ap.add_argument("--entrada", type=float, help="minha entrada (padrão: preço atual do sinal)")
    ap.add_argument("--stop", type=float)
    ap.add_argument("--alvo", type=float)
    ap.add_argument("--stop-pct", type=float)
    ap.add_argument("--alvo-pct", type=float)
    ap.add_argument("--strike", type=float)
    ap.add_argument("--vencimento")
    ap.add_argument("--subjacente", type=float)
    ap.add_argument("--modo", choices=["swing", "intraday"], default="swing")
    ap.add_argument("--dias", type=int)
    ap.add_argument("--hora")
    ap.add_argument("--replays", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=19)
    ap.add_argument("--sem-simulacao", action="store_true")
    ap.add_argument("--conta", choices=["real", "paper"], default="real")
    ap.add_argument("--limites", help="JSON de limites (padrão: .claude/skills/copiloto-risco/limites.json)")
    ap.add_argument("--db", help="banco do Copiloto (padrão: COPILOTO_DB ou database/app.db)")
    ap.add_argument("--sem-api", action="store_true", help="não consultar o TradingFloors")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    from src.core import db
    from src.core.config import get_prefs
    from src.core.market_hours import to_brt
    from src.lab import signal_review as sr

    if args.db:
        db.configure(Path(args.db))
    prefs = get_prefs()

    if args.abertos:
        sigs, source = sr.open_signals(prefs, followed_only=not args.todos, use_api=not args.sem_api)
        if args.json:
            print(json.dumps(sigs, ensure_ascii=False, indent=2, default=str))
            return 0
        print(f"{len(sigs)} sinais abertos ({'todos' if args.todos else 'analistas/classes seguidos'}; fonte: {source})")
        for s in sigs:
            when = to_brt(s.get("timestamp_entrada"))
            atual = f" · atual {s['preco_atual']:.2f}" if s.get("preco_atual") else ""
            line = (f"  {str(s['id'])[:8]}  {when.strftime('%d/%m') if when else '--/--'} {s.get('trader') or '—':<14} "
                    f"{'C' if s['lado'] == 'BUY' else 'V'} {s['ticker']:<10} entrada {s.get('preco_entrada') or 0:.2f}{atual}")
            print(line.replace(".", ","))
        return 0

    if args.id:
        sig = sr.find_signal(args.id, prefs, use_api=not args.sem_api)
        if not sig:
            print(f"Sinal {args.id} não encontrado (nem no banco nem entre os abertos do TradingFloors).")
            return 2
        if args.strike:
            sig["strike"] = args.strike
        if args.vencimento:
            sig["expiration"] = args.vencimento
    elif args.ticker:
        if not args.entrada:
            ap.error("sinal manual precisa de --entrada")
        sig = sr.manual_signal(args.ticker, "SELL" if args.lado == "venda" else "BUY", args.entrada, args.trader,
                               args.strike, args.vencimento)
    else:
        ap.error("use --abertos, --id ou informe um ticker")

    rv = sr.review(sig, entry=args.entrada, stop=args.stop, target=args.alvo, stop_pct=args.stop_pct,
                   target_pct=args.alvo_pct, mode=args.modo, horizon=args.dias, entry_time=args.hora,
                   replays=args.replays, seed=args.seed, simulate=not args.sem_simulacao,
                   limits=sr.load_limits(args.limites), account=args.conta, spot=args.subjacente,
                   use_api=not args.sem_api)
    print(json.dumps(rv, ensure_ascii=False, indent=2, default=str) if args.json else sr.report(rv))
    return 0 if rv["check"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
