"""Máquina do Tempo, histórico do analista e checagem pré-trade (skills do Claude Code em .claude/skills/)."""
import copy
import math
import random
from datetime import date, datetime, timedelta

import pytest

from src.core.config import DEFAULT_PREFS
from src.core.market_hours import BRT, is_business_day
from src.lab import analyst_history as ah
from src.lab import signal_review as sr
from src.lab import timemachine as tm
from src.services import pretrade


def business_days(start: date, n: int):
    d, out = start, []
    while len(out) < n:
        if is_business_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def daily_bars(n=300, start=date(2025, 6, 2), seed=1, price=30.0):
    rng = random.Random(seed)
    bars = []
    for d in business_days(start, n):
        o = price * math.exp(rng.gauss(0, 0.004))
        c = o * math.exp(rng.gauss(0, 0.015))
        h, l = max(o, c) * (1 + abs(rng.gauss(0, 0.006))), min(o, c) * (1 - abs(rng.gauss(0, 0.006)))
        bars.append((datetime(d.year, d.month, d.day, tzinfo=BRT), o, h, l, c))
        price = c
    return bars


def intraday_bars(days, seed=2, price=30.0, drop_every=17):
    """Pregões de 10:00 a 16:55 (horário de verão dos EUA), algumas barras omitidas como faz o Yahoo."""
    rng = random.Random(seed)
    bars, i = [], 0
    for d in days:
        for k in range(83):
            i += 1
            o = price
            c = o * math.exp(rng.gauss(0, 0.002))
            h, l = max(o, c) * (1 + abs(rng.gauss(0, 0.001))), min(o, c) * (1 - abs(rng.gauss(0, 0.001)))
            price = c
            if i % drop_every == 0:
                continue
            t = datetime(d.year, d.month, d.day, 10, 0, tzinfo=BRT) + timedelta(minutes=5 * k)
            bars.append((t, o, h, l, c))
    return bars


# ---------------------------------------------------------------- Máquina do Tempo

def test_verdict_thresholds():
    assert tm.verdict(0.294, 0.255, 0.451, 1.0, 0.034)[0].startswith("Perto de cara ou coroa")
    lines = tm.verdict(0.241, 0.505, 0.254, 2.0, -0.1)
    assert lines[0].startswith("Perto do empate")  # 2R: precisa de 33% entre os que tocaram, veio 32%
    strong = tm.verdict(0.60, 0.20, 0.20, 1.0, 0.4)
    assert strong[0].startswith("Fortemente para o alvo") and len(strong) == 1
    contra = tm.verdict(0.05, 0.15, 0.80, 2.0, 0.10)
    assert contra[0].startswith("Pende para o stop")  # 25% entre os que tocaram; 2R empata com 33%
    assert any("não tocaram nenhum" in x for x in contra) and any("vai contra" in x for x in contra)


def test_walk_gap_fills_at_open_and_stop_wins_ties():
    lin = lambda s, tau: s  # noqa: E731
    buy = tm.Plan("PETR4", "BUY", 100.0, 95.0, 110.0)
    assert tm.walk(buy, 100.0, [(0.90, 0.92, 0.88, 0.91)], lin, True, [None]) [:2] == ("stop", 90.0)
    assert tm.walk(buy, 100.0, [(1.0, 1.12, 0.94, 1.0)], lin, True, [None])[:2] == ("stop", 95.0)
    assert tm.walk(buy, 100.0, [(1.0, 1.11, 0.99, 1.05)], lin, True, [None])[:2] == ("target", 110.0)
    out, exit_v, s_end = tm.walk(buy, 100.0, [(1.0, 1.01, 0.99, 1.0), (1.0, 1.02, 0.99, 1.01)], lin, True, [None, None])
    assert out == "neither" and exit_v == pytest.approx(101.0)
    sell = tm.Plan("PETR4", "SELL", 100.0, 105.0, 90.0)
    assert tm.walk(sell, 100.0, [(1.08, 1.09, 1.07, 1.08)], lin, True, [None])[:2] == ("stop", 108.0)
    assert tm.walk(sell, 100.0, [(1.0, 1.01, 0.89, 0.95)], lin, True, [None])[:2] == ("target", 90.0)


def test_run_swing_is_reproducible_and_consistent():
    bars = daily_bars()
    kw = dict(ticker="PETR4", side="BUY", entry=bars[-1][4], stop=bars[-1][4] * 0.95, target=bars[-1][4] * 1.10,
              bars=bars, as_of=date(2026, 9, 1), replays=2000)
    a, b = tm.run(**kw), tm.run(**kw)
    assert a["p_target"] == b["p_target"] and a["avg_r"] == b["avg_r"]
    assert a["p_target"] + a["p_stop"] + a["p_neither"] == pytest.approx(1.0)
    assert a["plan"]["target_r"] == pytest.approx(2.0, abs=0.02)
    c = tm.run(**{**kw, "seed": 7})
    assert c["p_target"] != a["p_target"] or c["avg_r"] != a["avg_r"]
    assert "semente 19" in tm.report(a)


