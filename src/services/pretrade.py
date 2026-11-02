"""
Checagem pré-trade com tamanho pelo RISCO — adaptado do trader-budget + trader-risk (day-trader-skill, MIT).

O Copiloto já dimensiona por valor (sizing.build_ticket) e confere capital/exposição (execution.risk). O que faltava
para copiar sinal com disciplina: o stop é MEU (o TradingFloors não publica stop) e, com ele,
  quantidade = menor entre (valor por trade ÷ preço) e (risco máximo por trade ÷ perda por unidade até o stop),
               arredondada para baixo no lote, já contando os custos de ida e volta;
  R:R conferido contra o acerto que ele exige para empatar, 1/(1+R). Um R:R baixo não é defeito por si: quem acerta
  muito (ex.: vendedor de opção) vive de R:R < 1. Por isso, havendo histórico do analista, compara-se com o acerto
  dele; sem histórico, vale o rr_min.
Nada aqui envia ordem: devolve a quantidade e APROVADO/BLOQUEADO com os motivos.
"""
import math
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from src.core import b3_tickers
from src.core.market_hours import business_days_between, market_status, now_brt
from src.services import similar
from src.services.journal import estimate_fees

DEFAULT_LIMITS: Dict[str, Any] = {
    "risco_max_trade": 100.0,       # R$ perdidos se o stop executar (1% de R$ 10 mil)
    "perda_max_dia": 300.0,         # R$: perda realizada no dia + risco deste trade
    "rr_min": 1.0,                  # R:R mínimo quando não há histórico do analista
    "margem_acerto": 5.0,           # p.p. de folga do acerto histórico sobre o acerto de empate
    "min_historico": 20,            # operações do analista para usar o acerto dele
    "exige_stop": True,
    "entradas_max_dia": 3,
    "sem_entrada_antes": "10:15",
    "sem_entrada_depois": "16:30",
    "dias_min_vencimento": 5,       # opções
}
POINT_VALUE = {"WIN": 0.20, "WDO": 10.0, "IND": 1.0, "DOL": 50.0}


def _brl(v: Optional[float]) -> str:
    if v is None:
        return "—"
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if v < 0 else ''}R$ {s}"


def _n(v: Optional[float], d: int = 2) -> str:
    return "—" if v is None else f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _hhmm(text: str) -> int:
    hh, mm = str(text).split(":")[:2]
    return int(hh) * 60 + int(mm)


def multiplier(ticker: str, asset: str) -> float:
    if asset == "FUTURO":
        for prefix, v in POINT_VALUE.items():
            if ticker.startswith(prefix):
                return v
    return 1.0


def size_by_risk(*, ticker: str, asset: str, entry: float, stop: float, lot: int, max_risk: float,
                 budget: float, prefs: Dict[str, Any]) -> Dict[str, Any]:
    mult = multiplier(ticker, asset)
    per_unit = abs(entry - stop) * mult

    def risk_of(q: float) -> float:
        return q * per_unit + 2 * estimate_fees(asset, q * entry * mult, prefs) if q else 0.0

    q_budget = float(math.floor(budget / (entry * mult) / lot) * lot) if entry > 0 else 0.0
    q_risk = float(math.floor(max_risk / per_unit / lot) * lot) if per_unit > 0 else 0.0
    while q_risk > 0 and risk_of(q_risk) > max_risk + 1e-9:
        q_risk -= lot
    qty = min(q_budget, q_risk)
    return {
        "qty": qty,
        "qty_budget": q_budget,
        "qty_risk": q_risk,
        "per_unit": round(per_unit, 4),
        "one_lot_risk": round(risk_of(lot), 2),
        "one_lot_cost": round(lot * entry * mult, 2),
        "risk_brl": round(risk_of(qty), 2),
        "value": round(qty * entry * mult, 2),
        "limited_by": "risco" if q_risk < q_budget else "valor por trade",
    }


def context(account: str = "real", conn=None) -> Dict[str, Any]:
    """Posições, perda realizada e entradas de hoje, a partir das execuções do Copiloto."""
    from src.services import journal

    today = now_brt().date().isoformat()
    execs = journal.list_executions(account=account, conn=conn)
    if not execs:  # banco sem execuções (ex.: cópia de desenvolvimento): carteira desconhecida, não "zerada"
        return {"positions": None, "realized_today": 0.0, "entries_today": None, "exposure": 0.0}
    led = journal.ledger(conn, account)
    return {
        "positions": led["positions"],
        "realized_today": round(sum(e["pnl"] for e in led["events"] if e["date"] == today), 2),
        "entries_today": sum(1 for e in execs if str(e.get("executed_at") or "")[:10] == today and e["side"] == "BUY"),
        "exposure": round(sum(p["invested"] for p in led["positions"]), 2),
    }


