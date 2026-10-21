"""
Script e Módulo de Teste de Estresse de Slippage e Custos para Day Trade na B3 (WIN$N e WDO$N).
Analisa a curva de degradação de cada estratégia e do Meta-Seletor Causal sob slippage de:
- 1 tick (condição normal de mercado)
- 2 ticks (+100% de custo/spread)
- 3 ticks (+200% de custo, típico de horários de maior fluxo)
- 4 ticks (+300% de custo)
- 5 ticks (+400% de custo, estresse severo / leilões / volatilidade atípica)

Calcula:
- Taxa de acerto real após corrosão de spread
- Pontos líquidos e PnL em R$ por mini-contrato
- Profit Factor sob estresse
- Slippage de Ruptura (Ponto de Break-Even em ticks)
"""

import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from robo_lab.backtester.engine import _compute_slice_metrics, run_bot_backtest
from robo_lab.config import FUTURES_SPECS, REPORTS_DIR
from robo_lab.data_feed import MultiTimeframeDataFeed
from robo_lab.regime.market_sentiment import enrich_indicators_and_regimes
from robo_lab.strategies.base_bot import FilterConfig
from robo_lab.strategies.bots_norisknogain import get_bot_by_id


def parse_filter_label(label: str) -> FilterConfig:
    cfg = FilterConfig()
    if not label or label == "sem_filtros_extras":
        return cfg
    for part in label.split("|"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            k, v = k.strip(), v.strip()
            if k == "trend":
                cfg.trend_filter = v
            elif k == "vol":
                cfg.volume_filter = v
            elif k == "atr":
                cfg.volatility_filter = v
            elif k == "sess":
                cfg.session_filter = v
            elif k == "side":
                cfg.side_mode = v
    return cfg


def run_slippage_stress_analysis(
    symbols: List[str] = None,
    timeframes: List[str] = None,
    slippage_levels: List[float] = None,
) -> Dict[str, Any]:
    feed = MultiTimeframeDataFeed()
    syms = symbols or ["WIN$N", "WDO$N"]
    tfs = timeframes or ["1m", "2m", "3m", "5m", "15m"]
    levels = slippage_levels or [1.0, 2.0, 3.0, 4.0, 5.0]

    # Carrega as configurações otimizadas salvas na arena
    arena_file = REPORTS_DIR / "norisknogain_full_arena.json"
    arena_data = {}
    if arena_file.exists():
        try:
            arena_data = json.loads(arena_file.read_text(encoding="utf-8")).get("arena_by_symbol", {})
        except Exception:
            arena_data = {}

    results_by_sym: Dict[str, Any] = {}

    for sym in syms:
        norm_sym = feed.normalize_symbol(sym)
        f_spec = FUTURES_SPECS.get(norm_sym, {"tick_size": 1.0, "point_value_brl": 1.0})
        tick = f_spec["tick_size"]
        pt_val = f_spec["point_value_brl"]

        sym_tfs: Dict[str, Any] = {}
        for tf in tfs:
            raw_df = feed.get_bars(norm_sym, timeframe=tf)
            if raw_df.empty or len(raw_df) < 50:
                continue
            df = enrich_indicators_and_regimes(raw_df, timeframe=tf)

            # Busca a lista de robôs e seus melhores filtros para este ativo/timeframe
            tf_saved = arena_data.get(norm_sym, {}).get("by_timeframe", {}).get(tf, {})
            saved_bots = tf_saved.get("bots_ranking", [])

            # Seleciona os robôs representativos (campeões de reversão, seguidor de tendência e rompimento)
            target_bot_ids = ["NRNG-009", "NRNG-003", "NRNG-002", "NRNG-006", "NRNG-008", "NRNG-004", "NRNG-001"]
            bots_to_test = []
            if saved_bots:
                for b_info in saved_bots:
                    bid = b_info["bot_id"]
                    if bid in target_bot_ids:
                        best = b_info["best_overall"]
                        bots_to_test.append({
                            "bot_id": bid,
                            "bot_name": b_info["bot_name"],
                            "family": b_info["family"],
                            "params": best["params"],
                            "filters": FilterConfig(**best["filters"]),
                            "filter_label": best["filter_label"],
                        })
            else:
                for bid in target_bot_ids:
                    bs = get_bot_by_id(bid)
                    bots_to_test.append({
                        "bot_id": bid,
                        "bot_name": bs.name,
                        "family": bs.family,
                        "params": bs.default_params,
                        "filters": FilterConfig(trend_filter="ema20_50_align"),
                        "filter_label": "trend=ema20_50_align",
                    })

            # Executa a curva de estresse para cada robô
            bots_stress = []
            for b_spec in bots_to_test:
                level_results = {}
                for slip in levels:
                    res = run_bot_backtest(
                        df,
                        b_spec["bot_id"],
                        params=b_spec["params"],
                        filters=b_spec["filters"],
                        timeframe=tf,
                        symbol=norm_sym,
                        slippage_ticks=slip,
                        include_trades_list=False,
                    )
                    sm = res["summary"]
                    level_results[str(slip)] = {
                        "slippage_ticks": slip,
                        "cost_pts": round(slip * tick, 2),
                        "cost_brl_per_trade": round(slip * tick * pt_val, 2),
                        "total_points": sm.get("total_points", 0.0),
                        "pnl_1_contract_brl": sm.get("pnl_1_contract_brl", 0.0),
                        "win_rate_pct": sm.get("win_rate_pct", 0.0),
                        "profit_factor": sm.get("profit_factor", 0.0),
                        "max_drawdown_pct": sm.get("max_drawdown_pct", 0.0),
                        "trades": sm.get("trades", 0),
                    }

                # Estima o ponto de Break-Even (quantos ticks aguenta)
                base_pts = level_results.get("1.0", {}).get("total_points", 0.0)
                n_trades = level_results.get("1.0", {}).get("trades", 1)
                pts_per_trade = (base_pts / n_trades) if n_trades > 0 else 0.0
                breakeven_slip_ticks = round(1.0 + (pts_per_trade / tick), 1) if pts_per_trade > 0 else 1.0

                bots_stress.append({
                    "bot_id": b_spec["bot_id"],
                    "bot_name": b_spec["bot_name"],
                    "family": b_spec["family"],
                    "filter_label": b_spec["filter_label"],
                    "breakeven_slippage_ticks": breakeven_slip_ticks,
                    "curve_by_slippage": level_results,
                })

            # Também testa o Meta-Seletor Causal sob estresse
            meta_stress = {}
            causal_specs = tf_saved.get("meta_causal_selector", {}).get("causal_specialists", {})
            for slip in levels:
                # Simula cada especialista com o nível de slippage
                causal_trades = []
                for reg in ("ALTA", "LATERAL", "BAIXA"):
                    sp = causal_specs.get(reg)
                    if not sp:
                        continue
                    sp_filter = FilterConfig(**sp["filters"]) if sp.get("filters") else parse_filter_label(sp.get("filter_label", ""))
                    r_run = run_bot_backtest(
                        df,
                        sp["bot_id"],
                        params=sp["params"],
                        filters=sp_filter,
                        timeframe=tf,
                        symbol=norm_sym,
                        slippage_ticks=slip,
                        include_trades_list=True,
                    )
                    for t in r_run["trades"]:
                        if t.get("causal_regime") == reg:
                            t_copy = dict(t)
                            t_copy["selected_by_regime"] = reg
                            causal_trades.append(t_copy)

                causal_trades.sort(key=lambda x: x["entry_ts"])
                # Sem overlap
                non_overlap = []
                last_exit = ""
                for t in causal_trades:
                    if t["entry_ts"] > last_exit:
                        non_overlap.append(t)
                        last_exit = t["exit_ts"]

                m_metrics = _compute_slice_metrics(non_overlap)
                meta_stress[str(slip)] = {
                    "slippage_ticks": slip,
                    "cost_pts": round(slip * tick, 2),
                    "total_points": m_metrics.get("total_points", 0.0),
                    "pnl_1_contract_brl": m_metrics.get("pnl_1_contract_brl", 0.0),
                    "win_rate_pct": m_metrics.get("win_rate_pct", 0.0),
                    "profit_factor": m_metrics.get("profit_factor", 0.0),
                    "max_drawdown_pct": m_metrics.get("max_drawdown_pct", 0.0),
                    "trades": m_metrics.get("trades", 0),
                }

            base_meta_pts = meta_stress.get("1.0", {}).get("total_points", 0.0)
            n_meta_tr = meta_stress.get("1.0", {}).get("trades", 1)
            pts_per_tr_meta = (base_meta_pts / n_meta_tr) if n_meta_tr > 0 else 0.0
            meta_be_ticks = round(1.0 + (pts_per_tr_meta / tick), 1) if pts_per_tr_meta > 0 else 1.0

            sym_tfs[tf] = {
                "timeframe": tf,
                "bars_count": len(df),
                "bots_stress": bots_stress,
                "meta_causal_stress": {
                    "breakeven_slippage_ticks": meta_be_ticks,
                    "curve_by_slippage": meta_stress,
                },
            }

        results_by_sym[norm_sym] = sym_tfs

    # Gera o Relatório Markdown
    md_content = _build_stress_report_markdown(results_by_sym, levels)
    out_md = REPORTS_DIR / "RELATORIO_STRESS_TEST_SLIPPAGE.md"
    out_md.write_text(md_content, encoding="utf-8")

    out_json = REPORTS_DIR / "slippage_stress_test.json"
    out_json.write_text(json.dumps(results_by_sym, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "md_path": str(out_md),
        "json_path": str(out_json),
        "data": results_by_sym,
    }


def _build_stress_report_markdown(data: Dict[str, Any], levels: List[float]) -> str:
    lines = [
        "# Relatório de Estresse de Slippage & Microestrutura B3 (WIN$N e WDO$N)",
        "",
        "Avaliação rigorosa de sensibilidade a custos e derrapagem de ordens de mercado/stop.",
        "Compara o desempenho sob **1 tick (normal)**, **2 ticks (+100%)**, **3 ticks (+200%)**, **4 ticks (+300%)** e **5 ticks (+400%)**.",
        "",
        "---",
        "",
    ]

    for sym, tfs_data in data.items():
        f_spec = FUTURES_SPECS.get(sym, {"tick_size": 1.0, "point_value_brl": 1.0, "name": sym})
        tick = f_spec["tick_size"]
        pt_val = f_spec["point_value_brl"]

        lines.append(f"## Ativo: {f_spec['name']} (`{sym}`)")
        lines.append(f"> **Microestrutura**: 1 tick = `{tick} pts` = `R$ {tick * pt_val:.2f}` por contrato | Penalização de Stop Loss com derrapagem progressiva ativa.")
        lines.append("")

        for tf, tf_obj in tfs_data.items():
            lines.append(f"### Timeframe `{tf}` ({tf_obj['bars_count']} barras)")
            lines.append("")

            # Tabela do Meta-Seletor Causal
            m_stress = tf_obj["meta_causal_stress"]
            lines.append("#### Degradação do Meta-Seletor Causal por Nível de Slippage")
            lines.append("")
            lines.append("| Cenário de Slippage | Custo por Trade | Pontos Líquidos | Lucro 1 Contr. (R$) | Win Rate (%) | Profit Factor | Max DD (%) | Trades | Status |")
            lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")

            for slip in levels:
                row = m_stress["curve_by_slippage"].get(str(slip), {})
                pts = row.get("total_points", 0.0)
                pnl = row.get("pnl_1_contract_brl", 0.0)
                wr = row.get("win_rate_pct", 0.0)
                pf = row.get("profit_factor", 0.0)
                dd = row.get("max_drawdown_pct", 0.0)
                tr = row.get("trades", 0)
                status = "✅ Resiliente" if pts > 0 and pf >= 1.3 else ("⚠️ Frágil" if pts > 0 else "❌ Negativo")
                lines.append(
                    f"| **{int(slip) if slip.is_integer() else slip} tick(s)** ({row.get('cost_pts', 0):.1f} pts) | "
                    f"R$ {row.get('cost_pts', 0) * pt_val:,.2f} | **{pts:+.1f} pts** | R$ {pnl:+,.2f} | "
                    f"{wr:.1f}% | {pf:.2f} | {dd:.2f}% | {tr} | {status} |"
                )

            lines.append("")
            lines.append(f"> **Slippage Máximo Suportado (Break-Even)**: `{m_stress['breakeven_slippage_ticks']} ticks` ({m_stress['breakeven_slippage_ticks'] * tick:.1f} pontos).")
            lines.append("")

            # Tabela comparativa dos robôs
            lines.append("#### Sensibilidade ao Slippage dos Robôs Individuais")
            lines.append("")
            lines.append("| Robô | Família | 1 Tick (Base) | 2 Ticks (+100%) | 3 Ticks (+200%) | 5 Ticks (+400%) | Break-Even Slippage | Tolerância |")
            lines.append("|---|---|---:|---:|---:|---:|---:|---|")

            for b in tf_obj["bots_stress"]:
                c = b["curve_by_slippage"]
                p1 = c.get("1.0", {}).get("total_points", 0.0)
                p2 = c.get("2.0", {}).get("total_points", 0.0)
                p3 = c.get("3.0", {}).get("total_points", 0.0)
                p5 = c.get("5.0", {}).get("total_points", 0.0)
                be = b["breakeven_slippage_ticks"]
                tol = "🛡️ Alta" if be >= 4.0 else ("⚖️ Média" if be >= 2.2 else "⚠️ Baixa (Scalper Puro)")
                lines.append(
                    f"| `{b['bot_id']}` {b['bot_name'][:28]} | `{b['family']}` | "
                    f"{p1:+.1f} pts | {p2:+.1f} pts | {p3:+.1f} pts | {p5:+.1f} pts | "
                    f"**{be:.1f} ticks** | {tol} |"
                )

            lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    print("[Robo Lab] Executando Teste de Estresse de Slippage...")
    res = run_slippage_stress_analysis()
    print(f"[OK] Relatório salvo em: {res['md_path']}")
