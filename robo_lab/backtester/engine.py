"""
Motor de Backtest Rápido e Robusto para Day Trade (Futuros WIN$N / WDO$N e Ações) e Swing Trade na B3.
Simula entradas, alvos (Take Profit), stops (Stop Loss), saídas por tempo (Time Exit),
zeragem compulsória de fim de pregão (Day Trade End-of-Day Flat nos tempos curtos 1m, 2m, 3m, 5m, 15m),
custos operacionais da B3 + slippage e segmenta automaticamente todos os resultados por:
- Sentimento de Mercado Ex-Post (Mês de ALTA, BAIXA, LATERAL)
- Sentimento de Mercado Causal (Zero Look-Ahead: ALTA, BAIXA, LATERAL)
- Perfil do Dia da Bolsa (Volume Alto/Normal/Baixo, Direcional Alta/Baixa/Lateral)
"""

from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from robo_lab.config import BACKTEST_DEFAULTS, FUTURES_SPECS
from robo_lab.strategies.base_bot import FilterConfig, apply_universal_filters
from robo_lab.strategies.bots_norisknogain import BOT_SIGNAL_FUNCTIONS, get_bot_by_id


def _compute_slice_metrics(trades: List[Dict[str, Any]], initial_capital: float = 100000.0) -> Dict[str, Any]:
    n = len(trades)
    if n == 0:
        return {
            "trades": 0,
            "win_rate_pct": 0.0,
            "avg_return_pct": 0.0,
            "total_return_pct": 0.0,
            "net_pnl_brl": 0.0,
            "total_points": 0.0,
            "pnl_1_contract_brl": 0.0,
            "profit_factor": 0.0,
            "payoff_ratio": 0.0,
            "expectancy_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe": 0.0,
            "robustness_score": -10.0,
        }

    rets = np.array([t["net_return_pct"] for t in trades], dtype=float)
    pnls = np.array([t["net_pnl_brl"] for t in trades], dtype=float)
    pts = np.array([t.get("net_points", 0.0) for t in trades], dtype=float)
    pnl_1c = np.array([t.get("pnl_1_contract_brl", 0.0) for t in trades], dtype=float)

    wins = rets[rets > 0]
    losses = rets[rets <= 0]

    win_rate = (len(wins) / n) * 100.0
    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(np.abs(losses.mean())) if len(losses) > 0 else 0.0
    payoff = (avg_win / avg_loss) if avg_loss > 1e-9 else (2.5 if avg_win > 0 else 0.0)

    gross_profit = float(pnls[pnls > 0].sum()) if np.any(pnls > 0) else 0.0
    gross_loss = float(np.abs(pnls[pnls <= 0].sum())) if np.any(pnls <= 0) else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 1e-9 else (5.0 if gross_profit > 0 else 0.0)

    expectancy_pct = float(rets.mean())
    total_pnl = float(pnls.sum())
    total_return_pct = (total_pnl / initial_capital) * 100.0

    # Curva de patrimônio e Max Drawdown
    eq = initial_capital + np.cumsum(pnls)
    eq_full = np.concatenate([[initial_capital], eq])
    peaks = np.maximum.accumulate(eq_full)
    dd_pct = ((peaks - eq_full) / np.maximum(peaks, 1.0)) * 100.0
    max_dd_pct = float(dd_pct.max())

    std_ret = float(rets.std()) if n > 1 else 1.0
    sharpe = (expectancy_pct / std_ret) * np.sqrt(min(n, 252)) if std_ret > 1e-9 else 0.0

    # Score de Robustez: premia retorno líquido, profit factor, win rate, controle de drawdown e tamanho amostral
    sample_weight = min(1.0, n / 12.0)
    pf_capped = min(profit_factor, 4.5)
    robustness = sample_weight * (
        total_return_pct * 0.55
        + (pf_capped - 1.0) * 12.0
        + (win_rate - 50.0) * 0.25
        - max_dd_pct * 0.65
    )

    return {
        "trades": n,
        "win_rate_pct": round(win_rate, 2),
        "avg_return_pct": round(expectancy_pct, 3),
        "total_return_pct": round(total_return_pct, 2),
        "net_pnl_brl": round(total_pnl, 2),
        "total_points": round(float(pts.sum()), 1),
        "pnl_1_contract_brl": round(float(pnl_1c.sum()), 2),
        "profit_factor": round(min(profit_factor, 99.9), 2),
        "payoff_ratio": round(min(payoff, 99.9), 2),
        "expectancy_pct": round(expectancy_pct, 3),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe": round(sharpe, 2),
        "robustness_score": round(float(robustness), 2),
    }