def check(*, ticker: str, side: str, entry: float, stop: Optional[float], target: Optional[float] = None,
          prefs: Dict[str, Any], limits: Optional[Dict[str, Any]] = None, asset_class: Optional[str] = None,
          ctx: Optional[Dict[str, Any]] = None, analyst: Optional[Dict[str, Any]] = None,
          expiration: Optional[str] = None, opcao_tipo: Optional[str] = None, signal_id: Optional[str] = None,
          ref_entry: Optional[float] = None, at: Optional[datetime] = None) -> Dict[str, Any]:
    """ref_entry = entrada do analista: andar mais que sizing.max_slippage_pct contra mim é perseguir preço."""
    lim = {**DEFAULT_LIMITS, **(limits or {})}
    tk = b3_tickers.clean_ticker(ticker)
    asset = asset_class or b3_tickers.asset_class(None, tk)
    side = "SELL" if str(side).upper() in ("SELL", "VENDA", "V") else "BUY"
    is_buy = side == "BUY"
    blocks: List[str] = []
    warns: List[str] = []
    info: List[str] = []
    capital = float(prefs["capital"]["total"])
    sz = prefs["sizing"]
    budget = float(sz["value_per_trade"]) if sz["mode"] == "fixed_capital" else capital * float(sz["pct_per_trade"]) / 100
    lot = 1 if asset in ("FUTURO", "FOREX", "INDICE", "COMMODITY", "CRIPTO") else int(sz.get("lot_step") or b3_tickers.default_lot(asset))
    out: Dict[str, Any] = {"ticker": tk, "side": side, "asset_class": asset, "entry": entry, "stop": stop, "target": target,
                           "lot": lot, "budget": round(budget, 2), "limits": lim}

    # ---------------- stop e tamanho
    if stop is None:
        (blocks if lim["exige_stop"] else warns).append("Sem stop: o TradingFloors não publica, defina o seu (plano da Máquina do Tempo, histórico do analista ou ATR).")
        out.update({"qty": 0.0, "risk_brl": None, "rr": None, "breakeven_win": None})
    elif (is_buy and stop >= entry) or (not is_buy and stop <= entry):
        blocks.append(f"Stop {_n(stop)} do lado errado da entrada {_n(entry)} ({'compra: stop abaixo' if is_buy else 'venda: stop acima'}).")
        out.update({"qty": 0.0, "risk_brl": None, "rr": None, "breakeven_win": None})
    else:
        s = size_by_risk(ticker=tk, asset=asset, entry=entry, stop=stop, lot=lot, max_risk=float(lim["risco_max_trade"]),
                         budget=budget, prefs=prefs)
        out.update(s)
        if s["qty_budget"] == 0:
            blocks.append(f"Capital por trade ({_brl(budget)}) não compra 1 lote ({_n(lot, 0)} un = {_brl(s['one_lot_cost'])}).")
        if s["qty_risk"] == 0:
            blocks.append(f"1 lote já arrisca {_brl(s['one_lot_risk'])} até o stop, acima do risco máximo por trade "
                          f"({_brl(lim['risco_max_trade'])}): stop largo demais para o lote.")
        elif s["limited_by"] == "risco" and s["qty_budget"] > 0:
            info.append(f"Quantidade limitada pelo risco: {_n(s['qty'], 0)} em vez de {_n(s['qty_budget'], 0)} pelo valor por trade.")

        # ---------------- R:R contra o acerto exigido
        out["rr"] = out["breakeven_win"] = None
        if target is None:
            warns.append("Sem alvo: R:R não conferido.")
        elif (is_buy and target <= entry) or (not is_buy and target >= entry):
            blocks.append(f"Alvo {_n(target)} do lado errado da entrada {_n(entry)}.")
        else:
            rr = abs(target - entry) / abs(entry - stop)
            be = 100 / (1 + rr)
            out["rr"], out["breakeven_win"] = round(rr, 2), round(be, 1)
            n_hist = (analyst or {}).get("closed") or 0
            wr = (analyst or {}).get("win_rate")
            if wr is not None and n_hist >= lim["min_historico"]:
                who = analyst.get("trader") or "o analista"
                txt = (f"R:R {_n(rr)} exige acerto ≥ {_n(be, 0)}% para empatar; {who} acerta {_n(wr, 1)}% em {n_hist} "
                       f"operações (com as saídas dele, não com este stop/alvo).")
                if wr >= be + lim["margem_acerto"]:
                    info.append(txt)
                else:
                    blocks.append(txt)
            elif rr < lim["rr_min"]:
                blocks.append(f"R:R {_n(rr)} abaixo do mínimo {_n(lim['rr_min'])} (sem histórico suficiente do analista para justificar).")

    # ---------------- perseguindo preço (mesmo limite da boleta do Copiloto)
    if ref_entry and ref_entry > 0 and entry != ref_entry:
        drift = (entry / ref_entry - 1) * 100
        adverse = drift if is_buy else -drift
        out["drift_pct"] = round(drift, 2)
        max_slip = float(sz["max_slippage_pct"])
        if adverse > max_slip:
            blocks.append(f"Preço já andou {_n(abs(drift), 1)}% contra desde a entrada do analista ({_n(ref_entry)}); limite "
                          f"{_n(max_slip, 1)}% (Configurações > tamanho). Copiar agora é outro trade, com outro R:R.")

    # ---------------- limites do dia
    ctx = ctx or {}
    realized = float(ctx.get("realized_today") or 0.0)
    risk_brl = out.get("risk_brl") or 0.0
    if lim["perda_max_dia"] > 0:
        if realized <= -lim["perda_max_dia"]:
            blocks.append(f"Perda do dia ({_brl(realized)}) já atingiu o limite de {_brl(lim['perda_max_dia'])}.")
        elif realized - risk_brl < -lim["perda_max_dia"] - 1e-9:
            blocks.append(f"Se o stop executar, a perda do dia vai a {_brl(realized - risk_brl)} (limite {_brl(lim['perda_max_dia'])}).")
    if ctx.get("entries_today") is not None and ctx["entries_today"] >= lim["entradas_max_dia"]:
        blocks.append(f"Já foram {ctx['entries_today']} entradas hoje (máximo {lim['entradas_max_dia']}).")

    now = at or now_brt()
    ms = market_status(now)
    minute = now.hour * 60 + now.minute
    if not ms["is_open"]:
        warns.append(f"{ms['label']}: planeje para o próximo pregão e confira o preço na abertura.")
    elif minute < _hhmm(lim["sem_entrada_antes"]) or minute > _hhmm(lim["sem_entrada_depois"]):
        warns.append(f"Fora da janela de entradas ({lim['sem_entrada_antes']}–{lim['sem_entrada_depois']}).")

    if asset == "OPCAO":
        exp = expiration or (b3_tickers.decode_option(tk, now.date()) or {}).get("expiration")
        if exp:
            days = business_days_between(now.date(), date.fromisoformat(exp))
            out["days_to_expiration"] = days
            if days < lim["dias_min_vencimento"]:
                blocks.append(f"Opção vence em {days} pregão(ões) ({date.fromisoformat(exp):%d/%m}); mínimo {lim['dias_min_vencimento']}.")

    positions = ctx.get("positions")
    if positions is None:
        warns.append("Nenhuma execução no banco: carteira, perda do dia, entradas de hoje, venda a descoberto e trades "
                     "semelhantes não conferidos (rode no servidor ou passe --db com uma cópia do app.db).")
    else:
        held = next((p["qty"] for p in positions if p["ticker"] == tk), 0.0)
        if not is_buy and held <= 0 and asset in ("ACAO", "OPCAO"):
            blocks.append("Venda sem posição (a descoberto) não é permitida pelo Copiloto.")
        sim = similar.find({"id": signal_id, "ticker": tk, "asset_class": asset, "lado": side, "opcao_tipo": opcao_tipo}, positions)
        if sim:
            warns.append(f"Atenção: {similar.describe(sim)}.")
        exposure = float(ctx.get("exposure") or 0.0)
        value = out.get("value") or 0.0
        max_exp = float(prefs["execution"]["auto"]["max_exposure_pct"])
        if capital > 0 and value and exposure + value > capital + 1e-6:
            warns.append(f"Valor ({_brl(value)}) maior que o capital livre ({_brl(capital - exposure)}).")
        elif capital > 0 and value and (exposure + value) / capital * 100 > max_exp:
            warns.append(f"Exposição passaria de {max_exp:.0f}% do capital.")

    out.update({"ok": not blocks, "blocks": blocks, "warnings": warns, "info": info})
    return out


