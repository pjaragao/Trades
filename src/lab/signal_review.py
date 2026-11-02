"""
Revisão de um sinal antes de copiar: histórico do analista -> plano (stop/alvo) -> Máquina do Tempo -> tamanho pelo
risco e checagem -> boleta.

É o fluxo do day-trader-skill (exit -> timemachine -> budget -> risk -> broker) adaptado ao Copiloto: o sinal vem do
TradingFloors (sem stop nem alvo), o plano sai do histórico do próprio analista ou do ATR do ativo, e a ordem quem
envia sou eu — no Home Broker ou pela tela do Copiloto, que tem a própria confirmação. Nada aqui envia ordem.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core import b3_tickers, db
from src.core.config import ROOT, get_prefs
from src.core.market_hours import to_brt
from src.lab import analyst_history, timemachine
from src.services import pretrade, sizing

LIMITS_FILE = ROOT / ".claude" / "skills" / "copiloto-risco" / "limites.json"
SIGNAL_FIELDS = ("id", "ticker", "underlying", "asset_class", "lado", "preco_entrada", "preco_atual", "preco_atual_at",
                 "timestamp_entrada", "expiration", "trader", "opcao_tipo", "strike", "status", "produto")


def load_limits(path: Optional[str] = None) -> Dict[str, Any]:
    p = Path(path) if path else LIMITS_FILE
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return {**pretrade.DEFAULT_LIMITS, **data}


def _slim(sig: Dict[str, Any]) -> Dict[str, Any]:
    return {k: sig.get(k) for k in SIGNAL_FIELDS}


def open_signals(prefs: Dict[str, Any], followed_only: bool = True, conn=None,
                 use_api: bool = True) -> Tuple[List[Dict[str, Any]], str]:
    """Sinais abertos do banco do Copiloto; banco sem sinais abertos -> API do TradingFloors."""
    from src.services.signals import is_followed

    with db.connection(conn) as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM signals WHERE status = 'OPEN'")]
    source = "banco do Copiloto"
    if not rows and use_api:
        from src.integrations import tradingfloors as tf

        client = tf.get_client()
        if client.configured:
            trades, opcoes = client.fetch_open()
            rows = [s for s in tf.merge_rows(trades, opcoes) if s.get("status") == "OPEN"]
            source = "API do TradingFloors"
    sigs = [_slim(r) for r in rows if not followed_only or is_followed(r, prefs)]
    sigs.sort(key=lambda s: s.get("timestamp_entrada") or "", reverse=True)
    return sigs, source


def find_signal(signal_id: str, prefs: Dict[str, Any], conn=None, use_api: bool = True) -> Optional[Dict[str, Any]]:
    with db.connection(conn) as c:
        row = c.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
    if row:
        return _slim(dict(row))
    sigs, _ = open_signals(prefs, followed_only=False, conn=conn, use_api=use_api)
    return next((s for s in sigs if s["id"] == signal_id or str(s["id"]).startswith(signal_id)), None)


def manual_signal(ticker: str, side: str, entry: float, trader: Optional[str] = None, strike: Optional[float] = None,
                  expiration: Optional[str] = None, opcao_tipo: Optional[str] = None) -> Dict[str, Any]:
    tk = b3_tickers.clean_ticker(ticker)
    asset = b3_tickers.asset_class(None, tk)
    info = b3_tickers.decode_option(tk) if asset == "OPCAO" else None
    return {
        "id": None, "ticker": tk, "underlying": (info or {}).get("underlying") or b3_tickers.underlying_of(tk),
        "asset_class": asset, "lado": "SELL" if str(side).upper() in ("SELL", "VENDA", "V") else "BUY",
        "preco_entrada": entry, "preco_atual": entry, "timestamp_entrada": None,
        "expiration": expiration or (info or {}).get("expiration"), "trader": trader,
        "opcao_tipo": opcao_tipo or (info or {}).get("kind"), "strike": strike, "status": "MANUAL",
    }


def _selic() -> float:
    try:
        from src.lab import rates

        return float(rates.get_rates()["selic"]["value"])
    except Exception:  # noqa: BLE001 — sem rede/banco: padrão do módulo
        return 15.0


def review(sig: Dict[str, Any], *, entry: Optional[float] = None, stop: Optional[float] = None,
           target: Optional[float] = None, stop_pct: Optional[float] = None, target_pct: Optional[float] = None,
           mode: str = "swing", horizon: Optional[int] = None, entry_time: Optional[str] = None,
           replays: int = 10000, seed: int = 19, simulate: bool = True, limits: Optional[Dict[str, Any]] = None,
           account: str = "real", history_rows: Optional[List[Dict[str, Any]]] = None,
           prefs: Optional[Dict[str, Any]] = None, bars=None, rate: Optional[float] = None,
           spot: Optional[float] = None, use_api: bool = True, conn=None) -> Dict[str, Any]:
    prefs = prefs or get_prefs(conn)
    limits = limits or load_limits()
    asset = sig.get("asset_class") or b3_tickers.asset_class(None, sig["ticker"])
    side = sig.get("lado") or "BUY"
    my_entry = float(entry or sig.get("preco_atual") or sig.get("preco_entrada") or 0)
    out: Dict[str, Any] = {"signal": sig, "entry": my_entry, "notes": []}

    # ---------------- histórico do analista
    analyst = None
    if sig.get("trader"):
        if history_rows is None:
            history_rows, out["history_source"] = analyst_history.load_closed(conn, use_api=use_api)
        analyst = analyst_history.summarize(history_rows, sig["trader"], asset)
        out["analyst"] = analyst if analyst["closed"] else None
        if not analyst["closed"]:
            analyst = None
    hist_plan = (analyst or {}).get("plan") or {}

    # ---------------- plano: informado > histórico do analista > ATR
    use_stop_pct = stop_pct if stop_pct is not None else (hist_plan.get("stop_pct") if stop is None else None)
    use_target_pct = target_pct if target_pct is not None else (hist_plan.get("target_pct") if target is None else None)
    horizon = horizon or hist_plan.get("horizon_days") or timemachine.DEFAULT_HORIZON
    if analyst and analyst.get("copyable") == "no":
        out["notes"].append(f"{sig['trader']} opera majoritariamente no mesmo dia nesta classe: cópia manual tende a chegar atrasada "
                            f"(use --modo intraday para simular o resto do pregão).")

    mc = None
    if simulate:
        try:
            mc = timemachine.run(
                ticker=sig["ticker"], side=side, entry=my_entry, stop=stop, target=target, mode=mode, horizon=horizon,
                entry_time=entry_time, replays=replays, seed=seed, stop_pct=use_stop_pct, target_pct=use_target_pct,
                strike=sig.get("strike"), expiration=sig.get("expiration"), option_kind=sig.get("opcao_tipo"),
                spot=spot, bars=bars, rate=(rate if rate is not None else _selic()) if asset == "OPCAO" else None,
            )
            if use_target_pct and target is None:
                mc["plan"]["source"] += f"; alvo {use_target_pct:.1f}% = ganho mediano de {sig['trader']}".replace(".", ",")
            stop, target = mc["plan"]["stop"], mc["plan"]["target"]
        except timemachine.TMError as exc:
            out["mc_error"] = str(exc)
    elif stop is None and use_stop_pct:
        sign = 1 if side == "BUY" else -1
        stop = round(my_entry * (1 - sign * use_stop_pct / 100), 2)
        if target is None and use_target_pct:
            target = round(my_entry * (1 + sign * use_target_pct / 100), 2)
    out["mc"] = mc

    # ---------------- tamanho pelo risco e checagem
    ctx = pretrade.context(account, conn)
    chk = pretrade.check(ticker=sig["ticker"], side=side, entry=my_entry, stop=stop, target=target, prefs=prefs,
                         limits=limits, asset_class=asset, ctx=ctx, analyst=analyst, expiration=sig.get("expiration"),
                         opcao_tipo=sig.get("opcao_tipo"), signal_id=sig.get("id"), ref_entry=sig.get("preco_entrada"))
    out["check"] = chk

    # ---------------- boleta (mesmo texto da tela do Copiloto), só com a checagem aprovada
    if chk["ok"] and chk.get("qty"):
        ticket_sig = {**sig, "asset_class": asset, "preco_atual": my_entry, "stop_loss": stop,
                      "preco_entrada": sig.get("preco_entrada") or my_entry}
        ticket = sizing.build_ticket(ticket_sig, prefs, exposure=ctx["exposure"], quantity=chk["qty"], limit_price=my_entry)
        out["ticket"] = {"copy_text": ticket["copy_text"], "total": ticket["total"], "fees": ticket["fees_estimate"],
                         "max_loss": ticket["max_loss"],
                         "warnings": [w["text"] for w in ticket["warnings"] if w["level"] in ("danger", "warning")]}
    return out


def _n(v: Optional[float], d: int = 2) -> str:
    return "—" if v is None else f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def report(rv: Dict[str, Any]) -> str:
    sig = rv["signal"]
    lado = "COMPRA" if sig.get("lado") == "BUY" else "VENDA"
    when = to_brt(sig.get("timestamp_entrada"))
    head = f"== {lado} {sig['ticker']}" + (f" · {sig['trader']}" if sig.get("trader") else "")
    if when:
        head += f" · sinal de {when:%d/%m %H:%M}".replace(" 00:00", "")
    lines = [head + " =="]
    if sig.get("preco_entrada") and rv["entry"] and abs(rv["entry"] - sig["preco_entrada"]) > 1e-9:
        drift = (rv["entry"] / sig["preco_entrada"] - 1) * 100
        lines.append(f"Entrada do analista {_n(sig['preco_entrada'])} · minha entrada {_n(rv['entry'])} ({'+' if drift > 0 else ''}{_n(drift, 1)}%)")
    if rv.get("analyst"):
        lines += ["", "-- Histórico do analista" + (f" (fonte: {rv['history_source']})" if rv.get("history_source") else ""),
                  analyst_history.report(rv["analyst"])]
    lines.append("")
    lines.append("-- Máquina do Tempo")
    if rv.get("mc"):
        lines.append(timemachine.report(rv["mc"]))
    else:
        lines.append(rv.get("mc_error") or "não simulada")
    lines += ["", "-- Risco e tamanho", pretrade.report(rv["check"])]
    if rv.get("ticket"):
        lines += ["", "-- Boleta (copiar no Home Broker)", rv["ticket"]["copy_text"]]
        lines += [f"! {w}" for w in rv["ticket"]["warnings"]]
    else:
        lines += ["", "-- Boleta não gerada: checagem bloqueada."]
    lines += [f"! {n}" for n in rv["notes"]]
    lines += ["", "Simulação e histórico não são previsão. Nada foi enviado: a decisão e a ordem são suas."]
    return "\n".join(lines)


__all__ = ["load_limits", "open_signals", "find_signal", "manual_signal", "review", "report"]
