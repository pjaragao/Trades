"""
Monitor de sinais sempre ativo (substitui o "Iniciar/Parar robô").

A cada ciclo:
1. Busca abertos em `trades` e `opcoes_trades` + linhas de `trades` atualizadas recentemente.
2. Mescla (dedup única) e reconcilia com o banco.
3. Sinais abertos no banco que não vieram no poll são conferidos um a um (encerrados/removidos).
4. Gera alertas: novo sinal (analistas seguidos), saída pendente (tenho posição), lembretes,
   stop/alvo, vencimento próximo de opção em carteira.

Na primeira execução baixa o histórico completo e marca tudo como "baseline" (sem alertas).
"""
import logging
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from src.core import db
from src.core.config import get_prefs, monitor_poll_seconds, now_iso, now_utc
from src.core.market_hours import business_days_between, market_status, now_brt, to_brt
from src.integrations.tradingfloors import TFError, TradingFloorsAPI, get_client, merge_rows
from src.services import alerts, journal, performance, portfolio
from src.services.legacy_import import import_legacy_cache
from src.services.signals import hydrate, is_followed, mark_closed, upsert_signals

log = logging.getLogger("copiloto.monitor")

HISTORY_RESYNC_HOURS = 12
UPDATED_LOOKBACK_MINUTES = 30


