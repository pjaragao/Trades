"""Monitor de sinais: baseline sem alertas, novo sinal, saída pendente, opção sumida de opcoes_trades."""
from src.core import db
from src.services import alerts, journal
from src.services.signal_monitor import SignalMonitor
from tests.conftest import FakeAPI, opcao_row, trade_row


def kinds():
    return [a["kind"] for a in alerts.list_alerts(limit=100)]


def test_first_run_is_baseline_without_alerts(tmp_db):
    api = FakeAPI([trade_row("t1", "VIVAJ241", preco=1.29)], [opcao_row("o1", "VIVAJ241", preco=1.29, atual=1.52)])
    m = SignalMonitor(api_factory=lambda: api, poll_seconds=5)
    res = m.run_cycle()
    assert res["history"]["signals"] == 1
    assert kinds() == []
    assert m.status()["state"] == "live"


def test_new_followed_signal_creates_alert_and_unfollowed_does_not(tmp_db):
    api = FakeAPI([trade_row("t1", "VIVAJ241")])
    m = SignalMonitor(api_factory=lambda: api, poll_seconds=5)
    m.run_cycle()
    api.trades.append(trade_row("t2", "NATUK800", trader="Sanita", ts="2026-10-05T14:00:00+00:00"))
    api.trades.append(trade_row("t3", "WINFUT", trader="Brondi", tipo="Futuros (B3)", produto="Trading Floor"))
    res = m.run_cycle()
    assert set(res["new"]) == {"t2", "t3"}
    al = alerts.list_alerts()
    assert [a["signal_id"] for a in al if a["kind"] == "new_signal"] == ["t2"]


def test_exit_pending_when_i_hold_the_position(tmp_db):
    t = trade_row("t1", "BBASJ216", trader="Ferri", preco=1.27)
    api = FakeAPI([t])
    m = SignalMonitor(api_factory=lambda: api, poll_seconds=5)
    m.run_cycle()
    journal.add_execution({"signal_id": "t1", "ticker": "BBASJ216", "side": "BUY", "quantity": 800, "price": 1.28,
                           "executed_at": "2026-09-28T13:30:00-03:00"})
    t.update(status="CLOSED", preco_saida=3.0, timestamp_saida="2026-10-05T15:00:00+00:00", updated_at="2099-01-01T00:00:00+00:00")
    res = m.run_cycle()
    assert res["closed"] == ["t1"]
    exit_alerts = [a for a in alerts.list_alerts() if a["kind"] == "exit_pending"]
    assert len(exit_alerts) == 1 and "800" in exit_alerts[0]["body"]


def test_closed_signal_found_by_id_when_not_in_updated_feed(tmp_db):
    t = trade_row("t1", "IRBRJ646", trader="Artur Horta", preco=2.15)
    api = FakeAPI([t])
    m = SignalMonitor(api_factory=lambda: api, poll_seconds=5)
    m.run_cycle()
    t.update(status="CLOSED", preco_saida=1.7, updated_at="2000-01-01T00:00:00+00:00")  # updated_at antigo
    res = m.run_cycle()
    assert res["closed"] == ["t1"]
    with db.connection() as c:
        assert c.execute("SELECT status, preco_saida FROM signals WHERE id='t1'").fetchone()["preco_saida"] == 1.7


def test_opcao_only_signal_closes_when_it_disappears(tmp_db):
    o = opcao_row("o1", "CEABJ102", preco=0.42, ts="2026-09-30T16:26:00+00:00")
    api = FakeAPI([], [o])
    m = SignalMonitor(api_factory=lambda: api, poll_seconds=5)
    m.run_cycle()
    api.opcoes.clear()
    api.trades.append(trade_row("t9", "CEABJ102", preco=0.42, status="CLOSED", saida=0.65,
                                ts="2026-09-30T16:26:00+00:00", ts_saida="2026-10-05T15:00:00+00:00",
                                updated_at="2000-01-01T00:00:00+00:00"))
    res = m.run_cycle()
    assert res["closed"] == ["o1"]
    with db.connection() as c:
        rows = c.execute("SELECT id, trades_id, status, preco_saida FROM signals").fetchall()
    assert len(rows) == 1 and rows[0]["trades_id"] == "t9" and rows[0]["preco_saida"] == 0.65


def test_api_failure_marks_offline(tmp_db):
    class Broken(FakeAPI):
        def fetch_all(self):
            from src.integrations.tradingfloors import TFError
            raise TFError("Sem conexão")

    m = SignalMonitor(api_factory=lambda: Broken(), poll_seconds=5)
    assert m.run_cycle() == {}
    st = m.status()
    assert st["state"] == "offline" and "Sem conexão" in st["last_error"]
