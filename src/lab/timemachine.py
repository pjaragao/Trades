"""
Máquina do Tempo: milhares de replays Monte Carlo de um trade na B3 antes de arriscar um real.

Adaptado do trader-timemachine (github.com/Jakeschincariol/day-trader-skill, MIT). A pergunta é a mesma: se os
próximos pregões se parecerem com o passado recente do próprio ativo, com que frequência o plano (entrada, stop,
alvo) bate o alvo primeiro, o stop primeiro, ou nenhum dos dois até o fim do horizonte?

Modos:
- swing    : barras diárias (2 anos, ajustadas por proventos). Cada réplica sorteia os próximos H pregões em blocos
             de 5 dias seguidos (mantém a volatilidade agrupada) e confere stop/alvo na máxima/mínima de cada dia.
- intraday : barras de 5 min (60 dias). Cada barra que falta no pregão é sorteada entre as barras do mesmo horário
             (±2 barras) dos pregões anteriores, como no original.
Opções: simula o ATIVO-OBJETO e reprecifica o prêmio por Black-Scholes, com a volatilidade implícita tirada do
prêmio de entrada (vol constante: não modela sorriso nem choque de vol). Stop e alvo valem sobre o prêmio.

Diferenças para o original (feito para ações dos EUA):
- pregão da B3 (10:00 até o fechamento do dia, que muda com o horário de verão dos EUA; ver core/market_hours);
- o Yahoo omite barras de 5 min sem negócio: viram barra parada no fechamento anterior, e pregão com menos de 80%
  das barras fica de fora;
- gap além do stop/alvo executa na ABERTURA da barra (o original contava sempre -1R) — no swing isso pesa;
- compra e venda; barra que toca stop e alvo conta como stop (conservador, igual ao original);
- o TradingFloors não publica stop/alvo, então o plano pode vir de % (histórico do analista) ou de ATR.

É simulação a partir do passado recente, não previsão: balanço, notícia e leilão fazem o que esses dias não fizeram.
"""
import csv
import math
import random
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from src.core import b3_tickers
from src.core.market_hours import BRT, business_days_between, now_brt, session_times

TICK = 0.01
SLOT_MIN = 5
WINDOW = 2            # ±2 barras de 5 min no sorteio do mesmo horário
BLOCK = 5             # pregões seguidos por bloco no modo swing
LOOKBACK_DAYS = 500
MIN_SESSIONS = 20
MIN_DAYS = 120
MIN_SLOT_SHARE = 0.8
DAYS_YEAR = 252
COIN_FLIP, STRONG, MANY_NEITHER = 0.05, 0.15, 0.40
DEFAULT_STOP_ATR = {"swing": 1.5, "intraday": 0.5}
DEFAULT_HORIZON = 10

Bar = Tuple[datetime, float, float, float, float]   # (início da barra em Brasília, abertura, máxima, mínima, fechamento)
Ratio = Tuple[float, float, float, float]          # (abertura, máxima, mínima, fechamento) / fechamento anterior


class TMError(Exception):
    """Plano ou dados insuficientes — a mensagem vai inteira para o usuário."""


# ---------------------------------------------------------------- formatação

def _num(v: Optional[float], d: int = 2) -> str:
    if v is None:
        return "—"
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %".replace(".", ",")


def _r(x: float, d: int = 2) -> str:
    return f"{x:+.{d}f}".replace(".", ",")


def _round_tick(price: float) -> float:
    return round(round(price / TICK) * TICK, 2)


# ---------------------------------------------------------------- dados

def yahoo_symbol(ticker: str) -> str:
    """PETR4 -> PETR4.SA; opção -> ativo-objeto. Futuros/índices: sem barra gratuita confiável."""
    tk = b3_tickers.clean_ticker(ticker)
    cls = b3_tickers.asset_class(None, tk)
    if cls == "OPCAO":
        tk, cls = b3_tickers.underlying_of(tk), "ACAO"
    if cls != "ACAO" or not tk:
        raise TMError(f"{ticker}: sem barras gratuitas confiáveis (futuro/índice/forex). Exporte do MT5 e use --csv.")
    return f"{tk}.SA"