def _fmt_price(v: Optional[float]) -> str:
    return "—" if v is None else f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class SignalMonitor:
    def __init__(self, api_factory: Callable[[], TradingFloorsAPI] = get_client, poll_seconds: Optional[int] = None):
        self.api_factory = api_factory
        self.poll_seconds = poll_seconds
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._cycle_lock = threading.Lock()
        self._state: Dict[str, Any] = {
            "state": "starting",
            "last_ok_at": None,
            "last_attempt_at": None,
            "last_error": None,
            "consecutive_errors": 0,
            "last_result": None,
        }

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="signal-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def trigger(self) -> None:
        self._wake.set()

    def interval(self) -> int:
        base = self.poll_seconds or monitor_poll_seconds()
        phase = market_status()["phase"]
        return base if phase != "closed" else max(60, base * 3)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.run_cycle()
            self._wake.wait(self.interval())
            self._wake.clear()

    # ------------------------------------------------------------------ status
    def status(self) -> Dict[str, Any]:
        st = dict(self._state)
        st["history_synced_at"] = db.kv_get("history_synced_at")
        st["baseline_at"] = db.kv_get("baseline_at")
        st["interval_seconds"] = self.interval()
        last_ok = st.get("last_ok_at") or db.kv_get("last_poll_ok_at")
        st["last_ok_at"] = last_ok
        if last_ok:
            age = (now_utc() - datetime.fromisoformat(last_ok)).total_seconds()
            st["age_seconds"] = int(age)
            if st["state"] not in ("no_credentials",):
                if age <= max(90, 3 * st["interval_seconds"]):
                    st["state"] = "live" if st["consecutive_errors"] == 0 else "degraded"
                else:
                    st["state"] = "stale"
        elif st["state"] == "starting" and st["consecutive_errors"]:
            st["state"] = "offline"
        st["running"] = bool(self._thread and self._thread.is_alive())
        return st

    # ------------------------------------------------------------------ execução
    def run_cycle(self) -> Dict[str, Any]:
        with self._cycle_lock:
            self._state["last_attempt_at"] = now_iso()
            api = self.api_factory()
            if not api.configured:
                self._state.update(state="no_credentials", last_error="Configure TF_EMAIL e TF_PASSWORD em config/.env")
                return {}
            try:
                result: Dict[str, Any] = {}
                if self._needs_history():
                    result["history"] = self.sync_history(api)
                result.update(self.poll_once(api))
                self._state.update(state="live", last_ok_at=now_iso(), last_error=None, consecutive_errors=0, last_result=_summ(result))
                db.kv_set("last_poll_ok_at", self._state["last_ok_at"])
                self._run_automation(result)
                return result
            except TFError as exc:
                self._fail(str(exc))
            except Exception as exc:  # nunca derrubar a thread
                log.error("Erro no monitor: %s\n%s", exc, traceback.format_exc())
                self._fail(f"Erro interno: {exc}")
            return {}

    def _run_automation(self, result: Dict[str, Any]) -> None:
        """Fase 6: sincroniza ordens abertas e, se armada, deixa a automação agir neste ciclo."""
        try:
            from src.execution import automation

            acts = automation.run(result)
            if acts:
                result["automation"] = [{"type": a["type"], "order_id": a["order"]["id"]} for a in acts]
                alerts.dispatch_pending()
        except Exception as exc:
            log.error("Erro na automação: %s | %s", exc, traceback.format_exc())

    def _fail(self, msg: str) -> None:
        self._state["last_error"] = msg
        self._state["consecutive_errors"] += 1
        self._state["state"] = "offline"

    def _needs_history(self) -> bool:
        synced = db.kv_get("history_synced_at")
        if not synced:
            return True
        return now_utc() - datetime.fromisoformat(synced) > timedelta(hours=HISTORY_RESYNC_HOURS)

    def sync_history(self, api: TradingFloorsAPI) -> Dict[str, Any]:
        trades, opcoes = api.fetch_all()
        merged = merge_rows(trades, opcoes)
        with db.transaction() as c:
            baseline = db.kv_get("baseline_at", conn=c) is None
            res = upsert_signals(c, merged, baseline=baseline)
            out: Dict[str, Any] = {"rows": len(trades) + len(opcoes), "signals": len(merged), "new": len(res["new"]) + len(res["new_closed"])}
            if db.kv_get("legacy_imported", conn=c) is None:
                out["legacy"] = import_legacy_cache(c)
                db.kv_set("legacy_imported", now_iso(), conn=c)
            if baseline:
                db.kv_set("baseline_at", now_iso(), conn=c)
            db.kv_set("history_synced_at", now_iso(), conn=c)
            if not baseline:
                self._alerts_for(c, res)
        performance.invalidate_cache()
        return out

    def poll_once(self, api: TradingFloorsAPI) -> Dict[str, Any]:
        last_ok = db.kv_get("last_poll_ok_at")
        since_dt = (datetime.fromisoformat(last_ok) if last_ok else now_utc() - timedelta(days=1)) - timedelta(minutes=UPDATED_LOOKBACK_MINUTES)
        since = since_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

        open_trades, open_opcoes = api.fetch_open()
        updated = api.fetch_trades_updated_since(since)
        trades_rows = list({r["id"]: r for r in [*updated, *open_trades] if r.get("id")}.values())
        merged = merge_rows(trades_rows, open_opcoes)

        with db.transaction() as c:
            baseline = db.kv_get("baseline_at", conn=c) is None
            res = upsert_signals(c, merged, baseline=baseline)
            seen_open = {sid for sid, st in res["seen"].items() if st == "OPEN"}
            missing = [dict(r) for r in c.execute("SELECT * FROM signals WHERE status = 'OPEN'") if r["id"] not in seen_open]

        if missing:
            res2 = self._resolve_missing(api, missing, opcoes_empty=not open_opcoes)
            for k in ("closed", "new", "new_closed", "updated"):
                res[k].extend(res2.get(k, []))

        with db.transaction() as c:
            if baseline:
                db.kv_set("baseline_at", now_iso(), conn=c)
            else:
                self._alerts_for(c, res)
            self._periodic_alerts(c)
        alerts.dispatch_pending()
        if res["new"] or res["closed"] or res["new_closed"]:
            performance.invalidate_cache()
        return {"new": res["new"], "closed": res["closed"], "updated": len(res["updated"]), "open": len(seen_open)}

    def _resolve_missing(self, api: TradingFloorsAPI, missing: List[Dict[str, Any]], opcoes_empty: bool) -> Dict[str, List[str]]:
        """Abertos no banco que não vieram no poll: busca o estado real (encerrado/removido)."""
        out: Dict[str, List[str]] = {"closed": [], "updated": []}
        with_trades = [m for m in missing if m.get("trades_id")]
        only_opcoes = [m for m in missing if not m.get("trades_id")]

        if with_trades:
            rows = api.fetch_trades_by_ids([m["trades_id"] for m in with_trades])
            found = {r["id"] for r in rows}
            with db.transaction() as c:
                res = upsert_signals(c, merge_rows(rows, []))
                out["closed"] += res["closed"]
                out["updated"] += res["updated"]
                for m in with_trades:
                    if m["trades_id"] not in found:
                        mark_closed(c, m["id"])
                        out["closed"].append(m["id"])

        # Se `opcoes_trades` veio vazio por instabilidade, não encerra nada às cegas.
        if only_opcoes and not (opcoes_empty and len(only_opcoes) >= 3):
            for m in only_opcoes:
                rows = api.fetch_recent_closed(m["ticker"])
                cands = merge_rows(rows, [])
                cands = [s for s in cands if s["trader"].lower() == m["trader"].lower() and s["lado"] == m["lado"]]
                with db.transaction() as c:
                    if cands:
                        res = upsert_signals(c, cands)
                        out["closed"] += [i for i in res["closed"] if i == m["id"]]
                    still_open = c.execute("SELECT status FROM signals WHERE id = ?", (m["id"],)).fetchone()
                    if still_open and still_open["status"] == "OPEN":
                        mark_closed(c, m["id"])
                        out["closed"].append(m["id"])
        out["closed"] = sorted(set(out["closed"]))
        return out

    # ------------------------------------------------------------------ alertas
    def _alerts_for(self, c, res: Dict[str, Any]) -> None:
        prefs = get_prefs(c)
        held = {p["ticker"]: p for p in portfolio.positions(c)}

        for sid in res.get("new", []):
            row = c.execute("SELECT * FROM signals WHERE id = ?", (sid,)).fetchone()
            if not row:
                continue
            sig = hydrate(dict(row), prefs)
            if not is_followed(sig, prefs):
                continue
            verb = "comprou" if sig["lado"] == "BUY" else "vendeu"
            body = f"Entrada {_fmt_price(sig['preco_entrada'])}"
            if sig.get("preco_atual") is not None:
                body += f" · agora {_fmt_price(sig['preco_atual'])}"
            alerts.create_alert(c, "new_signal", f"Novo sinal: {sig['trader']} {verb} {sig['ticker']}", body,
                                signal_id=sid, ticker=sig["ticker"], severity="action", dedup_key=f"new:{sid}")

        for sid in res.get("closed", []):
            row = c.execute("SELECT * FROM signals WHERE id = ?", (sid,)).fetchone()
            if not row:
                continue
            sig = hydrate(dict(row), prefs)
            pos = held.get(sig["ticker"])
            ret = sig.get("return_final_pct")
            ret_txt = f" ({ret:+.1f}%)".replace(".", ",") if ret is not None else ""
            if pos:
                alerts.create_alert(
                    c, "exit_pending", f"Saída pendente: {sig['trader']} encerrou {sig['ticker']}",
                    f"Saída do analista {_fmt_price(sig.get('preco_saida'))}{ret_txt}. Você ainda tem {abs(pos['qty']):,.0f} un.".replace(",", "."),
                    signal_id=sid, ticker=sig["ticker"], severity="action", dedup_key=f"exit:{sid}")
            elif is_followed(sig, prefs):
                alerts.create_alert(c, "signal_closed", f"{sig['trader']} encerrou {sig['ticker']}",
                                    f"Saída {_fmt_price(sig.get('preco_saida'))}{ret_txt}",
                                    signal_id=sid, ticker=sig["ticker"], severity="info", dedup_key=f"closed:{sid}")

    def _periodic_alerts(self, c) -> None:
        now = now_brt()
        # Lembretes de sinais adiados
        for r in c.execute(
            "SELECT d.*, s.ticker, s.trader, s.status FROM decisions d JOIN signals s ON s.id = d.signal_id "
            "WHERE d.status = 'snoozed' AND d.remind_at IS NOT NULL"
        ).fetchall():
            remind = to_brt(r["remind_at"])
            if remind and remind <= now and r["status"] == "OPEN":
                alerts.create_alert(c, "reminder", f"Lembrete: {r['trader']} · {r['ticker']}", "Você pediu para lembrar deste sinal.",
                                    signal_id=r["signal_id"], ticker=r["ticker"], severity="action",
                                    dedup_key=f"reminder:{r['signal_id']}:{r['remind_at']}")

        # Stop/alvo do analista e vencimento próximo nas minhas posições
        for p in portfolio.positions(c):
            sig = p.get("signal")
            for a in p["alerts"]:
                if a.get("kind") == "stop":
                    alerts.create_alert(c, "stop_hit", f"Stop atingido: {p['ticker']}", a["text"], signal_id=sig and sig["id"],
                                        ticker=p["ticker"], severity="danger", dedup_key=f"stop:{p['cycle_id']}")
                elif a.get("kind") == "target":
                    alerts.create_alert(c, "target_hit", f"Alvo atingido: {p['ticker']}", a["text"], signal_id=sig and sig["id"],
                                        ticker=p["ticker"], severity="action", dedup_key=f"target:{p['cycle_id']}")
            if sig and sig.get("expiration"):
                exp = datetime.fromisoformat(sig["expiration"]).date()
                left = business_days_between(now.date(), exp)
                if 0 <= left <= 2:
                    alerts.create_alert(c, "expiry", f"Vencimento próximo: {p['ticker']}",
                                        f"Sua opção vence em {exp.strftime('%d/%m')} ({left} pregão(ões)).",
                                        signal_id=sig["id"], ticker=p["ticker"], severity="danger",
                                        dedup_key=f"expiry:{p['cycle_id']}:{sig['expiration']}")


def _summ(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "new": len(result.get("new", [])),
        "closed": len(result.get("closed", [])),
        "updated": result.get("updated", 0),
        "open": result.get("open"),
        "history": result.get("history"),
        "at": now_iso(),
    }


_monitor: Optional[SignalMonitor] = None


def get_monitor() -> SignalMonitor:
    global _monitor
    if _monitor is None:
        _monitor = SignalMonitor()
    return _monitor
