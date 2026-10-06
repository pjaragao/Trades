"""Baixa automática: o aviso do WhatsApp chega antes, eu já executei — o sinal é vinculado e marcado como executado."""
from datetime import timedelta

from src.core import db
from src.core.config import now_utc
from src.core.market_hours import BRT
from src.services import alerts, auto_link, journal
from src.services.signal_monitor import SignalMonitor
from tests.conftest import FakeAPI, opcao_row, trade_row


def iso_utc(minutes_ago: float) -> str:
    return (now_utc() - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


def iso_brt(minutes_ago: float) -> str:
    return (now_utc() - timedelta(minutes=minutes_ago)).astimezone(BRT).isoformat(timespec="seconds")


def decision(sid):
    with db.connection() as c:
        r = c.execute("SELECT status, reason FROM decisions WHERE signal_id = ?", (sid,)).fetchone()
        return dict(r) if r else None


def boot_monitor(api):
    m = SignalMonitor(api_factory=lambda: api, poll_seconds=5)
    m.run_cycle()  # baseline
    return m


def test_signal_arriving_after_my_execution_is_marked_executed(tmp_db):
    """Caso BEEFJ406: Artur Horta entra 12:19, API mostra 12:20:33 — eu já tinha executado e registrado."""
    api = FakeAPI([trade_row("old", "VIVAJ241")])
    m = boot_monitor(api)
    ex = journal.add_execution({"ticker": "BEEFJ406", "side": "BUY", "quantity": 2000, "price": 0.34, "fees": 0,
                                "executed_at": iso_brt(4)})
    api.trades.append(trade_row("beef", "BEEFJ406", trader="Artur Horta", preco=0.34, ts=iso_utc(3), opcao_id="o-beef"))
    api.opcoes.append(opcao_row("o-beef", "BEEFJ406", trader="Artur Horta", preco=0.34, atual=0.35, ts=iso_utc(3)))
    res = m.run_cycle()
    assert res["new"] == ["beef"]
    assert journal.list_executions(ticker="BEEFJ406")[0]["signal_id"] == "beef"
    assert decision("beef")["status"] == "executed"
    kinds = {a["kind"]: a for a in alerts.list_alerts()}
    assert "new_signal" not in kinds and "signal_executed" in kinds
    assert "Já executado" in kinds["signal_executed"]["title"] and "2.000" in kinds["signal_executed"]["body"]
    assert ex["id"] in [e["id"] for e in journal.list_executions(signal_id="beef")]


def test_old_or_opposite_executions_are_not_linked(tmp_db):
    api = FakeAPI([trade_row("old", "VIVAJ241")])
    m = boot_monitor(api)
    # compra antiga (fora da janela de 30 min) e registrada há tempo
    with db.transaction() as c:
        c.execute("INSERT INTO executions(ticker, side, quantity, price, fees, executed_at, asset_class, created_at, account) "
                  "VALUES('BEEFJ406','BUY',1000,0.30,0,?,'OPCAO',?,'real')", (iso_brt(180), iso_utc(180)))
    api.trades.append(trade_row("beef", "BEEFJ406", trader="Artur Horta", preco=0.34, ts=iso_utc(2)))
    # venda que zera uma compra (saída) não é entrada num sinal de venda
    journal.add_execution({"ticker": "PETRK420", "side": "BUY", "quantity": 100, "price": 1.0, "executed_at": iso_brt(60)})
    journal.add_execution({"ticker": "PETRK420", "side": "SELL", "quantity": 100, "price": 1.2, "executed_at": iso_brt(5)})
    api.trades.append(trade_row("short", "PETRK420", trader="Artur Horta", lado="SELL", preco=1.2, ts=iso_utc(2)))
    m.run_cycle()
    assert decision("beef") is None and decision("short") is None
    assert {a["signal_id"] for a in alerts.list_alerts() if a["kind"] == "new_signal"} == {"beef", "short"}


def test_execution_registered_after_signal_is_linked_on_save(tmp_db):
    from web.app import create_app

    api = FakeAPI([trade_row("old", "VIVAJ241")])
    m = boot_monitor(api)
    api.trades.append(trade_row("beef", "BEEFJ406", trader="Artur Horta", preco=0.34, ts=iso_utc(10)))
    m.run_cycle()
    client = create_app(start_monitor=False, db_path=db.db_path()).test_client()
    r = client.post("/api/executions", json={"ticker": "BEEFJ406", "side": "BUY", "quantity": 2000, "price": 0.35, "fees": 0,
                                             "executed_at": iso_brt(1)[:16]})
    body = r.get_json()
    assert r.status_code == 201 and body["signal_id"] == "beef" and body["linked_signal"]["trader"] == "Artur Horta"
    assert decision("beef")["status"] == "executed"


def test_open_order_is_attached_to_the_new_signal(tmp_db):
    api = FakeAPI([trade_row("old", "VIVAJ241")])
    m = boot_monitor(api)
    with db.transaction() as c:
        c.execute("INSERT INTO orders(account, broker, origin, purpose, ticker, asset_class, side, quantity, order_type, limit_price, "
                  "status, created_at, updated_at) VALUES('real','mt5','manual','entry','BEEFJ406','OPCAO','BUY',2000,'limit',0.34,'open',?,?)",
                  (iso_utc(3), iso_utc(3)))
    api.trades.append(trade_row("beef", "BEEFJ406", trader="Artur Horta", preco=0.34, ts=iso_utc(1)))
    m.run_cycle()
    with db.connection() as c:
        assert c.execute("SELECT signal_id FROM orders").fetchone()[0] == "beef"
    assert decision("beef") is None  # ordem ainda não executada: o sinal continua pendente, mas com a ordem vinculada
    assert any("ordem aberta" in a["body"] for a in alerts.list_alerts() if a["kind"] == "new_signal")


def test_match_window_is_configurable_and_zero_disables(tmp_db):
    from src.core.config import update_prefs

    update_prefs({"follow": {"match_minutes": 0}})
    api = FakeAPI([trade_row("old", "VIVAJ241")])
    m = boot_monitor(api)
    journal.add_execution({"ticker": "BEEFJ406", "side": "BUY", "quantity": 2000, "price": 0.34, "executed_at": iso_brt(4)})
    api.trades.append(trade_row("beef", "BEEFJ406", trader="Artur Horta", preco=0.34, ts=iso_utc(1)))
    m.run_cycle()
    assert decision("beef") is None
    assert auto_link.match_minutes({"follow": {"match_minutes": 0}}) == 0
    # desligado também no registro manual
    with db.transaction() as c:
        assert auto_link.link_execution(c, journal.list_executions(ticker="BEEFJ406")[0]["id"]) is None


def test_sweep_links_existing_unlinked_execution(tmp_db):
    """Sinal que já estava no banco (antes desta versão) + execução sem vínculo: o próximo ciclo dá baixa."""
    api = FakeAPI([trade_row("old", "VIVAJ241")])
    m = boot_monitor(api)
    api.trades.append(trade_row("beef", "BEEFJ406", trader="Artur Horta", preco=0.34, ts=iso_utc(20)))
    with db.transaction() as c:  # inserção direta: simula execução gravada sem a vinculação no registro
        c.execute("INSERT INTO executions(ticker, side, quantity, price, fees, executed_at, asset_class, created_at, account) "
                  "VALUES('BEEFJ406','BUY',2000,0.34,0,?,'OPCAO',?,'real')", (iso_brt(15), iso_utc(15)))
    m.run_cycle()  # o sinal chega (novo) depois da execução: link direto
    assert decision("beef")["status"] == "executed"
    api.trades.append(trade_row("cogn", "COGNK280", trader="Artur Horta", preco=0.22, ts=iso_utc(30)))
    m.run_cycle()
    with db.transaction() as c:
        c.execute("INSERT INTO executions(ticker, side, quantity, price, fees, executed_at, asset_class, created_at, account) "
                  "VALUES('COGNK280','BUY',4700,0.22,0,?,'OPCAO',?,'real')", (iso_brt(5), iso_utc(5)))
    m.run_cycle()
    assert decision("cogn")["status"] == "executed"
    assert any(a["dedup_key"].startswith("link:") for a in alerts.list_alerts() if a.get("dedup_key"))
