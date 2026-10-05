"""Boleta pronta: quantidade, limite, custos e avisos."""
from datetime import datetime

from src.core.config import DEFAULT_PREFS, deep_merge
from src.core.market_hours import BRT
from src.services.sizing import build_ticket

OPEN_MARKET = datetime(2026, 10, 5, 11, 0, tzinfo=BRT)   # segunda, pregão aberto
SATURDAY = datetime(2026, 10, 3, 11, 0, tzinfo=BRT)


def prefs(**patch):
    return deep_merge(DEFAULT_PREFS, patch)


def sig(**kw):
    base = {
        "id": "s1", "ticker": "NATUK800", "asset_class": "OPCAO", "lado": "BUY", "preco_entrada": 0.38,
        "preco_atual": 0.38, "timestamp_entrada": "2026-10-05T13:30:00+00:00", "trader": "Sanita",
        "expiration": "2026-11-19", "underlying": "NATU3", "opcao_tipo": "CALL", "strike": 8.0,
    }
    base.update(kw)
    return base


def test_quantity_respects_lot_and_budget():
    t = build_ticket(sig(), prefs(), at=OPEN_MARKET)
    assert t["quantity"] == 2600          # 1000 / 0.38 = 2631 -> 2600 (lote 100)
    assert t["limit_price"] == 0.38
    assert t["gross"] == 988.0
    assert t["total"] > t["gross"]        # custos estimados somados na compra
    assert t["can_execute"]


def test_never_forces_a_lot_above_capital():
    t = build_ticket(sig(preco_entrada=15.0, preco_atual=15.0), prefs(), at=OPEN_MARKET)
    assert t["quantity"] == 0
    assert not t["can_execute"]
    assert t["one_lot_cost"] == 1500.0
    assert any("Capital insuficiente" in w["text"] for w in t["warnings"])


def test_price_drift_above_slippage_caps_limit():
    t = build_ticket(sig(preco_entrada=1.00, preco_atual=1.20), prefs(), at=OPEN_MARKET)
    assert t["worst_price"] == 1.05
    assert t["limit_price"] == 1.05
    assert any(w["level"] == "danger" and "acima" in w["text"] for w in t["warnings"])


def test_better_current_price_is_used():
    t = build_ticket(sig(preco_entrada=1.00, preco_atual=0.95), prefs(), at=OPEN_MARKET)
    assert t["limit_price"] == 0.95


def test_pct_capital_mode_and_free_capital_cap():
    p = prefs(capital={"total": 5000.0}, sizing={"mode": "pct_capital", "pct_per_trade": 20.0})
    t = build_ticket(sig(preco_entrada=1.0, preco_atual=1.0), p, at=OPEN_MARKET)
    assert t["budget"] == 1000.0 and t["quantity"] == 1000
    t2 = build_ticket(sig(preco_entrada=1.0, preco_atual=1.0), p, exposure=4600.0, at=OPEN_MARKET)
    assert t2["quantity"] == 400
    assert any("Capital livre" in w["text"] for w in t2["warnings"])


def test_manual_overrides_and_odd_lot_warning():
    t = build_ticket(sig(), prefs(), quantity=250, limit_price=0.40, at=OPEN_MARKET)
    assert t["quantity"] == 250 and t["limit_price"] == 0.40
    assert any("lote padrão" in w["text"] for w in t["warnings"])


def test_option_buy_max_loss_is_premium_and_market_closed_warning():
    t = build_ticket(sig(), prefs(), at=SATURDAY)
    assert t["max_loss"] == t["total"]
    assert any("fechado" in w["text"].lower() for w in t["warnings"])


def test_stop_loss_defines_max_loss():
    t = build_ticket(sig(asset_class="ACAO", ticker="PETR4", preco_entrada=10.0, preco_atual=10.0, stop_loss=9.5, expiration=None), prefs(), at=OPEN_MARKET)
    assert t["quantity"] == 100
    assert 50.0 <= t["max_loss"] < 51.0


def test_near_expiration_warning():
    t = build_ticket(sig(expiration="2026-10-07"), prefs(), at=OPEN_MARKET)
    assert any(w["level"] == "danger" and "vence" in w["text"] for w in t["warnings"])


def test_copy_text_has_essentials():
    t = build_ticket(sig(), prefs(), at=OPEN_MARKET)
    txt = t["copy_text"]
    assert "COMPRA NATUK800" in txt and "2.600" in txt and "R$ 0,38" in txt and "Sanita" in txt
