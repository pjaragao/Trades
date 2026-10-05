"""
Calendário e horário do pregão da B3 (sem dependência de tzdata: Brasília é UTC-3 fixo desde 2019).

Horários padrão do mercado à vista/opções (a B3 ajusta conforme o horário de verão dos EUA):
- EUA em horário de verão (mar→nov): negociação 10:00–16:55, call de fechamento 16:55–17:00
- Fora dele:                          negociação 10:00–17:55, call de fechamento 17:55–18:00
- Pré-abertura: 09:45–10:00
Pode ser sobrescrito em config/settings.yaml, seção `market` (open, close, closing_call_end, pre_open).
"""
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, Optional, Set

BRT = timezone(timedelta(hours=-3), "BRT")


def now_brt() -> datetime:
    return datetime.now(BRT)


def to_brt(value: Any) -> Optional[datetime]:
    """Converte ISO string/datetime para datetime em Brasília (naive => assume UTC)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip().replace("Z", "+00:00")
        if " " in s and "T" not in s:
            s = s.replace(" ", "T", 1)
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            try:
                dt = datetime.fromisoformat(s[:19])
            except ValueError:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BRT)


def is_date_only(value: Any) -> bool:
    """O TradingFloors grava muitos sinais só com a data (meia-noite de Brasília = 03:00 UTC)."""
    dt = to_brt(value)
    return dt is not None and dt.hour == 0 and dt.minute == 0 and dt.second == 0


def _easter(year: int) -> date:
    # Algoritmo de Meeus/Jones/Butcher
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=16)
def b3_holidays(year: int) -> Set[date]:
    easter = _easter(year)
    days = {
        date(year, 1, 1),
        easter - timedelta(days=48),  # Carnaval (segunda)
        easter - timedelta(days=47),  # Carnaval (terça)
        easter - timedelta(days=2),   # Sexta-feira Santa
        date(year, 4, 21),
        date(year, 5, 1),
        easter + timedelta(days=60),  # Corpus Christi
        date(year, 9, 7),
        date(year, 10, 12),
        date(year, 11, 2),
        date(year, 11, 15),
        date(year, 12, 24),
        date(year, 12, 25),
        date(year, 12, 31),
    }
    if year >= 2024:
        days.add(date(year, 11, 20))  # Consciência Negra (feriado nacional desde 2024)
    return days


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in b3_holidays(d.year)


def previous_business_day(d: date) -> date:
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def next_business_day(d: date) -> date:
    d += timedelta(days=1)
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def business_days_between(start: date, end: date) -> int:
    """Dias úteis em (start, end]."""
    if end <= start:
        return 0
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if is_business_day(d):
            n += 1
    return n


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def us_dst_active(d: date) -> bool:
    start = _nth_weekday(d.year, 3, 6, 2)   # 2º domingo de março
    end = _nth_weekday(d.year, 11, 6, 1)   # 1º domingo de novembro
    return start <= d < end


def option_expiration(year: int, month: int, week: Optional[int] = None) -> date:
    """Vencimento de opções de ações na B3: 3ª sexta-feira (ou a sexta da semana W1..W5), recuando se feriado."""
    nth = week or 3
    try:
        d = _nth_weekday(year, month, 4, nth)
        if d.month != month:
            raise ValueError
    except ValueError:
        d = _nth_weekday(year, month, 4, 4)
    return previous_business_day(d)


def _parse_hhmm(value: Any, default: time) -> time:
    try:
        hh, mm = str(value).split(":")[:2]
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return default


def session_times(d: date) -> Dict[str, time]:
    from src.core.config import load_yaml

    override = load_yaml().get("market", {}) or {}
    if us_dst_active(d):
        close, call_end = time(16, 55), time(17, 0)
    else:
        close, call_end = time(17, 55), time(18, 0)
    return {
        "pre_open": _parse_hhmm(override.get("pre_open"), time(9, 45)),
        "open": _parse_hhmm(override.get("open"), time(10, 0)),
        "close": _parse_hhmm(override.get("close"), close),
        "closing_call_end": _parse_hhmm(override.get("closing_call_end"), call_end),
    }


def market_status(at: Optional[datetime] = None) -> Dict[str, Any]:
    """Fase atual do pregão: open | pre_open | closing_call | closed (+ rótulo e próximo evento)."""
    now = (at or now_brt()).astimezone(BRT)
    today = now.date()
    t = now.time()

    def fmt(x: time) -> str:
        return x.strftime("%H:%M")

    if not is_business_day(today):
        nxt = next_business_day(today)
        reason = "feriado" if today.weekday() < 5 else "fim de semana"
        return {
            "phase": "closed",
            "label": "Pregão fechado",
            "detail": f"{reason.capitalize()} · abre {nxt.strftime('%d/%m')} às {fmt(session_times(nxt)['open'])}",
            "is_open": False,
        }

    s = session_times(today)
    if s["pre_open"] <= t < s["open"]:
        return {"phase": "pre_open", "label": "Pré-abertura", "detail": f"Leilão até {fmt(s['open'])}", "is_open": False}
    if s["open"] <= t < s["close"]:
        return {"phase": "open", "label": "Pregão aberto", "detail": f"Fecha às {fmt(s['close'])}", "is_open": True}
    if s["close"] <= t < s["closing_call_end"]:
        return {"phase": "closing_call", "label": "Call de fechamento", "detail": f"Leilão até {fmt(s['closing_call_end'])}", "is_open": False}
    if t < s["pre_open"]:
        return {"phase": "closed", "label": "Pregão fechado", "detail": f"Abre hoje às {fmt(s['open'])}", "is_open": False}
    nxt = next_business_day(today)
    return {
        "phase": "closed",
        "label": "Pregão encerrado",
        "detail": f"Abre {nxt.strftime('%d/%m')} às {fmt(session_times(nxt)['open'])}",
        "is_open": False,
    }