def test_run_swing_builds_plan_from_atr_or_pct():
    bars = daily_bars()
    entry = bars[-1][4]
    atr_plan = tm.run(ticker="PETR4", side="BUY", entry=entry, bars=bars, as_of=date(2026, 9, 1), replays=500)
    assert "ATR14" in atr_plan["plan"]["source"] and atr_plan["plan"]["target_r"] == pytest.approx(2.0, abs=0.05)
    pct = tm.run(ticker="PETR4", side="SELL", entry=entry, stop_pct=2, target_pct=4, bars=bars, as_of=date(2026, 9, 1), replays=500)
    assert pct["plan"]["stop"] == pytest.approx(entry * 1.02, abs=0.01) and pct["plan"]["target"] == pytest.approx(entry * 0.96, abs=0.01)
    no_stop = tm.run(ticker="PETR4", side="BUY", entry=entry, stop_pct=100, bars=bars, as_of=date(2026, 9, 1), replays=200)
    assert "ATR14" in no_stop["plan"]["source"] and any("não ter stop" in n for n in no_stop["notes"])


def test_run_rejects_bad_plans_and_short_history():
    bars = daily_bars()
    with pytest.raises(tm.TMError, match="stop fica abaixo"):
        tm.run(ticker="PETR4", side="BUY", entry=30, stop=31, target=33, bars=bars, as_of=date(2026, 9, 1))
    with pytest.raises(tm.TMError, match="mínimo"):
        tm.run(ticker="PETR4", side="BUY", entry=30, stop=29, target=32, bars=daily_bars(60), as_of=date(2026, 9, 1))
    with pytest.raises(tm.TMError, match="--csv"):
        tm.yahoo_symbol("WINZ26")
    assert tm.yahoo_symbol("PETRK300") == "PETR4.SA" and tm.yahoo_symbol("SAUDK170") == "SAUD3.SA"


def test_intraday_pool_fills_gaps_and_drops_thin_sessions():
    days = business_days(date(2026, 8, 3), 25)
    bars = intraday_bars(days)
    thin_day = days[3]
    bars = [b for b in bars if not (b[0].date() == thin_day and b[0].hour >= 13)]  # pregão pela metade
    pool, used = tm.intraday_pool(bars, date(2026, 10, 1))
    assert used == 24
    assert 0 not in pool and all(k in pool for k in range(1, 83))
    assert any(r == (1.0, 1.0, 1.0, 1.0) for r in sum(pool.values(), []))


def test_run_intraday_uses_rest_of_session():
    days = business_days(date(2026, 8, 3), 30)
    bars = intraday_bars(days)
    res = tm.run(ticker="PETR4", side="BUY", entry=30.0, stop=29.7, target=30.6, mode="intraday", entry_time="11:00",
                 bars=bars, as_of=date(2026, 9, 21), replays=1000)
    assert "11:00 até 16:45 (69 barras" in res["span"]
    assert res["p_target"] + res["p_stop"] + res["p_neither"] == pytest.approx(1.0)
    with pytest.raises(tm.TMError, match="hora"):
        tm.run(ticker="PETR4", side="BUY", entry=30.0, stop=29.7, target=30.6, mode="intraday", bars=bars, as_of=date(2026, 9, 21))


def test_black_scholes_parity_and_implied_vol():
    s, k, tau, r = 30.0, 31.0, 20 / 252, math.log(1.1375)
    call, put = tm.bs_price(s, k, tau, r, 0.4, "CALL"), tm.bs_price(s, k, tau, r, 0.4, "PUT")
    assert call - put == pytest.approx(s - k * math.exp(-r * tau), abs=1e-9)
    assert tm.implied_vol(call, s, k, tau, r, "CALL") == pytest.approx(0.4, abs=1e-6)
    assert tm.implied_vol(0.0001, s, 20.0, tau, r, "CALL") is None  # abaixo do intrínseco
    assert tm.spot_for_premium(call, k, tau, r, 0.4, "CALL", s) == pytest.approx(s, abs=1e-4)


