"""
Gerador de Relatórios Quantitativos da Fábrica de Robôs & Matriz de Regimes de Mercado.
Salva os resultados consolidados em JSON e Markdown para consulta imediata e consumo pela Web UI / CLI.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from robo_lab.backtester.optimizer import run_arena_analysis
from robo_lab.config import REPORTS_DIR, SYMBOL_LABELS
from robo_lab.ingestion.youtube_channel_miner import build_channel_strategy_catalog


def generate_full_research_report(
    symbols: List[str] = None,
    timeframes: List[str] = None,
    start_date: str = "2020-01-01",
    max_param_combos: int = 6,
) -> Dict[str, Any]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    syms = symbols or ["^BVSP", "VALE3.SA", "PETR4.SA"]
    tfs = timeframes or ["5m", "15m", "60m", "1d", "1wk"]

    channel_catalog = build_channel_strategy_catalog("norisknogainoficial")

    arena_by_symbol: Dict[str, Any] = {}
    for sym in syms:
        print(f"[Robo Lab] Executando exaustão de filtros/parâmetros para {sym} nos timeframes {tfs}...")
        arena_by_symbol[sym] = run_arena_analysis(
            symbol=sym,
            timeframes=tfs,
            start_date=start_date,
            max_param_combos=max_param_combos,
        )

    full_payload = {
        "generated_at": datetime.now().isoformat(),
        "channel_catalog": channel_catalog,
        "symbols_analyzed": syms,
        "timeframes_analyzed": tfs,
        "arena_by_symbol": arena_by_symbol,
    }

    json_path = REPORTS_DIR / "norisknogain_full_arena.json"
    json_path.write_text(json.dumps(full_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    md_text = _build_markdown_summary(full_payload)
    md_path = REPORTS_DIR / "RELATORIO_ROBOS_NORISKNOGAIN.md"
    md_path.write_text(md_text, encoding="utf-8")

    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
        "payload": full_payload,
    }


def _build_markdown_summary(data: Dict[str, Any]) -> str:
    cat = data.get("channel_catalog", {})
    lines = [
        "# Relatório Quantitativo — Fábrica de Robôs & Regimes de Mercado (B3 / Ibovespa)",
        "",
        f"- **Canal Analisado**: [{cat.get('channel_name')}]({cat.get('channel_url')})",
        f"- **Total de Vídeos Varridos no Canal**: **{cat.get('total_videos_scanned', 0)} vídeos** ({cat.get('strategy_videos_identified', 0)} vídeos com conteúdo operacional/robôs)",
        f"- **Transcrições Completas Extraídas e Mineradas**: **{cat.get('transcripts_extracted_count', 0)} vídeos-chave**",
        f"- **Robôs Programados e Testados**: **{len(cat.get('programmed_bots', []))} robôs paramétricos**",
        "",
        "---",
        "",
        "## 1. Famílias de Estratégias Identificadas no Canal (`@norisknogainoficial`)",
        "",
        "| Família Operacional | Qtd. Vídeos | Exemplos de Vídeos do Canal |",
        "|---|---:|---|",
    ]

    for fam in cat.get("families_breakdown", []):
        samples = "; ".join(fam.get("sample_titles", [])[:2])
        lines.append(f"| **{fam['family']}** | {fam['videos_count']} | {samples} |")

    lines.extend([
        "",
        "---",
        "",
        "## 2. Como Operar a Estratégia de Mês de Alta SEM Saber que o Mês é de Alta (Detector Causal)",
        "",
        "O problema clássico de classificar meses como **Mês de Alta**, **Mês Lateral** ou **Mês de Baixa** é o *Look-Ahead Bias*: no dia 5 do mês, você ainda não sabe como o mês vai fechar.",
        "",
        "Para resolver isso na prática, o módulo `robo_lab/regime/market_sentiment.py` implementa uma arquitetura em **duas camadas**:",
        "1. **Mapeamento de Especialidade (Ex-Post)**: Identifica o DNA de cada robô (quais setups ganham dinheiro quando o mercado sobe, cai ou anda de lado).",
        "2. **Detector Causal em Tempo Real (`causal_regime` em $t-1$)**: Antes de cada pregão/barra $t$, avalia **exclusivamente o passado até $t-1$**:",
        "   - **Eficiência Direcional de Kaufman ($ER_{10}$)** e **ADX(14)**: Se $ER_{10} < 0.22$ e $ADX < 22$ (ou $ADX < 16.5$), o mercado está **LATERAL (De Lado)** $\\to$ o sistema desliga robôs de tendência e ativa especialistas de oscilação (**Cash Bands, Keltner Médio, VWAP Gradiente Linear, Bollinger**).",
        "   - **Score de Estrutura Direcional ($EMA_{20} > EMA_{50} > EMA_{200}$ + Inclinação + Momentum 5/15 barras)**: Quando o mercado rompe a inércia com $ER_{10} \\ge 0.22$ e estrutura positiva, classifica como **CAUSAL ALTA** $\\to$ ativa especialistas direcionais/pullback (**IFR2 Stormer, Alinhamento 3 Médias, Setup 123 Fibo, 2MV Padrão, HiLo+MACD**).",
        "   - Quando a estrutura é negativa com expansão de volatilidade, classifica como **CAUSAL BAIXA** $\\to$ ativa robôs calibrados na ponta vendedora ou filtros defensivos.",
        "",
        "---",
        "",
    ])

    for sym, sym_data in data.get("arena_by_symbol", {}).items():
        sym_label = SYMBOL_LABELS.get(sym, sym)
        lines.append(f"## 3. Resultados Exaustivos — {sym_label} (`{sym}`)")
        lines.append("")

        for tf, tf_data in sym_data.get("by_timeframe", {}).items():
            meta = tf_data["meta_causal_selector"]["comparison"]
            c_spec = tf_data["meta_causal_selector"]["causal_specialists"]

            lines.append(f"### Timeframe `{tf}` ({tf_data['bars_count']} barras: `{tf_data['period_start']}` a `{tf_data['period_end']}`)")
            lines.append("")
            lines.append("#### Comparativo: Robô Fixo vs. Seletor Causal (Sem Saber o Futuro) vs. Oráculo")
            lines.append("")
            lines.append("| Abordagem | Retorno Líquido (%) | Win Rate (%) | Profit Factor | Max Drawdown (%) | Nº Trades |")
            lines.append("|---|---:|---:|---:|---:|---:|")

            bh = meta["buy_and_hold_return_pct"]
            s_bot = meta["best_single_bot"]
            s_m = s_bot["metrics"]
            c_m = meta["causal_adaptive_selector"]["metrics"]
            o_m = meta["expost_oracle_selector"]["metrics"]

            lines.append(f"| **Buy & Hold ({sym})** | {bh:+.2f}% | — | — | — | 1 |")
            lines.append(f"| **Melhor Robô Único Fixo ({s_bot['bot_id']} - {s_bot['bot_name']})** | {s_m['total_return_pct']:+.2f}% | {s_m['win_rate_pct']:.1f}% | {s_m['profit_factor']:.2f} | {s_m['max_drawdown_pct']:.2f}% | {s_m['trades']} |")
            lines.append(f"| **Meta-Seletor Causal (SEM saber o futuro — Tempo Real)** | **{c_m['total_return_pct']:+.2f}%** | **{c_m['win_rate_pct']:.1f}%** | **{c_m['profit_factor']:.2f}** | **{c_m['max_drawdown_pct']:.2f}%** | {c_m['trades']} |")
            lines.append(f"| *Oráculo Ex-Post (Sabendo o Mês de antemão)* | *{o_m['total_return_pct']:+.2f}%* | *{o_m['win_rate_pct']:.1f}%* | *{o_m['profit_factor']:.2f}* | *{o_m['max_drawdown_pct']:.2f}%* | {o_m['trades']} |")
            lines.append("")

            lines.append("#### Qual Robô Ligar em Cada Sentimento Causal de Mercado (`" + tf + "`)")
            lines.append("")
            lines.append("| Estado Causal (Tempo Real) | Robô Campeão | Filtros Otimizados | Parâmetros Otimizados | Retorno no Regime | Win Rate | Profit Factor |")
            lines.append("|---|---|---|---|---:|---:|---:|")
            for reg in ("ALTA", "LATERAL", "BAIXA"):
                sp = c_spec[reg]
                rm = sp["regime_metrics"]
                lines.append(
                    f"| **{reg}** | `{sp['bot_id']}` {sp['bot_name']} | `{sp['filter_label']}` | `{json.dumps(sp['params'])}` | "
                    f"**{rm.get('total_return_pct', 0):+.2f}%** | {rm.get('win_rate_pct', 0):.1f}% | {rm.get('profit_factor', 0):.2f} |"
                )
            lines.append("")

            lines.append("#### Campeões por Perfil do Dia da Bolsa (Volume & Direção)")
            lines.append("")
            lines.append("| Condição do Dia / Barra | Robô Mais Adaptado | Filtro Ideal | Retorno no Perfil | Win Rate | Profit Factor |")
            lines.append("|---|---|---|---:|---:|---:|")
            for vp, vc in tf_data.get("champions_by_volume_profile", {}).items():
                m = vc["metrics"]
                lines.append(f"| **{vp}** | `{vc['bot_id']}` {vc['bot_name']} | `{vc['filter_label']}` | {m.get('total_return_pct', 0):+.2f}% | {m.get('win_rate_pct', 0):.1f}% | {m.get('profit_factor', 0):.2f} |")
            for dd, dc in tf_data.get("champions_by_day_direction", {}).items():
                m = dc["metrics"]
                lines.append(f"| **{dd}** | `{dc['bot_id']}` {dc['bot_name']} | `{dc['filter_label']}` | {m.get('total_return_pct', 0):+.2f}% | {m.get('win_rate_pct', 0):.1f}% | {m.get('profit_factor', 0):.2f} |")
            lines.append("")

            lines.append("#### Ranking Completo dos 10 Robôs Após Exaustão de Parâmetros e Filtros (`" + tf + "`)")
            lines.append("")
            lines.append("| # | ID | Robô | Família | Retorno Base | Retorno Otimizado | Win Rate | PF | Max DD | Melhor Filtro Encontrado |")
            lines.append("|---:|---|---|---|---:|---:|---:|---:|---:|---|")
            for idx, b in enumerate(tf_data["bots_ranking"], 1):
                base_r = b["baseline"]["summary"]["total_return_pct"]
                opt_s = b["best_overall"]["summary"]
                lines.append(
                    f"| {idx} | `{b['bot_id']}` | {b['bot_name']} | `{b['family']}` | {base_r:+.2f}% | "
                    f"**{opt_s['total_return_pct']:+.2f}%** | {opt_s['win_rate_pct']:.1f}% | {opt_s['profit_factor']:.2f} | "
                    f"{opt_s['max_drawdown_pct']:.2f}% | `{b['best_overall']['filter_label']}` |"
                )
            lines.append("")

    return "\n".join(lines)
