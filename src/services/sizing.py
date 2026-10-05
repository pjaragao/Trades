"""
"Boleta pronta": quanto comprar/vender, a que preço limite, quanto custa e quais os riscos.

Diferente do robô antigo, NUNCA força 1 lote quando o capital não cobre — devolve quantidade 0
com o aviso e o custo de 1 lote, para eu decidir.
"""
import math
from datetime import date
from typing import Any, Dict, List, Optional

from src.core import b3_tickers
from src.core.config import get_prefs
from src.core.market_hours import business_days_between, market_status, now_brt, to_brt
from src.services.journal import estimate_fees

TICK = 0.01


def _fmt_brl(v: Optional[float], decimals: int = 2) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if v < 0 else ''}R$ {s}"


def _fmt_qty(q: float) -> str:
    return f"{q:,.0f}".replace(",", ".") if float(q).is_integer() else f"{q:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _round_tick(price: float, up: bool) -> float:
    steps = price / TICK
    steps = math.ceil(steps - 1e-9) if up else math.floor(steps + 1e-9)
    return round(steps * TICK, 2)


def build_ticket(
    signal: Dict[str, Any],
    prefs: Optional[Dict[str, Any]] = None,
    exposure: float = 0.0,
    quantity: Optional[float] = None,
    limit_price: Optional[float] = None,
    trader_profile: Optional[Dict[str, Any]] = None,
    at=None,
) -> Dict[str, Any]:
    """
    signal   : sinal hidratado (services.signals.hydrate)
    exposure : R$ já alocados em posições abertas (para checar capital disponível)
    quantity / limit_price : sobrescritas manuais vindas da tela
    """
    prefs = prefs or get_prefs()
    sizing, capital = prefs["sizing"], float(prefs["capital"]["total"])
    asset = signal.get("asset_class") or "OUTRO"
    side = signal.get("lado", "BUY")
    is_buy = side == "BUY"
    entry = float(signal.get("preco_entrada") or 0)
    current = signal.get("preco_atual")
    current = float(current) if current is not None else None
    slip = float(sizing["max_slippage_pct"]) / 100.0
    warnings: List[Dict[str, str]] = []

    def warn(level: str, text: str) -> None:
        warnings.append({"level": level, "text": text})

    # ---------------- preço
    if entry > 0:
        worst = _round_tick(entry * (1 + slip), up=False) if is_buy else _round_tick(entry * (1 - slip), up=True)
    else:
        worst = None
    if limit_price is not None and limit_price > 0:
        limit = round(float(limit_price), 2)
    elif current is not None and entry > 0:
        if is_buy:
            limit = current if current <= worst else worst
        else:
            limit = current if current >= worst else worst
        limit = round(limit, 2)
    else:
        limit = round(entry, 2) if entry > 0 else (round(current, 2) if current else 0.0)

    drift_pct = None
    if current is not None and entry > 0:
        drift_pct = round((current / entry - 1) * 100, 2)
        adverse = drift_pct if is_buy else -drift_pct
        if adverse > slip * 100:
            warn("danger", f"Preço atual já está {abs(drift_pct):.1f}% {'acima' if drift_pct > 0 else 'abaixo'} da entrada do analista "
                           f"(limite configurado: {sizing['max_slippage_pct']:.1f}%). A boleta usa o preço máximo aceitável.")
        elif adverse > 0.5:
            warn("warning", f"Preço atual {abs(drift_pct):.1f}% {'acima' if drift_pct > 0 else 'abaixo'} da entrada do analista.")
        elif adverse < -0.5:
            warn("info", f"Preço atual {abs(drift_pct):.1f}% melhor que a entrada do analista.")
    elif current is None:
        warn("info", "Sem cotação atual do TradingFloors — confira o preço no Home Broker antes de enviar.")

    # ---------------- quantidade
    lot = 1 if asset in ("FUTURO", "FOREX", "INDICE", "COMMODITY", "CRIPTO") else int(sizing.get("lot_step") or b3_tickers.default_lot(asset))
    budget = float(sizing["value_per_trade"]) if sizing["mode"] == "fixed_capital" else capital * float(sizing["pct_per_trade"]) / 100.0
    available = max(0.0, capital - exposure) if capital > 0 else budget
    if capital > 0 and budget > available:
        warn("warning", f"Capital livre ({_fmt_brl(available)}) menor que o valor por trade ({_fmt_brl(budget)}). Quantidade reduzida.")
        budget = available

    one_lot_cost = lot * limit if limit else None
    if quantity is not None:
        qty = max(0.0, float(quantity))
        if lot > 1 and qty % lot:
            warn("warning", f"Quantidade fora do lote padrão de {lot}. Ordem iria para o mercado fracionário (ações) ou pode ser rejeitada (opções).")
    elif asset == "FUTURO":
        qty = 1.0
    elif limit > 0:
        qty = float(math.floor(budget / limit / lot) * lot)
    else:
        qty = 0.0
    if qty == 0 and quantity is None and one_lot_cost:
        warn("danger", f"Capital insuficiente para 1 lote ({_fmt_qty(lot)} un = {_fmt_brl(one_lot_cost)}). Aumente o valor por trade ou ignore.")

    gross = round(qty * limit, 2)
    fees = estimate_fees(asset, gross, prefs) if qty else 0.0
    total = round(gross + fees, 2) if is_buy else round(gross - fees, 2)
    pct_capital = round(total / capital * 100, 2) if capital > 0 and qty else None

    # ---------------- risco
    stop = signal.get("stop_loss")
    if stop and qty:
        per_unit = (limit - float(stop)) if is_buy else (float(stop) - limit)
        max_loss = round(max(per_unit, 0) * qty + fees * 2, 2)
        max_loss_note = f"Até o stop do analista ({_fmt_brl(float(stop))})"
    elif asset == "OPCAO" and is_buy and qty:
        max_loss = total
        max_loss_note = "Opção comprada sem stop: o prêmio pode virar pó"
    else:
        max_loss = None
        max_loss_note = "Sem stop definido no sinal" if qty else None

    # ---------------- contexto
    now = at or now_brt()
    ms = market_status(now)
    if not ms["is_open"]:
        warn("info", f"{ms['label']} — {ms['detail']}.")

    entry_dt = to_brt(signal.get("timestamp_entrada"))
    if entry_dt:
        bd = business_days_between(entry_dt.date(), now.date())
        if bd >= 2:
            warn("warning", f"Sinal aberto há {bd} pregões — a entrada pode estar desatualizada.")

    exp_iso = signal.get("expiration")
    days_to_exp = None
    if exp_iso:
        exp = date.fromisoformat(exp_iso)
        days_to_exp = business_days_between(now.date(), exp)
        if days_to_exp <= 3:
            warn("danger", f"Opção vence em {days_to_exp} pregão(ões) ({exp.strftime('%d/%m')}).")
        elif days_to_exp <= 7:
            warn("warning", f"Opção vence em {days_to_exp} pregões ({exp.strftime('%d/%m')}).")

    if asset in ("FUTURO", "FOREX", "INDICE", "COMMODITY", "CRIPTO"):
        warn("warning", "Ativo de giro rápido/fora do Home Broker de ações — difícil copiar manualmente.")
    if trader_profile and trader_profile.get("copyable") == "no":
        warn("warning", f"{signal.get('trader')} opera majoritariamente intraday neste tipo de ativo — cópia manual tende a chegar atrasada.")

    ticket = {
        "signal_id": signal.get("id"),
        "ticker": signal.get("ticker"),
        "underlying": signal.get("underlying"),
        "asset_class": asset,
        "side": side,
        "side_label": "COMPRA" if is_buy else "VENDA",
        "entry_price": entry or None,
        "current_price": current,
        "drift_pct": drift_pct,
        "limit_price": limit,
        "worst_price": worst,
        "lot": lot,
        "quantity": qty,
        "budget": round(budget, 2),
        "one_lot_cost": round(one_lot_cost, 2) if one_lot_cost else None,
        "gross": gross,
        "fees_estimate": fees,
        "total": total,
        "pct_capital": pct_capital,
        "max_loss": max_loss,
        "max_loss_note": max_loss_note,
        "days_to_expiration": days_to_exp,
        "market": ms,
        "warnings": warnings,
        "can_execute": qty > 0,
    }
    ticket["copy_text"] = copy_text(ticket, signal, prefs)
    return ticket


