"""
Gerador de Relatórios Quantitativos da Fábrica de Robôs & Matriz de Regimes de Mercado.
Salva os resultados consolidados em JSON e Markdown para consulta imediata e consumo pela Web UI / CLI.
Inclui métricas específicas de Contratos Futuros da B3 (Pontos Líquidos e R$/Contrato para WIN$N e WDO$N).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from robo_lab.backtester.optimizer import run_arena_analysis
from robo_lab.config import FUTURES_SPECS, REPORTS_DIR, SYMBOL_LABELS
from robo_lab.ingestion.youtube_channel_miner import build_channel_strategy_catalog


def generate_full_research_report(
    symbols: List[str] = None,
    timeframes: List[str] = None,
    start_date: str = "2020-01-01",
    max_param_combos: int = 6,
) -> Dict[str, Any]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    from robo_lab.data_feed import MultiTimeframeDataFeed
    _feed = MultiTimeframeDataFeed()
    syms = [_feed.normalize_symbol(s) for s in (symbols or ["^BVSP", "VALE3.SA", "PETR4.SA"])]
    tfs = timeframes or ["5m", "15m", "60m", "1d", "1wk"]

    channel_catalog = build_channel_strategy_catalog("norisknogainoficial")

    json_path = REPORTS_DIR / "norisknogain_full_arena.json"
    existing_arena: Dict[str, Any] = {}
    if json_path.exists():
        try:
            old_data = json.loads(json_path.read_text(encoding="utf-8"))
            existing_arena = {k: v for k, v in old_data.get("arena_by_symbol", {}).items() if k not in ("WIN", "WDO")}
        except Exception:
            existing_arena = {}

    arena_by_symbol: Dict[str, Any] = dict(existing_arena)
    current_run_arena: Dict[str, Any] = {}

    for sym in syms:
        print(f"[Robo Lab] Executando exaustão de filtros/parâmetros para {sym} nos timeframes {tfs}...")
        sym_res = run_arena_analysis(
            symbol=sym,
            timeframes=tfs,
            start_date=start_date,
            max_param_combos=max_param_combos,
        )
        current_run_arena[sym] = sym_res
        if sym in arena_by_symbol:
            merged_tf = dict(arena_by_symbol[sym].get("by_timeframe", {}))
            merged_tf.update(sym_res.get("by_timeframe", {}))
            arena_by_symbol[sym]["by_timeframe"] = merged_tf
            arena_by_symbol[sym]["timeframes_evaluated"] = list(merged_tf.keys())
        else:
            arena_by_symbol[sym] = sym_res

    all_tfs = []
    for s_data in arena_by_symbol.values():
        for t_code in s_data.get("by_timeframe", {}).keys():
            if t_code not in all_tfs:
                all_tfs.append(t_code)

    full_payload = {
        "generated_at": datetime.now().isoformat(),
        "channel_catalog": channel_catalog,
        "symbols_analyzed": list(arena_by_symbol.keys()),
        "timeframes_analyzed": all_tfs,
        "arena_by_symbol": arena_by_symbol,
    }

    json_path.write_text(json.dumps(full_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    md_text = _build_markdown_summary(full_payload)
    md_path = REPORTS_DIR / "RELATORIO_ROBOS_NORISKNOGAIN.md"
    md_path.write_text(md_text, encoding="utf-8")

    # Se rodou WIN$N ou WDO$N, salva também o relatório dedicado de Day Trade em Futuros
    if any(s in ("WIN$N", "WDO$N") for s in syms):
        fut_payload = {
            "generated_at": datetime.now().isoformat(),
            "channel_catalog": channel_catalog,
            "symbols_analyzed": [s for s in syms if s in current_run_arena],
            "timeframes_analyzed": tfs,
            "arena_by_symbol": {s: current_run_arena[s] for s in syms if s in current_run_arena},
        }
        fut_md = _build_markdown_summary(fut_payload, title="Relatório Day Trade Curto — Mini-Índice (WIN$N) & Mini-Dólar (WDO$N)")
        fut_path = REPORTS_DIR / "RELATORIO_DAYTRADE_INDICE_DOLAR.md"
        fut_path.write_text(fut_md, encoding="utf-8")

    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
        "payload": full_payload,
    }


def _build_markdown_summary(data: Dict[str, Any], title: str = "Relatório Quantitativo — Fábrica de Robôs & Regimes de Mercado (B3 / Ibovespa)") -> str:
    cat = data.get("channel_catalog", {})
    lines = [
        f"# {title}",
        "",
        f"- **Canal Analisado**: [{cat.get('channel_name')}]({cat.get('channel_url')})",
        f"- **Total de Vídeos Varridos no Canal**: **{cat.get('total_videos_scanned', 0)} vídeos** ({cat.get('strategy_videos_identified', 0)} vídeos com conteúdo operacional/robôs)",
        f"- **Transcrições Completas Extraídas e Mineradas**: **{cat.get('transcripts_extracted_count', 0)} vídeos-chave**",
        f"- **Robôs Programados e Testados**: **{len(cat.get('programmed_bots', []))} robôs paramétricos**",
        "",
        "---",
        "",
    ]

    for sym, sym_data in data.get("arena_by_symbol", {}).items():
        sym_label = SYMBOL_LABELS.get(sym, sym)
        is_fut = sym in FUTURES_SPECS
        lines.append(f"## Resultados Exaustivos — {sym_label} (`{sym}`)")
        if is_fut:
            f_spec = FUTURES_SPECS[sym]
            lines.append(
                f"> **Especificação B3 `{sym}`**: Tick mínimo = `{f_spec['tick_size']} pts` | "
                f"Valor do ponto = `R$ {f_spec['point_value_brl']:.2f}/pt` por mini-contrato | "
                f"Zeragem compulsória de fim de pregão (Day Trade Flat) ativa."
            )
        lines.append("")

        for tf, tf_data in sym_data.get("by_timeframe", {}).items():
            meta = tf_data["meta_causal_selector"]["comparison"]
            c_spec = tf_data["meta_causal_selector"]["causal_specialists"]

            lines.append(f"### Timeframe `{tf}` ({tf_data['bars_count']} barras: `{tf_data['period_start']}` a `{tf_data['period_end']}`)")
            lines.append("")
            lines.append("#### Comparativo: Robô Fixo vs. Seletor Causal (Sem Saber o Futuro) vs. Oráculo")
            lines.append("")

            bh = meta["buy_and_hold_return_pct"]
            s_bot = meta["best_single_bot"]
            s_m = s_bot["metrics"]
            c_m = meta["causal_adaptive_selector"]["metrics"]
            o_m = meta["expost_oracle_selector"]["metrics"]

            if is_fut:
                lines.append("| Abordagem | Pontos Líquidos | Lucro (1 Mini-Contrato) | Retorno Capital (%) | Win Rate (%) | Profit Factor | Max DD (%) | Nº Trades |")
                lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
                lines.append(f"| **Variação do Ativo ({sym})** | — | — | {bh:+.2f}% | — | — | — | 1 |")
                lines.append(
                    f"| **Melhor Robô Único Fixo ({s_bot['bot_id']} - {s_bot['bot_name']})** | "
                    f"**{s_m.get('total_points', 0):+.1f} pts** | R$ {s_m.get('pnl_1_contract_brl', 0):+,.2f} | "
                    f"{s_m['total_return_pct']:+.2f}% | {s_m['win_rate_pct']:.1f}% | {s_m['profit_factor']:.2f} | {s_m['max_drawdown_pct']:.2f}% | {s_m['trades']} |"
                )
                lines.append(
                    f"| **Meta-Seletor Causal (SEM saber o futuro — Tempo Real)** | "
                    f"**{c_m.get('total_points', 0):+.1f} pts** | **R$ {c_m.get('pnl_1_contract_brl', 0):+,.2f}** | "
                    f"**{c_m['total_return_pct']:+.2f}%** | **{c_m['win_rate_pct']:.1f}%** | **{c_m['profit_factor']:.2f}** | **{c_m['max_drawdown_pct']:.2f}%** | {c_m['trades']} |"
                )
                lines.append(
                    f"| *Oráculo Ex-Post (Sabendo o Mês de antemão)* | "
                    f"*{o_m.get('total_points', 0):+.1f} pts* | *R$ {o_m.get('pnl_1_contract_brl', 0):+,.2f}* | "
                    f"*{o_m['total_return_pct']:+.2f}%* | *{o_m['win_rate_pct']:.1f}%* | *{o_m['profit_factor']:.2f}* | *{o_m['max_drawdown_pct']:.2f}%* | {o_m['trades']} |"
                )
            else:
                lines.append("| Abordagem | Retorno Líquido (%) | Win Rate (%) | Profit Factor | Max Drawdown (%) | Nº Trades |")
                lines.append("|---|---:|---:|---:|---:|---:|")
                lines.append(f"| **Buy & Hold ({sym})** | {bh:+.2f}% | — | — | — | 1 |")
                lines.append(f"| **Melhor Robô Único Fixo ({s_bot['bot_id']} - {s_bot['bot_name']})** | {s_m['total_return_pct']:+.2f}% | {s_m['win_rate_pct']:.1f}% | {s_m['profit_factor']:.2f} | {s_m['max_drawdown_pct']:.2f}% | {s_m['trades']} |")
                lines.append(f"| **Meta-Seletor Causal (SEM saber o futuro — Tempo Real)** | **{c_m['total_return_pct']:+.2f}%** | **{c_m['win_rate_pct']:.1f}%** | **{c_m['profit_factor']:.2f}** | **{c_m['max_drawdown_pct']:.2f}%** | {c_m['trades']} |")
                lines.append(f"| *Oráculo Ex-Post (Sabendo o Mês de antemão)* | *{o_m['total_return_pct']:+.2f}%* | *{o_m['win_rate_pct']:.1f}%* | *{o_m['profit_factor']:.2f}* | *{o_m['max_drawdown_pct']:.2f}%* | {o_m['trades']} |")
            lines.append("")

            lines.append("#### Qual Robô Ligar em Cada Sentimento Causal de Mercado (`" + tf + "`)")
            lines.append("")
            if is_fut:
                lines.append("| Estado Causal (Tempo Real) | Robô Campeão | Filtros Otimizados | Parâmetros Otimizados | Pontos no Regime | Lucro 1 Contr. | Win Rate | PF |")
                lines.append("|---|---|---|---|---:|---:|---:|---:|")
                for reg in ("ALTA", "LATERAL", "BAIXA"):
                    sp = c_spec[reg]
                    rm = sp["regime_metrics"]
                    lines.append(
                        f"| **{reg}** | `{sp['bot_id']}` {sp['bot_name']} | `{sp['filter_label']}` | `{json.dumps(sp['params'])}` | "
                        f"**{rm.get('total_points', 0):+.1f} pts** | R$ {rm.get('pnl_1_contract_brl', 0):+,.2f} | {rm.get('win_rate_pct', 0):.1f}% | {rm.get('profit_factor', 0):.2f} |"
                    )
            else:
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
            if is_fut:
                lines.append("| Condição do Dia / Barra | Robô Mais Adaptado | Filtro Ideal | Pontos no Perfil | Lucro 1 Contr. | Win Rate | PF |")
                lines.append("|---|---|---|---:|---:|---:|---:|")
                for vp, vc in tf_data.get("champions_by_volume_profile", {}).items():
                    m = vc["metrics"]
                    lines.append(f"| **{vp}** | `{vc['bot_id']}` {vc['bot_name']} | `{vc['filter_label']}` | {m.get('total_points', 0):+.1f} pts | R$ {m.get('pnl_1_contract_brl', 0):+,.2f} | {m.get('win_rate_pct', 0):.1f}% | {m.get('profit_factor', 0):.2f} |")
                for dd, dc in tf_data.get("champions_by_day_direction", {}).items():
                    m = dc["metrics"]
                    lines.append(f"| **{dd}** | `{dc['bot_id']}` {dc['bot_name']} | `{dc['filter_label']}` | {m.get('total_points', 0):+.1f} pts | R$ {m.get('pnl_1_contract_brl', 0):+,.2f} | {m.get('win_rate_pct', 0):.1f}% | {m.get('profit_factor', 0):.2f} |")
            else:
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
            if is_fut:
                lines.append("| # | ID | Robô | Família | Pts Base (Cru) | Pts Otimizado | Lucro 1 Contr. | Retorno (%) | WR (%) | PF | Max DD | Melhor Filtro Encontrado |")
                lines.append("|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
                for idx, b in enumerate(tf_data["bots_ranking"], 1):
                    base_pts = b["baseline"]["summary"].get("total_points", 0.0)
                    opt_s = b["best_overall"]["summary"]
                    lines.append(
                        f"| {idx} | `{b['bot_id']}` | {b['bot_name']} | `{b['family']}` | {base_pts:+.1f} pts | "
                        f"**{opt_s.get('total_points', 0):+.1f} pts** | **R$ {opt_s.get('pnl_1_contract_brl', 0):+,.2f}** | "
                        f"{opt_s['total_return_pct']:+.2f}% | {opt_s['win_rate_pct']:.1f}% | {opt_s['profit_factor']:.2f} | "
                        f"{opt_s['max_drawdown_pct']:.2f}% | `{b['best_overall']['filter_label']}` |"
                    )
            else:
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