def test_run_option_reprices_premium_on_underlying():
    bars = daily_bars(start=date(2025, 1, 2), n=440)
    as_of = date(2026, 10, 1)
    s0 = [b for b in bars if b[0].date() <= as_of][-1][4]
    days = 33  # pregões de 01/10 (exclusive) a 19/11/2026: sem 12/10, 02/11 e 20/11
    prem = round(tm.bs_price(s0, round(s0), days / 252, math.log(1.1375), 0.35, "CALL"), 2)
    res = tm.run(ticker="PETRK300", side="BUY", entry=prem, strike=round(s0), expiration="2026-11-19", bars=bars,
                 as_of=as_of, rate=13.75, horizon=60, replays=1000)
    opt = res["option"]
    assert opt["kind"] == "CALL" and opt["days"] == days
    assert opt["iv"] == pytest.approx(0.35, abs=0.02)
    assert "ativo-objeto" in res["plan"]["source"]
    assert any("cortado no vencimento" in n for n in res["notes"])
    assert opt["spot_at_stop"] < s0 < opt["spot_at_target"]
    with pytest.raises(tm.TMError, match="strike"):
        tm.run(ticker="PETRK300", side="BUY", entry=prem, bars=bars, as_of=as_of, rate=13.75)


def test_load_csv_mt5_and_brazilian_formats(tmp_path):
    mt5 = tmp_path / "win.csv"
    mt5.write_text("<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\n"
                   "2026.10.23\t10:00:00\t131000\t131200\t130900\t131100\t500\n"
                   "2026.10.23\t10:05:00\t131100\t131300\t131050\t131250\t400\n", encoding="utf-8")
    bars = tm.load_csv(str(mt5))
    assert len(bars) == 2 and bars[1][0] == datetime(2026, 10, 23, 10, 5, tzinfo=BRT) and bars[1][4] == 131250
    br = tmp_path / "petr.csv"
    br.write_text("data;abertura;maxima;minima;fechamento\n2026-10-22;38,10;38,90;37,95;38,50\n", encoding="utf-8")
    assert tm.load_csv(str(br))[0][1:] == (38.10, 38.90, 37.95, 38.50)


# ---------------------------------------------------------------- histórico do analista

def closed(trader, ret_pct, i, days_held=3, asset="OPCAO"):
    entry_dt = datetime(2026, 7, 1, 14, 0) + timedelta(days=i)
    return {"trader": trader, "asset_class": asset, "ticker": "PETRK300", "lado": "BUY", "preco_entrada": 1.0,
            "preco_saida": 1.0 + ret_pct / 100, "timestamp_entrada": entry_dt.isoformat() + "+00:00",
            "timestamp_saida": (entry_dt + timedelta(days=days_held)).isoformat() + "+00:00", "status": "CLOSED"}


def test_analyst_summary_plan_needs_enough_losses():
    rows = [closed("Ana", 30, i) for i in range(22)] + [closed("Ana", -80, 30 + i) for i in range(2)]
    s = ah.summarize(rows, "ana", "OPCAO")
    assert s["closed"] == 24 and s["win_rate"] == pytest.approx(91.7)
    assert s["plan"]["stop_pct"] is None and s["plan"]["target_pct"] == 30 and s["plan"]["horizon_days"] == 3
    assert "use o ATR" in ah.report(s)

    rows2 = rows + [closed("Ana", -10 * (i + 1), 40 + i) for i in range(4)]
    s2 = ah.summarize(rows2, "Ana", "OPCAO")
    assert s2["plan"]["stop_pct"] == pytest.approx(70.0)  # 75º percentil (interpolado) de 10, 20, 30, 40, 80, 80
    assert s2["t_stat"] is not None and s2["last10"].endswith("PPPP")


def test_analyst_edge_labels_and_ranking():
    few = ah.summarize([closed("Bia", 5, i) for i in range(5)], "Bia")
    assert few["edge"].startswith("amostra pequena") and few["plan"] is None
    noisy = [closed("Caio", (12 if i % 2 else -11), i) for i in range(40)]
    assert ah.summarize(noisy, "Caio")["edge"].startswith("sem edge")
    rank = ah.ranking(noisy + [closed("Ana", 10 + i % 3, i) for i in range(30)], "OPCAO", min_n=10)
    assert [r["trader"] for r in rank] == ["Ana", "Caio"]


# ---------------------------------------------------------------- checagem pré-trade

@pytest.fixture()
def prefs():
    return copy.deepcopy(DEFAULT_PREFS)


AT = datetime(2026, 10, 26, 11, 0, tzinfo=BRT)  # segunda-feira, pregão aberto
CTX = {"positions": [], "realized_today": 0.0, "entries_today": 0, "exposure": 0.0}