def copy_text(ticket: Dict[str, Any], signal: Dict[str, Any], prefs: Dict[str, Any]) -> str:
    validity = prefs["broker"].get("order_validity") or "Dia"
    desc = ticket["ticker"]
    if ticket["asset_class"] == "OPCAO":
        kind = "CALL" if (signal.get("opcao_tipo") or "").upper() == "CALL" else "PUT" if signal.get("opcao_tipo") else "opção"
        extra = []
        if signal.get("underlying"):
            extra.append(signal["underlying"])
        if signal.get("strike"):
            extra.append(f"strike {signal['strike']:.2f}".replace(".", ","))
        if signal.get("expiration"):
            extra.append(f"venc. {date.fromisoformat(signal['expiration']).strftime('%d/%m')}")
        desc += f" ({kind} {' · '.join(extra)})" if extra else ""
    lines = [
        f"{ticket['side_label']} {desc}",
        f"Quantidade: {_fmt_qty(ticket['quantity'])}",
        f"Preço limite: {_fmt_brl(ticket['limit_price'])}" + (f" (máx. aceitável {_fmt_brl(ticket['worst_price'])})" if ticket.get("worst_price") else ""),
        f"Validade: {validity}",
        f"Total estimado: {_fmt_brl(ticket['gross'])} + custos {_fmt_brl(ticket['fees_estimate'])}",
    ]
    entry_dt = to_brt(signal.get("timestamp_entrada"))
    when = entry_dt.strftime("%d/%m %H:%M") if entry_dt and not (entry_dt.hour == 0 and entry_dt.minute == 0) else (entry_dt.strftime("%d/%m") if entry_dt else "")
    lines.append(f"Sinal: {signal.get('trader')} · entrada {_fmt_brl(ticket['entry_price'])} · {when}".rstrip(" ·"))
    return "\n".join(lines)


