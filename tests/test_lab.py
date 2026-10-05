"""Laboratório: backtest de cópia e taxas do BCB com fallback."""
import pytest

from src.core import db
from src.integrations.tradingfloors import merge_rows
from src.lab import rates, signal_backtest
from src.services.signals import upsert_signals
from tests.conftest import trade_row


def seed(rows):
    with db.transaction() as c:
        upsert_signals(c, merge_rows(rows, []), baseline=True)


def closed(id, ticker, entry, exit_, ts_in, ts_out, trader="Sanita", lado="BUY", tipo="OPCOES"):
    return trade_row(id, ticker, trader=trader, lado=lado, preco=entry, status="CLOSED", saida=exit_, ts=ts_in, ts_saida=ts_out, tipo=tipo)


def test_backtest_applies_lot_slippage_costs_and_side(tmp_db):
    seed([
        closed("a", "BBASJ216", 1.00, 2.00, "2026-09-01T14:00:00+00:00", "2026-09-05T14:00:00+00:00"),
        closed("b", "PETR4", 10.0, 9.0, "2026-09-02T14:00:00+00:00", "2026-09-06T14:00:00+00:00", lado="SELL", tipo="Ações/FIIs/BDRs (B3)"),
    ])
    r = signal_backtest.run(traders=["Sanita"], initial_capital=10000, value_per_trade=1000, slippage_pct=0)
    t = {x["id"]: x for x in r["trades"]}
    assert t["a"]["qty"] == 1000 and t["a"]["pnl"] == pytest.approx(1000 - t["a"]["fees"])
    assert t["b"]["qty"] == 100 and t["b"]["pnl"] == pytest.approx(100 - t["b"]["fees"])  # venda lucra na queda
    r2 = signal_backtest.run(traders=["Sanita"], initial_capital=10000, value_per_trade=1000, slippage_pct=1.0)
    assert r2["summary"]["net_pnl"] < r["summary"]["net_pnl"]


def test_backtest_skips_intraday_and_unaffordable(tmp_db):
    seed([
        closed("a", "BBASJ216", 1.0, 1.5, "2026-09-01T14:00:00+00:00", "2026-09-01T18:00:00+00:00"),
        closed("b", "ITUBJ423", 25.0, 30.0, "2026-09-02T14:00:00+00:00", "2026-09-08T14:00:00+00:00"),
    ])
    r = signal_backtest.run(traders=["Sanita"], value_per_trade=1000)
    assert r["summary"]["trades"] == 0
    assert r["summary"]["skipped"] == {"intraday (mesmo dia)": 1, "capital insuficiente p/ 1 lote": 1}
    r2 = signal_backtest.run(traders=["Sanita"], value_per_trade=1000, skip_intraday=False)
    assert r2["summary"]["trades"] == 1


def test_backtest_respects_free_capital(tmp_db):
    seed([
        closed("a", "AAAAJ10", 1.0, 1.1, "2026-09-01T14:00:00+00:00", "2026-09-10T14:00:00+00:00"),
        closed("b", "BBBBJ10", 1.0, 1.1, "2026-09-02T14:00:00+00:00", "2026-09-10T14:00:00+00:00"),
    ])
    r = signal_backtest.run(traders=["Sanita"], initial_capital=1500, value_per_trade=1000, slippage_pct=0)
    assert r["summary"]["trades"] == 1
    assert r["summary"]["skipped"]["sem capital livre (posições abertas)"] == 1


def test_rates_fallback_when_bcb_unreachable(tmp_db, monkeypatch):
    def boom(code):
        raise rates.requests.ConnectionError("offline")

    monkeypatch.setattr(rates, "_fetch", boom)
    r = rates.get_rates(force=True)
    assert r["cdi"]["source"] == "fixo" and r["cdi"]["value"] == 11.75

    monkeypatch.setattr(rates, "_fetch", lambda code: {"value": 13.65, "date": "01/10/2026"})
    assert rates.get_rates(force=True)["cdi"]["value"] == 13.65
    monkeypatch.setattr(rates, "_fetch", boom)
    cached = rates.get_rates(force=True)["cdi"]
    assert cached["source"] == "cache" and cached["value"] == 13.65
