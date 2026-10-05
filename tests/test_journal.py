"""Posições e P&L derivados das execuções (preço médio, day trade x swing, custos)."""
import pytest

from src.services import journal, portfolio
from src.services.journal import compute_ledger


def ex(id, side, qty, price, at, ticker="BBASJ216", fees=0.0, signal_id=None, asset="OPCAO"):
    return {"id": id, "ticker": ticker, "side": side, "quantity": qty, "price": price, "fees": fees,
            "executed_at": at, "signal_id": signal_id, "asset_class": asset}


def test_average_price_includes_fees_and_partial_exit():
    led = compute_ledger([
        ex(1, "BUY", 1000, 1.00, "2026-10-01T11:00:00-03:00", fees=1.0),
        ex(2, "BUY", 1000, 1.20, "2026-10-02T11:00:00-03:00", fees=1.0),
        ex(3, "SELL", 1000, 1.50, "2026-10-05T11:00:00-03:00", fees=1.0),
    ])
    pos = led["positions"][0]
    assert pos["qty"] == 1000
    assert pos["avg_price"] == pytest.approx(1.101)              # (1001 + 1201) / 2000
    ev = led["events"][0]
    assert ev["kind"] == "swing"
    assert ev["pnl"] == pytest.approx(1499.0 - 1101.0)
    assert led["cycles"][0]["status"] == "OPEN"


def test_full_round_trip_closes_cycle():
    led = compute_ledger([
        ex(1, "BUY", 1500, 1.27, "2026-09-28T13:20:00-03:00", signal_id="s1"),
        ex(2, "SELL", 1500, 3.00, "2026-10-05T14:00:00-03:00", signal_id="s1"),
    ])
    assert led["positions"] == []
    cy = led["cycles"][0]
    assert cy["status"] == "CLOSED" and cy["signal_ids"] == ["s1"]
    assert cy["realized_pnl"] == pytest.approx(1500 * 1.73)
    assert cy["return_pct"] == pytest.approx(136.22, abs=0.01)


def test_same_day_buy_and_sell_is_day_trade():
    led = compute_ledger([
        ex(1, "BUY", 500, 2.00, "2026-10-05T10:30:00-03:00"),
        ex(2, "SELL", 500, 2.20, "2026-10-05T15:30:00-03:00"),
    ])
    assert [e["kind"] for e in led["events"]] == ["day"]
    assert led["events"][0]["pnl"] == pytest.approx(100.0)
    assert led["cycles"][0]["day_trade_pnl"] == pytest.approx(100.0)


def test_day_trade_on_top_of_existing_position():
    # Tinha 1000 de ontem; hoje compra 500 e vende 800 -> 500 day trade + 300 swing
    led = compute_ledger([
        ex(1, "BUY", 1000, 1.00, "2026-10-02T11:00:00-03:00"),
        ex(2, "BUY", 500, 1.10, "2026-10-05T10:15:00-03:00"),
        ex(3, "SELL", 800, 1.30, "2026-10-05T16:00:00-03:00"),
    ])
    kinds = {e["kind"]: e for e in led["events"]}
    assert kinds["day"]["qty"] == 500 and kinds["day"]["pnl"] == pytest.approx(500 * 0.20)
    assert kinds["swing"]["qty"] == 300 and kinds["swing"]["pnl"] == pytest.approx(300 * 0.30)
    assert led["positions"][0]["qty"] == 700
    assert led["positions"][0]["avg_price"] == pytest.approx(1.00)


def test_short_position_pnl():
    led = compute_ledger([
        ex(1, "SELL", 100, 10.0, "2026-10-01T11:00:00-03:00", ticker="PETR4", asset="ACAO"),
        ex(2, "BUY", 100, 9.0, "2026-10-02T11:00:00-03:00", ticker="PETR4", asset="ACAO"),
    ])
    assert led["events"][0]["pnl"] == pytest.approx(100.0)
    assert led["cycles"][0]["direction"] == "SHORT"


def test_sell_more_than_held_is_blocked_by_default(tmp_db):
    journal.add_execution({"ticker": "VIVAJ241", "side": "BUY", "quantity": 700, "price": 1.29, "executed_at": "2026-10-05T11:00:00-03:00"})
    with pytest.raises(ValueError, match="descoberto"):
        journal.add_execution({"ticker": "VIVAJ241", "side": "SELL", "quantity": 800, "price": 1.5, "executed_at": "2026-10-05T12:00:00-03:00"})
    journal.add_execution({"ticker": "VIVAJ241", "side": "SELL", "quantity": 700, "price": 1.5, "executed_at": "2026-10-05T12:00:00-03:00"})
    assert portfolio.positions() == []


def test_execution_validation(tmp_db):
    with pytest.raises(ValueError):
        journal.add_execution({"ticker": "X", "side": "BUY", "quantity": 0, "price": 1, "executed_at": "2026-10-05T11:00:00"})
    with pytest.raises(ValueError):
        journal.add_execution({"ticker": "X", "side": "HOLD", "quantity": 1, "price": 1, "executed_at": "2026-10-05T11:00:00"})
    with pytest.raises(ValueError):
        journal.add_execution({"ticker": "X", "side": "BUY", "quantity": 1, "price": 1, "executed_at": "ontem"})