def exit_ticket(position: Dict[str, Any], signal: Optional[Dict[str, Any]], prefs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Boleta de saída para uma posição minha (zerar)."""
    prefs = prefs or get_prefs()
    qty = abs(float(position["qty"]))
    side = "SELL" if position["side"] == "LONG" else "BUY"
    ref = None
    if signal and signal.get("preco_saida"):
        ref = float(signal["preco_saida"])
    elif position.get("last_price") is not None:
        ref = float(position["last_price"])
    gross = round(qty * ref, 2) if ref else None
    fees = estimate_fees(position["asset_class"], gross or 0.0, prefs) if gross else 0.0
    lines = [
        f"{'VENDA' if side == 'SELL' else 'COMPRA'} {position['ticker']} (zerar posição)",
        f"Quantidade: {_fmt_qty(qty)}",
        f"Preço de referência: {_fmt_brl(ref)}" + (" (saída do analista)" if signal and signal.get("preco_saida") else ""),
        f"Validade: {prefs['broker'].get('order_validity') or 'Dia'}",
    ]
    return {
        "ticker": position["ticker"],
        "side": side,
        "side_label": "VENDA" if side == "SELL" else "COMPRA",
        "quantity": qty,
        "reference_price": ref,
        "gross": gross,
        "fees_estimate": fees,
        "copy_text": "\n".join(lines),
    }
