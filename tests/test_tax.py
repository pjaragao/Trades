"""Apuração mensal de IR (estimativa)."""
import pytest

from src.services.tax import monthly_tax


def ev(date, kind, pnl, asset="OPCAO", sale=0.0):
    return {"date": date, "kind": kind, "pnl": pnl, "asset_class": asset, "sale_gross": sale}


def by_month(rows):
    return {r["month"]: r for r in rows}


def test_options_swing_taxed_15_no_exemption():
    r = by_month(monthly_tax([ev("2026-09-10", "swing", 1000.0, sale=3000.0)]))["2026-09"]
    assert r["swing_tax"] == pytest.approx(150.0)
    assert r["darf_value"] == pytest.approx(150.0 - 3000 * 0.00005)
    assert r["due_date"] == "2026-10-30"


def test_stock_exemption_up_to_20k_sales():
    r = by_month(monthly_tax([ev("2026-09-10", "swing", 900.0, asset="ACAO", sale=15000.0)]))["2026-09"]
    assert r["stock_exempt"] and r["swing_tax"] == 0 and r["exempt_gain"] == 900.0
    r2 = by_month(monthly_tax([ev("2026-09-10", "swing", 900.0, asset="ACAO", sale=25000.0)]))["2026-09"]
    assert not r2["stock_exempt"] and r2["swing_tax"] == pytest.approx(135.0)


def test_loss_compensation_is_separate_for_day_trade():
    rows = by_month(monthly_tax([
        ev("2026-07-10", "swing", -500.0),
        ev("2026-07-11", "day", -200.0),
        ev("2026-08-10", "swing", 800.0),
        ev("2026-08-11", "day", 100.0),
    ]))
    assert rows["2026-07"]["swing_loss_carry"] == 500.0 and rows["2026-07"]["day_loss_carry"] == 200.0
    assert rows["2026-08"]["swing_base"] == pytest.approx(300.0)
    assert rows["2026-08"]["day_base"] == 0.0 and rows["2026-08"]["day_loss_carry"] == pytest.approx(100.0)


def test_darf_below_10_is_carried():
    rows = by_month(monthly_tax([ev("2026-07-10", "swing", 50.0), ev("2026-08-10", "swing", 30.0)]))
    assert rows["2026-07"]["darf_value"] == 0 and rows["2026-07"]["carried_to_next"] == pytest.approx(7.5)
    assert rows["2026-08"]["darf_value"] == pytest.approx(12.0)


def test_months_without_operations_are_listed():
    rows = monthly_tax([ev("2026-06-10", "swing", -100.0), ev("2026-08-10", "swing", 200.0)])
    assert [r["month"] for r in rows] == ["2026-06", "2026-07", "2026-08"]
    assert rows[1]["swing_loss_carry"] == 100.0