def _frame_to_bars(df) -> List[Bar]:
    out: List[Bar] = []
    for ts, row in df.iterrows():
        o, h, l, c = (float(row[k]) for k in ("Open", "High", "Low", "Close"))
        if not all(math.isfinite(x) and x > 0 for x in (o, h, l, c)):
            continue
        dt = ts.to_pydatetime()
        dt = dt.astimezone(BRT) if dt.tzinfo else dt.replace(tzinfo=BRT)
        out.append((dt, o, max(h, o, c), min(l, o, c), c))
    return out


def fetch_bars(ticker: str, mode: str) -> List[Bar]:
    """Yahoo Finance (gratuito, não oficial, ~15 min de atraso): 2 anos diários ou 60 dias de 5 min."""
    import yfinance as yf

    symbol = yahoo_symbol(ticker)
    interval, period = ("5m", "60d") if mode == "intraday" else ("1d", "2y")
    df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=mode != "intraday")
    if df is None or df.empty:
        raise TMError(f"O Yahoo não devolveu barras de {interval} para {symbol}.")
    return _frame_to_bars(df)


_CSV_KEYS = {
    "datetime": ("datetime", "timestamp", "time_utc", "data_hora"),
    "date": ("date", "data", "dia"),
    "time": ("time", "hora"),
    "open": ("open", "abertura"),
    "high": ("high", "maxima", "máxima"),
    "low": ("low", "minima", "mínima"),
    "close": ("close", "fechamento", "ultimo", "último"),
}


