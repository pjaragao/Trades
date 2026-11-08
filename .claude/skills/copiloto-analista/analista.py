#!/usr/bin/env python3
"""Histórico real de um analista do TradingFloors (src/lab/analyst_history.py) — skill copiloto-analista.

    python .claude/skills/copiloto-analista/analista.py Sanita --classe OPCAO
    python .claude/skills/copiloto-analista/analista.py "Artur Horta" --classe ACAO --desde 2026-01-01
    python .claude/skills/copiloto-analista/analista.py --ranking --classe OPCAO
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CLASSES = ["OPCAO", "ACAO", "FUTURO", "FOREX", "INDICE", "COMMODITY", "CRIPTO"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Estatística real de um analista (acerto, payoff, t, plano sugerido).")
    ap.add_argument("trader", nargs="?")
    ap.add_argument("--classe", choices=CLASSES)
    ap.add_argument("--desde", help="AAAA-MM-DD")
    ap.add_argument("--ranking", action="store_true", help="todos os analistas da classe, ordenados pelo t")
    ap.add_argument("--min", type=int, default=10, help="mínimo de operações no ranking")
    ap.add_argument("--db", help="banco do Copiloto (padrão: COPILOTO_DB ou database/app.db)")
    ap.add_argument("--sem-api", action="store_true", help="não buscar no TradingFloors quando o banco está vazio")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if not args.trader and not args.ranking:
        ap.error("informe o analista ou --ranking")

    from src.core import db
    from src.lab import analyst_history as ah

    if args.db:
        db.configure(Path(args.db))
    rows, source = ah.load_closed(use_api=not args.sem_api)
    if not rows:
        print(f"Sem histórico (fonte: {source}).")
        return 2
    if args.ranking:
        items = ah.ranking(rows, args.classe, args.min)
        if args.json:
            print(json.dumps(items, ensure_ascii=False, indent=2))
            return 0
        print(f"Fonte: {source} · {args.classe or 'todas as classes'} · mínimo {args.min} operações · ordenado pelo t")
        copy = {"yes": "sim", "partial": "em parte", "no": "não", "unknown": "?"}
        for s in items:
            print(f"  {s['trader']:<18} n={s['closed']:<4} acerto {ah._n(s['win_rate']):>5}%  médio {ah._n(s['avg_return_pct'], 2):>7}%  "
                  f"FL {ah._n(s['profit_factor'], 2):>5}  t={ah._n(s['t_stat'], 2):>5}  copiável: {copy[s['copyable']]}")
        return 0
    s = ah.summarize(rows, args.trader, args.classe, args.desde)
    if not s["closed"]:
        print(f"{args.trader}: nenhuma operação encerrada{' em ' + args.classe if args.classe else ''} (fonte: {source}).")
        return 2
    print(json.dumps(s, ensure_ascii=False, indent=2) if args.json else f"Fonte: {source}\n{ah.report(s)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