def test_size_by_risk_counts_round_trip_costs(prefs):
    s = pretrade.size_by_risk(ticker="ABCD3", asset="ACAO", entry=10.0, stop=9.5, lot=100, max_risk=100.0,
                              budget=2000.0, prefs=prefs)
    assert s["qty_budget"] == 200 and s["qty_risk"] == 100  # 200 × 0,50 + custos passaria de R$ 100
    assert s["qty"] == 100 and s["limited_by"] == "risco" and s["risk_brl"] <= 100
    fut = pretrade.size_by_risk(ticker="WINZ26", asset="FUTURO", entry=131000, stop=130800, lot=1, max_risk=100.0,
                                budget=1e9, prefs=prefs)
    assert fut["per_unit"] == pytest.approx(40.0) and fut["qty"] == 2  # 200 pontos × R$ 0,20


def test_check_blocks_and_passes(prefs):
    ok = pretrade.check(ticker="ABCD3", side="BUY", entry=10.0, stop=9.5, target=11.0, prefs=prefs, ctx=CTX, at=AT)
    assert ok["ok"] and ok["qty"] == 100 and ok["rr"] == 2.0 and ok["breakeven_win"] == pytest.approx(33.3)

    no_stop = pretrade.check(ticker="ABCD3", side="BUY", entry=10.0, stop=None, prefs=prefs, ctx=CTX, at=AT)
    assert not no_stop["ok"] and "Sem stop" in no_stop["blocks"][0]
    wrong = pretrade.check(ticker="ABCD3", side="BUY", entry=10.0, stop=10.5, prefs=prefs, ctx=CTX, at=AT)
    assert any("lado errado" in b for b in wrong["blocks"])
    low_rr = pretrade.check(ticker="ABCD3", side="BUY", entry=10.0, stop=9.5, target=10.2, prefs=prefs, ctx=CTX, at=AT)
    assert any("abaixo do mínimo" in b for b in low_rr["blocks"])

    winner = {"trader": "Sanita", "closed": 89, "win_rate": 97.8}
    hi_wr = pretrade.check(ticker="ABCD3", side="BUY", entry=10.0, stop=9.5, target=10.2, prefs=prefs, ctx=CTX, at=AT, analyst=winner)
    assert hi_wr["ok"] and any("Sanita acerta 97,8%" in i for i in hi_wr["info"])
    coin = {"trader": "Amilton", "closed": 98, "win_rate": 53.1}
    lo_wr = pretrade.check(ticker="ABCD3", side="BUY", entry=10.0, stop=9.5, target=10.2, prefs=prefs, ctx=CTX, at=AT, analyst=coin)
    assert not lo_wr["ok"] and any("Amilton acerta 53,1%" in b for b in lo_wr["blocks"])


def test_check_day_limits_expiry_short_and_chasing(prefs):
    day = pretrade.check(ticker="ABCD3", side="BUY", entry=10.0, stop=9.5, target=11.0, prefs=prefs, at=AT,
                         ctx={**CTX, "realized_today": -250.0, "entries_today": 3})
    assert any("perda do dia vai a" in b for b in day["blocks"]) and any("3 entradas hoje" in b for b in day["blocks"])
    exp = pretrade.check(ticker="PETRK300", side="BUY", entry=1.0, stop=0.6, target=1.8, prefs=prefs, ctx=CTX, at=AT,
                         expiration="2026-10-29")
    assert any("vence em 3 pregão" in b for b in exp["blocks"])
    short = pretrade.check(ticker="ABCD3", side="SELL", entry=10.0, stop=10.5, target=9.0, prefs=prefs, ctx=CTX, at=AT)
    assert any("descoberto" in b for b in short["blocks"])
    chase = pretrade.check(ticker="ABCD3", side="BUY", entry=10.0, stop=9.5, target=11.0, prefs=prefs, ctx=CTX, at=AT, ref_entry=9.0)
    assert any("andou 11,1% contra" in b for b in chase["blocks"])
    unknown = pretrade.check(ticker="ABCD3", side="BUY", entry=10.0, stop=9.5, target=11.0, prefs=prefs, at=AT,
                             ctx={"positions": None, "realized_today": 0.0, "entries_today": None, "exposure": 0.0})
    assert unknown["ok"] and any("Nenhuma execução no banco" in w for w in unknown["warnings"])


def test_review_without_simulation_builds_ticket(tmp_db):
    sig = sr.manual_signal("ABCD3", "BUY", 10.0)
    rv = sr.review(sig, stop=9.5, target=11.0, simulate=False, history_rows=[], limits=sr.load_limits())
    assert rv["check"]["qty"] == 100
    assert rv["check"]["ok"] == (not rv["check"]["blocks"])
    if rv["check"]["ok"]:
        assert rv["ticket"]["copy_text"].startswith("COMPRA ABCD3") and "Quantidade: 100" in rv["ticket"]["copy_text"]
    assert "Nada foi enviado" in sr.report(rv)