def report(res: Dict[str, Any]) -> str:
    lado = "COMPRA" if res["side"] == "BUY" else "VENDA"
    lines = [f"{'APROVADO' if res['ok'] else 'BLOQUEADO'} — {lado} {res['ticker']} a {_n(res['entry'])}"
             + (f", stop {_n(res['stop'])}" if res.get("stop") else "") + (f", alvo {_n(res['target'])}" if res.get("target") else "")]
    if res.get("qty") is not None and res.get("per_unit") is not None:
        lines.append(f"  Quantidade {_n(res['qty'], 0)} (lote {res['lot']}; pelo valor {_n(res['qty_budget'], 0)}, pelo risco {_n(res['qty_risk'], 0)})"
                     f" · valor {_brl(res['value'])} · perda no stop {_brl(res['risk_brl'])} (limite {_brl(res['limits']['risco_max_trade'])})")
    if res.get("rr") is not None:
        lines.append(f"  R:R {_n(res['rr'])} → empata com {_n(res['breakeven_win'], 0)}% de acerto")
    lines += [f"  ✖ {b}" for b in res["blocks"]]
    lines += [f"  ! {w}" for w in res["warnings"]]
    lines += [f"  · {i}" for i in res["info"]]
    return "\n".join(lines)


__all__ = ["DEFAULT_LIMITS", "size_by_risk", "context", "check", "report"]
