"""
Automação (Fase 6, etapa 2): quando ARMADA, envia sozinha as entradas de sinais novos e as saídas
de posições cujo sinal foi encerrado — sempre dentro dos limites diários.

Regras de entrada (todas precisam passar):
- analista/classe seguidos; só opções e ações; analista "copiável" (se exigido);
- sinal visto pela primeira vez há poucos minutos (não entra em sinal velho);
- pregão aberto; nenhuma posição ou ordem aberta no mesmo ativo;
- boleta com quantidade > 0 e preço atual dentro do slippage aceitável;
- limites: entradas automáticas/dia, perda do dia, valor por ordem, exposição máxima.
Toda decisão (enviou/bloqueou) vai para automation_log e vira alerta.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core import db
from src.core.config import get_prefs, now_iso, now_utc
from src.core.market_hours import market_status
from src.execution import orders
from src.services import alerts, journal, performance, portfolio, signals
from src.services.sizing import _round_tick, build_ticket

log = logging.getLogger("copiloto.automation")


def _log(account: str, action: str, decision: str, reason: str, signal_id: Optional[str] = None,
         order_id: Optional[int] = None, ticker: Optional[str] = None) -> None:
    with db.transaction() as c:
        c.execute("INSERT INTO automation_log(at, account, action, decision, signal_id, order_id, ticker, reason) VALUES(?,?,?,?,?,?,?,?)",
                  (now_iso(), account, action, decision, signal_id, order_id, ticker, reason))
        acct = " (simulação)" if account == "paper" else ""
        what = f"{action} {ticker}".strip() if ticker else action
        if decision == "sent":
            alerts.create_alert(c, "auto_order", f"Automação{acct}: {what}", reason, signal_id=signal_id, ticker=ticker,
                                severity="action", dedup_key=f"auto:{action}:{signal_id or ticker}:{order_id or now_iso()}")
        else:
            alerts.create_alert(c, "auto_blocked", f"Automação{acct} não enviou {what}", reason, signal_id=signal_id,
                                ticker=ticker, severity="info", dedup_key=f"autoblock:{action}:{signal_id or ticker}")


def recent_log(limit: int = 30) -> List[Dict[str, Any]]:
    with db.connection() as c:
        return [dict(r) for r in c.execute("SELECT * FROM automation_log ORDER BY id DESC LIMIT ?", (limit,))]


def _profiles() -> Dict[Any, Dict[str, Any]]:
    return {(p["trader"].lower(), p["asset_class"]): p for p in performance.trader_profiles()}


def evaluate_entry(sig: Dict[str, Any], prefs: Dict[str, Any], account: str, open_idx: Dict[str, List[Dict[str, Any]]],
                   held: set, profiles: Dict[Any, Dict[str, Any]]) -> Dict[str, Any]:
    """Decide se a automação entra no sinal. Retorna {'ok', 'reason', 'ticket'}."""
    auto = prefs["execution"]["auto"]
    if sig["status"] != "OPEN":
        return {"ok": False, "reason": "Sinal já encerrado."}
    if not signals.is_followed(sig, prefs):
        return {"ok": False, "reason": "Analista/classe não seguidos."}
    if sig["asset_class"] not in ("OPCAO", "ACAO"):
        return {"ok": False, "reason": "Automação só opera opções e ações."}
    if sig.get("is_baseline"):
        return {"ok": False, "reason": "Sinal anterior ao início do monitor."}
    first_seen = datetime.fromisoformat(sig["first_seen_at"])
    age_min = (now_utc() - first_seen).total_seconds() / 60
    if age_min > auto["max_signal_age_minutes"]:
        return {"ok": False, "reason": f"Sinal visto há {age_min:.0f} min (máximo {auto['max_signal_age_minutes']} min)."}
    profile = profiles.get((sig["trader"].lower(), sig["asset_class"]))
    if auto["only_copyable"] and (not profile or profile.get("copyable") != "yes"):
        return {"ok": False, "reason": f"{sig['trader']} não é classificado como copiável nessa classe."}
    if not market_status()["is_open"]:
        return {"ok": False, "reason": "Pregão fechado."}
    if sig["ticker"] in held or open_idx.get(f"ticker:{sig['ticker']}") or open_idx.get(sig["id"]):
        return {"ok": False, "reason": "Já existe posição ou ordem aberta nesse ativo."}
    if sig.get("decision") and sig["decision"]["status"] == "ignored":
        return {"ok": False, "reason": "Você marcou o sinal como ignorado."}

    exposure = portfolio.exposure(account=account)
    ticket = build_ticket(sig, prefs, exposure=exposure, trader_profile=profile)
    if not ticket["can_execute"]:
        return {"ok": False, "reason": "Boleta sem quantidade (capital insuficiente para 1 lote).", "ticket": ticket}
    danger = [w["text"] for w in ticket["warnings"] if w["level"] == "danger" and ("acima" in w["text"] or "abaixo" in w["text"] or "vence" in w["text"])]
    if danger:
        return {"ok": False, "reason": danger[0], "ticket": ticket}
    return {"ok": True, "reason": "Regras atendidas.", "ticket": ticket}


def run(monitor_result: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Chamada a cada ciclo do monitor. Sincroniza ordens; se armada, envia entradas/saídas."""
    actions: List[Dict[str, Any]] = []
    try:
        if orders.list_orders(only_open=True, limit=1):
            orders.sync_open_orders()
        orders.refresh_quotes_from_broker()
    except Exception as exc:  # nunca derrubar o monitor
        log.warning("Falha ao sincronizar ordens: %s", exc)

    prefs = get_prefs()
    state = orders.execution_state(prefs)
    if not state["armed"]:
        return actions
    account = state["account"]
    auto = prefs["execution"]["auto"]
    open_idx = orders.open_orders_index(account)
    slip = prefs["sizing"]["max_slippage_pct"] / 100

    # ---- saídas: posição minha cujo sinal foi encerrado
    if auto["exits"]:
        for p in portfolio.positions(account=account):
            if not p["exit_pending"] or open_idx.get(f"cycle:{p['cycle_id']}") or open_idx.get(f"ticker:{p['ticker']}"):
                continue
            sig = p.get("signal") or {}
            ref = sig.get("preco_saida") or p.get("last_price")
            side = "SELL" if p["side"] == "LONG" else "BUY"
            if not ref:
                _log(account, "saída", "blocked", "Sem preço de referência para a saída.", sig.get("id"), None, p["ticker"])
                continue
            limit = _round_tick(ref * (1 - slip), up=True) if side == "SELL" else _round_tick(ref * (1 + slip), up=False)
            try:
                o = orders.submit(ticker=p["ticker"], side=side, quantity=p["quantity"], order_type="limit", limit_price=limit,
                                  purpose="exit", origin="auto", signal_id=sig.get("id"), cycle_id=p["cycle_id"], prefs=prefs)
                _log(account, "saída", "sent", f"{side} {p['quantity']:.0f} @ limite {limit:.2f} (analista saiu a {ref:.2f})",
                     sig.get("id"), o["id"], p["ticker"])
                actions.append({"type": "exit", "order": o})
            except ValueError as exc:
                _log(account, "saída", "blocked", str(exc), sig.get("id"), None, p["ticker"])

    # ---- entradas: sinais novos deste ciclo
    if auto["entries"] and monitor_result:
        held = {p["ticker"] for p in journal.ledger(None, account)["positions"]}
        profiles = _profiles()
        for sid in monitor_result.get("new", []):
            sig = signals.get_signal(sid)
            if not sig:
                continue
            ev = evaluate_entry(sig, prefs, account, open_idx, held, profiles)
            if not ev["ok"]:
                if signals.is_followed(sig, prefs):
                    _log(account, "entrada", "blocked", ev["reason"], sid, None, sig["ticker"])
                continue
            t = ev["ticket"]
            try:
                o = orders.submit(ticker=sig["ticker"], side=sig["lado"], quantity=t["quantity"], order_type="limit",
                                  limit_price=t["limit_price"], purpose="entry", origin="auto", signal_id=sid, prefs=prefs)
                held.add(sig["ticker"])
                _log(account, "entrada", "sent", f"{t['side_label']} {t['quantity']:.0f} @ limite {t['limit_price']:.2f} "
                     f"(entrada do analista {t['entry_price']:.2f})", sid, o["id"], sig["ticker"])
                actions.append({"type": "entry", "order": o})
            except ValueError as exc:
                _log(account, "entrada", "blocked", str(exc), sid, None, sig["ticker"])
    return actions


def panic() -> Dict[str, Any]:
    """Desarma a automação e cancela todas as ordens abertas."""
    from src.core.config import update_prefs

    prefs = get_prefs()
    prefs["execution"]["auto"]["armed"] = False
    update_prefs({"execution": prefs["execution"]})
    n = orders.cancel_all()
    _log(orders.execution_state()["account"], "pânico", "sent", f"Automação desarmada; {n} ordem(ns) cancelada(s).")
    return {"cancelled": n}