def load_csv(path: str) -> List[Bar]:
    """CSV de barras (export do MT5, robo_lab real_bars...): data/hora + abertura/máxima/mínima/fechamento."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.DictReader(f, dialect=dialect))
    if not rows:
        raise TMError(f"{path}: CSV vazio.")
    norm = {k: k.strip().strip("<>").lower() for k in rows[0]}
    col = {}
    for want, names in _CSV_KEYS.items():
        col[want] = next((k for k, n in norm.items() if n in names), None)
    if not all(col[k] for k in ("open", "high", "low", "close")) or not (col["datetime"] or col["date"]):
        raise TMError(f"{path}: preciso das colunas data(/hora), open, high, low, close.")

    def num(s: str) -> float:
        s = str(s).strip()
        return float(s.replace(".", "").replace(",", ".") if "," in s else s)

    out: List[Bar] = []
    for r in rows:
        stamp = r[col["datetime"]] if col["datetime"] else f"{r[col['date']]} {r[col['time']] if col['time'] else '00:00'}"
        stamp = stamp.strip().replace(".", "-", 2) if stamp[:4].isdigit() and stamp[4:5] == "." else stamp.strip()
        try:
            dt = datetime.fromisoformat(stamp.replace("T", " ")[:19])
        except ValueError:
            continue
        dt = dt.astimezone(BRT) if dt.tzinfo else dt.replace(tzinfo=BRT)
        o, h, l, c = (num(r[col[k]]) for k in ("open", "high", "low", "close"))
        if min(o, h, l, c) > 0:
            out.append((dt, o, max(h, o, c), min(l, o, c), c))
    out.sort(key=lambda b: b[0])
    if not out:
        raise TMError(f"{path}: nenhuma barra válida.")
    return out


def daily_from_intraday(bars: Sequence[Bar]) -> List[Bar]:
    days: Dict[date, List[Bar]] = {}
    for b in bars:
        days.setdefault(b[0].date(), []).append(b)
    out = []
    for d in sorted(days):
        bs = days[d]
        out.append((bs[0][0], bs[0][1], max(b[2] for b in bs), min(b[3] for b in bs), bs[-1][4]))
    return out


def atr(daily: Sequence[Bar], n: int = 14) -> Optional[float]:
    """Média do true range dos últimos n pregões."""
    if len(daily) < n + 1:
        return None
    trs = [max(b[2], p[4]) - min(b[3], p[4]) for p, b in zip(daily[-n - 1:-1], daily[-n:])]
    return sum(trs) / n


# ---------------------------------------------------------------- pools

def _ratio(prev_close: float, bar: Bar) -> Ratio:
    return (bar[1] / prev_close, bar[2] / prev_close, bar[3] / prev_close, bar[4] / prev_close)


def daily_pool(bars: Sequence[Bar], before: date, lookback: int = LOOKBACK_DAYS) -> List[Ratio]:
    past = [b for b in bars if b[0].date() < before][-(lookback + 1):]
    pool = [_ratio(past[i - 1][4], past[i]) for i in range(1, len(past))]
    if len(pool) < MIN_DAYS:
        raise TMError(f"Só {len(pool)} pregões de histórico antes de {before:%d/%m/%Y} (mínimo {MIN_DAYS}).")
    return pool


@lru_cache(maxsize=512)
def _grid(d: date) -> Tuple[int, int]:
    """(minuto da abertura, nº de barras de 5 min até o fechamento) do pregão do dia d."""
    st = session_times(d)
    open_min = st["open"].hour * 60 + st["open"].minute
    close_min = st["close"].hour * 60 + st["close"].minute
    return open_min, (close_min - open_min) // SLOT_MIN


def _slot(dt: datetime) -> int:
    open_min, _ = _grid(dt.date())
    return (dt.hour * 60 + dt.minute - open_min) // SLOT_MIN


def intraday_pool(bars: Sequence[Bar], before: date) -> Tuple[Dict[int, List[Ratio]], int]:
    """{barra do dia: [razões dos pregões anteriores]} e quantos pregões entraram."""
    by_day: Dict[date, Dict[int, Bar]] = {}
    for b in bars:
        d = b[0].date()
        if d >= before:
            continue
        k = _slot(b[0])
        if 0 <= k < _grid(d)[1]:
            by_day.setdefault(d, {})[k] = b
    pool: Dict[int, List[Ratio]] = {}
    used = 0
    for d in sorted(by_day):
        slots, n = by_day[d], _grid(d)[1]
        if len(slots) < MIN_SLOT_SHARE * n:
            continue
        used += 1
        last = None
        for k in range(n):
            b = slots.get(k)
            if last is None:  # a primeira barra do dia carrega o gap da noite: fica fora
                last = b[4] if b else None
                continue
            pool.setdefault(k, []).append(_ratio(last, b) if b else (1.0, 1.0, 1.0, 1.0))
            if b:
                last = b[4]
    if used < MIN_SESSIONS:
        raise TMError(f"Só {used} pregões completos de 5 min antes de {before:%d/%m/%Y} (mínimo {MIN_SESSIONS}).")
    return pool, used


def daily_sampler(pool: Sequence[Ratio], block: int = BLOCK) -> Callable[[random.Random, int], List[Ratio]]:
    n = len(pool)

    def draw(rng: random.Random, h: int) -> List[Ratio]:
        out: List[Ratio] = []
        while len(out) < h:
            start = rng.randrange(0, n - block + 1)
            out.extend(pool[start:start + block])
        return out[:h]

    return draw


def intraday_sampler(pool: Dict[int, List[Ratio]], first_slot: int, window: int = WINDOW):
    keys = sorted(pool)
    nearest: Dict[int, int] = {}

    def pick(j: int) -> int:
        if j not in nearest:
            nearest[j] = j if j in pool else min(keys, key=lambda k: (abs(k - j), k))
        return nearest[j]

    def draw(rng: random.Random, h: int) -> List[Ratio]:
        return [rng.choice(pool[pick(first_slot + i + rng.randint(-window, window))]) for i in range(h)]

    return draw


# ---------------------------------------------------------------- opções (Black-Scholes)

def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(s: float, k: float, tau: float, r: float, vol: float, kind: str) -> float:
    if tau <= 0 or vol <= 0:
        return max(0.0, s - k) if kind == "CALL" else max(0.0, k - s)
    sq = vol * math.sqrt(tau)
    d1 = (math.log(s / k) + (r + vol * vol / 2) * tau) / sq
    d2 = d1 - sq
    if kind == "CALL":
        return s * _ncdf(d1) - k * math.exp(-r * tau) * _ncdf(d2)
    return k * math.exp(-r * tau) * _ncdf(-d2) - s * _ncdf(-d1)


def implied_vol(price: float, s: float, k: float, tau: float, r: float, kind: str) -> Optional[float]:
    lo, hi = 1e-4, 5.0
    if tau <= 0 or not bs_price(s, k, tau, r, lo, kind) - 1e-9 <= price <= bs_price(s, k, tau, r, hi, kind):
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if bs_price(s, k, tau, r, mid, kind) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def spot_for_premium(premium: float, k: float, tau: float, r: float, vol: float, kind: str, s0: float) -> Optional[float]:
    """Preço do ativo-objeto que faz a opção valer `premium` hoje (para traduzir stop/alvo do prêmio)."""
    lo, hi = s0 / 5, s0 * 5
    f = lambda s: bs_price(s, k, tau, r, vol, kind) - premium  # noqa: E731
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        if (f(mid) > 0) == (kind == "CALL"):
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------- plano e simulação

@dataclass
class Plan:
    ticker: str
    side: str                 # BUY | SELL
    entry: float              # preço de entrada (prêmio, se opção)
    stop: float
    target: float
    source: str = "informado"
    option: Optional[Dict[str, Any]] = None   # kind, strike, expiration, spot, iv, rate, days
    notes: List[str] = field(default_factory=list)

    @property
    def is_buy(self) -> bool:
        return self.side == "BUY"

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def target_r(self) -> float:
        return abs(self.target - self.entry) / self.risk

    def validate(self) -> None:
        if min(self.entry, self.stop, self.target) <= 0:
            raise TMError("Entrada, stop e alvo precisam ser maiores que zero.")
        if self.is_buy and not self.stop < self.entry < self.target:
            raise TMError(f"Na compra o stop fica abaixo e o alvo acima da entrada (entrada {_num(self.entry)}, "
                          f"stop {_num(self.stop)}, alvo {_num(self.target)}).")
        if not self.is_buy and not self.target < self.entry < self.stop:
            raise TMError(f"Na venda o stop fica acima e o alvo abaixo da entrada (entrada {_num(self.entry)}, "
                          f"stop {_num(self.stop)}, alvo {_num(self.target)}).")


def walk(plan: Plan, s0: float, draws: Sequence[Ratio], value: Callable[[float, Optional[float]], float],
         increasing: bool, taus: Sequence[Optional[float]]) -> Tuple[str, float, float]:
    """
    Uma réplica: (resultado, preço de saída do trade, ativo-objeto no fim do horizonte).
    Depois de tocar stop/alvo o caminho segue até o fim, para a distribuição do preço final valer para todas.
    """
    s, buy = s0, plan.is_buy
    hit: Optional[Tuple[str, float]] = None
    for (ro, rh, rl, rc), tau in zip(draws, taus):
        if hit is None:
            o, h, l = s * ro, s * rh, s * rl
            vo = value(o, tau)
            vh, vl = (value(h, tau), value(l, tau)) if increasing else (value(l, tau), value(h, tau))
            if buy:
                if vo <= plan.stop:
                    hit = ("stop", vo)
                elif vo >= plan.target:
                    hit = ("target", vo)
                elif vl <= plan.stop:
                    hit = ("stop", plan.stop)
                elif vh >= plan.target:
                    hit = ("target", plan.target)
            else:
                if vo >= plan.stop:
                    hit = ("stop", vo)
                elif vo <= plan.target:
                    hit = ("target", vo)
                elif vh >= plan.stop:
                    hit = ("stop", plan.stop)
                elif vl <= plan.target:
                    hit = ("target", plan.target)
        s *= rc
    if hit is None:
        return "neither", value(s, taus[-1]), s
    return hit[0], hit[1], s


def _q(sorted_vals: Sequence[float], q: float) -> float:
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


def simulate(plan: Plan, s0: float, sampler, horizon: int, replays: int, seed: int,
             value: Callable[[float, Optional[float]], float], increasing: bool,
             taus: Sequence[Optional[float]]) -> Dict[str, Any]:
    rng = random.Random(seed)
    counts = {"target": 0, "stop": 0, "neither": 0}
    rs: List[float] = []
    finals: List[float] = []
    unders: List[float] = []
    green = 0
    sign = 1 if plan.is_buy else -1
    for _ in range(replays):
        out, exit_v, s_end = walk(plan, s0, sampler(rng, horizon), value, increasing, taus)
        counts[out] += 1
        r = sign * (exit_v - plan.entry) / plan.risk
        rs.append(r)
        finals.append(value(s_end, taus[-1]))
        unders.append(s_end)
        if out == "target" or (out == "neither" and r > 0):
            green += 1
    finals.sort()
    unders.sort()
    rs_sorted = sorted(rs)
    return {
        "p_target": counts["target"] / replays,
        "p_stop": counts["stop"] / replays,
        "p_neither": counts["neither"] / replays,
        "p_green": green / replays,
        "avg_r": sum(rs) / replays,
        "median_r": statistics.median(rs_sorted),
        "worst_r_5": _q(rs_sorted, 0.05),
        "end_value": {"p5": _q(finals, 0.05), "p50": _q(finals, 0.5), "p95": _q(finals, 0.95)},
        "end_underlying": {"p5": _q(unders, 0.05), "p50": _q(unders, 0.5), "p95": _q(unders, 0.95)},
    }


def verdict(p_target: float, p_stop: float, p_neither: float, target_r: float, avg_r: float) -> List[str]:
    """Mesma régua do original: o alvo precisa vir primeiro em 1/(1+R) das réplicas que tocaram um lado."""
    decided = p_target + p_stop
    if decided <= 0:
        return ["Nenhuma réplica tocou stop ou alvo no horizonte: o preço no fim decide tudo."]
    share, be = p_target / decided, 1 / (1 + target_r)
    gap = share - be
    one_r = abs(target_r - 1) < 0.05
    lean = 0
    if abs(gap) < COIN_FLIP:
        head = "Perto de cara ou coroa" if one_r else "Perto do empate"
    elif abs(gap) < STRONG:
        head, lean = ("Pende para o alvo", 1) if gap > 0 else ("Pende para o stop", -1)
    else:
        head, lean = ("Fortemente para o alvo", 1) if gap > 0 else ("Fortemente para o stop", -1)
    lines = [f"{head}: alvo primeiro {_pct(p_target)} vs stop primeiro {_pct(p_stop)} "
             f"(com alvo de {_num(target_r, 1)}R o empate exige o alvo em {be:.0%} das réplicas que tocaram um lado; veio em {share:.0%})."]
    if p_neither > MANY_NEITHER:
        lines.append(f"{_pct(p_neither)} das réplicas não tocaram nenhum dos dois: o preço no fim do horizonte decide essas.")
    if lean and avg_r * lean < 0:
        lines.append(f"O R médio ({_r(avg_r, 3)}) vai contra essa tendência, por causa das réplicas que não tocaram nenhum lado.")
    return lines


def _option_info(ticker: str, strike: Optional[float], expiration: Optional[str], kind: Optional[str],
                 as_of: date) -> Dict[str, Any]:
    info = b3_tickers.decode_option(ticker, as_of) or {}
    kind = (kind or info.get("kind") or "").upper()
    exp = date.fromisoformat(expiration) if expiration else (date.fromisoformat(info["expiration"]) if info.get("expiration") else None)
    if kind not in ("CALL", "PUT") or not exp:
        raise TMError(f"{ticker}: não consegui decodificar a opção — informe --tipo call|put e --vencimento AAAA-MM-DD.")
    if not strike:
        raise TMError(f"{ticker}: informe o --strike (o código da opção na B3 não traz o strike exato).")
    return {"kind": kind, "strike": float(strike), "expiration": exp}


def run(*, ticker: str, side: str, entry: float, stop: Optional[float] = None, target: Optional[float] = None,
        mode: str = "swing", horizon: Optional[int] = None, entry_time: Optional[str] = None,
        until: Optional[str] = None, as_of: Optional[date] = None, bars: Optional[List[Bar]] = None,
        replays: int = 10000, seed: int = 19, stop_atr: Optional[float] = None, target_r: float = 2.0,
        stop_pct: Optional[float] = None, target_pct: Optional[float] = None, strike: Optional[float] = None,
        expiration: Optional[str] = None, option_kind: Optional[str] = None, spot: Optional[float] = None,
        rate: Optional[float] = None, plan_source: Optional[str] = None) -> Dict[str, Any]:
    """
    Prioridade do plano: stop/alvo informados > stop_pct/target_pct (histórico do analista) > ATR do ativo-objeto.
    rate = Selic anual em % (para opções). Retorna um dicionário pronto para report().
    """
    if mode not in ("swing", "intraday"):
        raise TMError("--modo é swing ou intraday.")
    side = "SELL" if str(side).upper() in ("SELL", "VENDA", "V") else "BUY"
    tk = b3_tickers.clean_ticker(ticker)
    is_option = b3_tickers.asset_class(None, tk) == "OPCAO"
    now = now_brt()
    as_of = as_of or now.date()
    entry = float(entry)
    if entry <= 0:
        raise TMError("Informe a entrada (--entrada).")
    bars = bars if bars is not None else fetch_bars(tk, mode)
    daily = bars if mode == "swing" else daily_from_intraday(bars)
    daily_past = [b for b in daily if b[0].date() < as_of]
    notes: List[str] = []

    # ---------------- relógio e horizonte
    if mode == "intraday":
        open_min, n_slots = _grid(as_of)
        if entry_time:
            hh, mm = (int(x) for x in entry_time.split(":")[:2])
            entry_min = hh * 60 + mm
        elif as_of == now.date():
            entry_min = now.hour * 60 + now.minute
        else:
            raise TMError("No modo intraday informe a hora da entrada (--hora HH:MM).")
        close_min = open_min + n_slots * SLOT_MIN
        if until:
            hh, mm = (int(x) for x in until.split(":")[:2])
            until_min = hh * 60 + mm
        else:
            until_min = close_min - 10
        until_min = min(until_min, close_min)
        if entry_min < open_min:
            raise TMError(f"Entrada às {entry_min // 60:02d}:{entry_min % 60:02d} é antes da abertura ({open_min // 60:02d}:{open_min % 60:02d}).")
        first = -(-(entry_min - open_min) // SLOT_MIN)   # barra em andamento na entrada fica de fora
        last = (until_min - open_min) // SLOT_MIN - 1    # última barra que termina até o "zerar até"
        horizon = last - first + 1
        if horizon < 1:
            raise TMError("Não sobra nenhuma barra de 5 min entre a entrada e o horário de zerar.")
        pool, used = intraday_pool(bars, as_of)
        sampler = intraday_sampler(pool, first)
        span = f"{entry_min // 60:02d}:{entry_min % 60:02d} até {until_min // 60:02d}:{until_min % 60:02d} ({horizon} barras de 5 min)"
        pool_desc = f"{used} pregões de 5 min anteriores"
    else:
        horizon = int(horizon or DEFAULT_HORIZON)
        pool = daily_pool(bars, as_of)
        sampler = daily_sampler(pool)
        used = len(pool)
        span = f"próximos {horizon} pregões"
        pool_desc = f"{used} pregões diários anteriores (blocos de {BLOCK} dias)"

    # ---------------- valor do trade em função do ativo-objeto
    option = None
    if is_option:
        option = _option_info(tk, strike, expiration, option_kind, as_of)
        s0 = float(spot) if spot else next((b[4] for b in reversed(bars) if b[0].date() <= as_of), None)
        if not s0:
            raise TMError("Sem preço do ativo-objeto: informe --subjacente.")
        days = business_days_between(as_of, option["expiration"])
        if days < 1:
            raise TMError(f"A opção vence em {option['expiration']:%d/%m/%Y}: sem pregão inteiro pela frente.")
        r = math.log(1 + (rate if rate is not None else 15.0) / 100)
        if mode == "swing":
            if horizon > days:
                notes.append(f"Horizonte cortado no vencimento: {days} pregões (pedido: {horizon}).")
                horizon = days
            taus = [max(0.0, (days - i) / DAYS_YEAR) for i in range(1, horizon + 1)]
            span = f"próximos {horizon} pregões"
        else:
            taus = [max(0.0, (days + (horizon - i) / n_slots) / DAYS_YEAR) for i in range(1, horizon + 1)]
        tau0 = (days + (horizon / n_slots if mode == "intraday" else 0)) / DAYS_YEAR
        iv = implied_vol(entry, s0, option["strike"], tau0, r, option["kind"])
        if iv is None:
            raise TMError(f"Prêmio {_num(entry)} incompatível com {b3_tickers.underlying_of(tk)} a {_num(s0)}, strike "
                          f"{_num(option['strike'])} e {days} pregões até o vencimento (abaixo do valor intrínseco?).")
        option.update({"spot": s0, "iv": iv, "rate": rate if rate is not None else 15.0, "days": days, "tau0": tau0, "r": r})
        if iv > 1.5:
            notes.append(f"Vol implícita de {_num(iv * 100, 0)}%: confira strike, prêmio e ativo-objeto (strike ajustado por "
                         f"provento? grupamento?) antes de confiar nos números.")
        k_, kind_ = option["strike"], option["kind"]
        value = lambda s, tau: bs_price(s, k_, tau if tau is not None else tau0, r, iv, kind_)  # noqa: E731
        increasing = kind_ == "CALL"
    else:
        s0 = entry
        taus = [None] * horizon
        value = lambda s, tau: s  # noqa: E731
        increasing = True

    # ---------------- plano (o TradingFloors não publica stop/alvo)
    sign = 1 if side == "BUY" else -1
    source = plan_source or "informado"
    if stop is None and stop_pct and stop_pct >= 95:
        notes.append(f"Stop do histórico ({_num(stop_pct, 1)}%) equivale a não ter stop: usei o ATR.")
    elif stop is None and stop_pct:
        stop = entry * (1 - sign * stop_pct / 100)
        source = plan_source or f"stop {_num(stop_pct, 1)}% do histórico"
    if stop is None:
        a = atr(daily_past)
        if not a:
            raise TMError("Sem histórico para calcular o ATR: informe --stop.")
        k_atr = stop_atr if stop_atr is not None else DEFAULT_STOP_ATR[mode]
        if is_option:
            # o ativo-objeto andando k ATR contra a opção
            adverse = -sign * (1 if option["kind"] == "CALL" else -1)
            stop = value(s0 + adverse * k_atr * a, None)
            source = plan_source or f"ativo-objeto {_num(k_atr, 1)}×ATR14 contra ({_num(a)})"
        else:
            stop = entry - sign * k_atr * a
            source = plan_source or f"{_num(k_atr, 1)}×ATR14 ({_num(a)})"
    if target is None:
        if target_pct:
            target = entry * (1 + sign * target_pct / 100)
        else:
            target = entry + sign * target_r * abs(entry - stop)
    plan = Plan(tk, side, entry, _round_tick(stop), _round_tick(target), source, option, notes)
    plan.validate()

    sim = simulate(plan, s0, sampler, horizon, replays, seed, value, increasing, taus)
    result: Dict[str, Any] = {
        "ticker": tk,
        "symbol": _safe_symbol(tk),
        "mode": mode,
        "as_of": as_of.isoformat(),
        "span": span,
        "pool": pool_desc,
        "replays": replays,
        "seed": seed,
        "plan": {
            "side": side, "entry": entry, "stop": plan.stop, "target": plan.target, "risk": round(plan.risk, 4),
            "target_r": round(plan.target_r, 2), "source": plan.source,
        },
        **sim,
    }
    if option:
        tau0, r_, iv_ = option["tau0"], option["r"], option["iv"]
        result["option"] = {
            "kind": option["kind"], "strike": option["strike"], "expiration": option["expiration"].isoformat(),
            "days": option["days"], "spot": s0, "iv": round(iv_, 4), "rate": option["rate"],
            "spot_at_stop": spot_for_premium(plan.stop, option["strike"], tau0, r_, iv_, option["kind"], s0),
            "spot_at_target": spot_for_premium(plan.target, option["strike"], tau0, r_, iv_, option["kind"], s0),
        }
    result["verdict"] = verdict(sim["p_target"], sim["p_stop"], sim["p_neither"], plan.target_r, sim["avg_r"])
    result["notes"] = notes
    return result


def _safe_symbol(tk: str) -> str:
    try:
        return yahoo_symbol(tk)
    except TMError:
        return tk


def report(res: Dict[str, Any]) -> str:
    p, opt = res["plan"], res.get("option")
    lado = "COMPRA" if p["side"] == "BUY" else "VENDA"
    unit = "prêmio" if opt else "preço"
    lines = [
        f"{lado} {res['ticker']} — entrada {_num(p['entry'])}, stop {_num(p['stop'])}, alvo {_num(p['target'])} "
        f"({_num(p['target_r'], 1)}R; risco {_num(p['risk'])} por unidade; plano: {p['source']})",
    ]
    if opt:
        ss, st = opt.get("spot_at_stop"), opt.get("spot_at_target")
        lines.append(f"Opção {opt['kind']} strike {_num(opt['strike'])}, vence {date.fromisoformat(opt['expiration']):%d/%m/%Y} "
                     f"({opt['days']} pregões); ativo-objeto {_num(opt['spot'])}; vol implícita {_num(opt['iv'] * 100, 1)}%; Selic {_num(opt['rate'], 2)}%.")
        if ss and st:
            lines.append(f"Hoje, stop ≈ ativo-objeto a {_num(ss)} e alvo ≈ {_num(st)}.")
    lines += [
        f"{_num(res['replays'], 0)} replays ({res['mode']}) dos {res['span']}, a partir de {res['pool']}, semente {res['seed']}.",
        f"  alvo primeiro  {_pct(res['p_target'])}",
        f"  stop primeiro  {_pct(res['p_stop'])}",
        f"  nenhum         {_pct(res['p_neither'])}   ainda aberto no fim do horizonte",
        f"  no verde       {_pct(res['p_green'])}   alvo primeiro, ou acima da entrada no fim (abaixo, na venda)",
        f"  {unit.capitalize()} no fim: mediana {_num(res['end_value']['p50'])}, 90% entre {_num(res['end_value']['p5'])} e {_num(res['end_value']['p95'])}.",
    ]
    if opt:
        u = res["end_underlying"]
        lines.append(f"  Ativo-objeto no fim: mediana {_num(u['p50'])}, 90% entre {_num(u['p5'])} e {_num(u['p95'])}.")
    lines.append(f"  R médio {_r(res['avg_r'], 3)} · R mediano {_r(res['median_r'])} · pior 5% ≤ {_r(res['worst_r_5'])}R (gap além do stop executa na abertura)")
    lines += res["verdict"]
    lines += res.get("notes") or []
    return "\n".join(lines)


__all__ = ["TMError", "Plan", "run", "report", "fetch_bars", "load_csv", "bs_price", "implied_vol", "verdict", "atr"]