def run_bot_backtest(
    df: pd.DataFrame,
    bot_id: str,
    params: Optional[Dict[str, Any]] = None,
    filters: Optional[FilterConfig] = None,
    timeframe: str = "1d",
    symbol: str = "^BVSP",
    slippage_ticks: float = 1.0,
    initial_capital: float = BACKTEST_DEFAULTS["initial_capital"],
    position_size_pct: float = BACKTEST_DEFAULTS["position_size_pct"],
    include_trades_list: bool = True,
) -> Dict[str, Any]:
    """
    Executa a simulação barra a barra (com sinais pré-vetorizados) de um robô do catálogo.
    Nos timeframes curtos de Day Trade ('1m', '2m', '3m', '5m', '15m'), aplica zeragem compulsória no fim do dia.
    Para WIN$N e WDO$N, calcula também os pontos líquidos e o resultado em R$ por mini-contrato.
    """
    bot_spec = get_bot_by_id(bot_id)
    sig_fn = BOT_SIGNAL_FUNCTIONS[bot_id]
    eff_params = dict(bot_spec.default_params)
    if params:
        eff_params.update(params)
    eff_filters = filters or FilterConfig()

    if len(df) < 30:
        return {
            "bot_id": bot_id,
            "bot_name": bot_spec.name,
            "timeframe": timeframe,
            "params": eff_params,
            "filters": eff_filters.to_dict(),
            "filter_label": eff_filters.label(),
            "summary": _compute_slice_metrics([], initial_capital),
            "by_expost_regime": {},
            "by_causal_regime": {},
            "by_volume_profile": {},
            "by_day_direction": {},
            "equity_curve": [],
            "trades": [],
        }

    raw_entry, tp_dist, sl_dist, max_hold = sig_fn(df, eff_params)
    entry_signals = apply_universal_filters(df, raw_entry, eff_filters, timeframe=timeframe)

    c = df["close"].to_numpy()
    o = df["open"].to_numpy()
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    ts_index = df.index
    days_arr = ts_index.date

    expost_reg = df["expost_regime"].to_numpy()
    causal_reg = df["causal_regime"].to_numpy()
    vol_prof = df["volume_profile"].to_numpy()
    day_dir = df["day_direction_profile"].to_numpy()

    norm_sym = symbol.strip().upper()
    fut_spec = FUTURES_SPECS.get(norm_sym)
    slip_mult = max(0.5, float(slippage_ticks))
    if fut_spec is not None:
        cost_in_points = fut_spec["tick_size"] * slip_mult
        ref_px = float(c[0]) if len(c) > 0 and c[0] > 0 else 100000.0
        roundtrip_cost_pct = (2.0 * fut_spec["fee_pct_per_side"] * 100.0) + ((cost_in_points / ref_px) * 100.0)
        point_val_brl = fut_spec["point_value_brl"]
        extra_stop_slip = fut_spec["tick_size"] * max(0.0, slip_mult - 1.0) * 0.5
    else:
        roundtrip_cost_pct = 2.0 * (BACKTEST_DEFAULTS["b3_fee_pct_per_side"] + BACKTEST_DEFAULTS["slippage_pct_per_side"] * slip_mult) * 100.0
        cost_in_points = 0.0
        point_val_brl = 1.0
        extra_stop_slip = 0.0

    is_daytrade_tf = timeframe in ("1m", "2m", "3m", "5m", "15m")
    trade_capital = initial_capital * position_size_pct

    trades: List[Dict[str, Any]] = []
    n = len(df)
    i = 20  # Warmup das médias e indicadores

    while i < n - 1:
        side = int(entry_signals[i])
        if side == 0:
            i += 1
            continue

        # Em Day Trade, evita abrir posição na última barra do dia
        if is_daytrade_tf and days_arr[i + 1] != days_arr[i]:
            i += 1
            continue

        entry_idx = i
        entry_price = float(c[entry_idx])
        if entry_price <= 0:
            i += 1
            continue

        tp = float(tp_dist[entry_idx])
        sl = float(sl_dist[entry_idx])
        target_price = entry_price + side * tp
        stop_price = entry_price - side * sl

        exit_idx = min(entry_idx + max_hold, n - 1)
        exit_price = float(c[exit_idx])
        exit_reason = "TIME_EXIT"

        for j in range(entry_idx + 1, min(entry_idx + max_hold + 1, n)):
            bar_h = float(h[j])
            bar_l = float(l[j])
            bar_o = float(o[j])

            if side == 1:
                if bar_l <= stop_price:
                    exit_idx = j
                    base_px = min(bar_o, stop_price) if bar_o < stop_price else stop_price
                    exit_price = base_px - extra_stop_slip
                    exit_reason = "STOP_LOSS"
                    break
                if bar_h >= target_price:
                    exit_idx = j
                    exit_price = max(bar_o, target_price) if bar_o > target_price else target_price
                    exit_reason = "TAKE_PROFIT"
                    break
            else:
                if bar_h >= stop_price:
                    exit_idx = j
                    base_px = max(bar_o, stop_price) if bar_o > stop_price else stop_price
                    exit_price = base_px + extra_stop_slip
                    exit_reason = "STOP_LOSS"
                    break
                if bar_l <= target_price:
                    exit_idx = j
                    exit_price = min(bar_o, target_price) if bar_o < target_price else target_price
                    exit_reason = "TAKE_PROFIT"
                    break

            # Zeragem Compulsória Day Trade no fechamento da última barra do pregão
            if is_daytrade_tf and (j == n - 1 or days_arr[j + 1] != days_arr[entry_idx]):
                exit_idx = j
                exit_price = float(c[j])
                exit_reason = "EOD_DAYTRADE_FLAT"
                break

            if entry_signals[j] == -side:
                exit_idx = j
                exit_price = float(c[j])
                exit_reason = "REVERSE_SIGNAL"
                break

        gross_points = side * (exit_price - entry_price)
        net_points = gross_points - cost_in_points
        pnl_1_contract_brl = net_points * point_val_brl

        gross_ret_pct = side * ((exit_price - entry_price) / entry_price) * 100.0
        net_ret_pct = gross_ret_pct - roundtrip_cost_pct
        net_pnl_brl = trade_capital * (net_ret_pct / 100.0)

        trades.append({
            "bot_id": bot_id,
            "entry_ts": str(ts_index[entry_idx]),
            "exit_ts": str(ts_index[exit_idx]),
            "side": "LONG" if side == 1 else "SHORT",
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "hold_bars": int(exit_idx - entry_idx),
            "exit_reason": exit_reason,
            "gross_points": round(gross_points, 2),
            "net_points": round(net_points, 2),
            "pnl_1_contract_brl": round(pnl_1_contract_brl, 2),
            "gross_return_pct": round(gross_ret_pct, 3),
            "net_return_pct": round(net_ret_pct, 3),
            "net_pnl_brl": round(net_pnl_brl, 2),
            "expost_regime": str(expost_reg[entry_idx]),
            "causal_regime": str(causal_reg[entry_idx]),
            "volume_profile": str(vol_prof[entry_idx]),
            "day_direction_profile": str(day_dir[entry_idx]),
        })

        i = max(exit_idx + 1, i + 1)

    summary = _compute_slice_metrics(trades, initial_capital)

    by_expost = {
        reg: _compute_slice_metrics([t for t in trades if t["expost_regime"] == reg], initial_capital)
        for reg in ("ALTA", "LATERAL", "BAIXA")
    }
    by_causal = {
        reg: _compute_slice_metrics([t for t in trades if t["causal_regime"] == reg], initial_capital)
        for reg in ("ALTA", "LATERAL", "BAIXA")
    }
    by_volume = {
        vp: _compute_slice_metrics([t for t in trades if t["volume_profile"] == vp], initial_capital)
        for vp in ("VOLUME_ALTO", "VOLUME_NORMAL", "VOLUME_BAIXO")
    }
    by_day_dir = {
        dd: _compute_slice_metrics([t for t in trades if t["day_direction_profile"] == dd], initial_capital)
        for dd in ("DIA_DIRECIONAL_ALTA", "DIA_DIRECIONAL_BAIXA", "DIA_LATERAL_OSCILANTE")
    }

    equity_curve = []
    if include_trades_list:
        curr_eq = initial_capital
        equity_curve.append({"ts": str(ts_index[0])[:10], "equity": round(curr_eq, 2)})
        for t in trades:
            curr_eq += t["net_pnl_brl"]
            equity_curve.append({"ts": t["exit_ts"][:16], "equity": round(curr_eq, 2)})

    return {
        "bot_id": bot_id,
        "bot_name": bot_spec.name,
        "family": bot_spec.family,
        "timeframe": timeframe,
        "params": eff_params,
        "filters": eff_filters.to_dict(),
        "filter_label": eff_filters.label(),
        "summary": summary,
        "by_expost_regime": by_expost,
        "by_causal_regime": by_causal,
        "by_volume_profile": by_volume,
        "by_day_direction": by_day_dir,
        "equity_curve": equity_curve,
        "trades": trades if include_trades_list else [],
    }
