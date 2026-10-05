"""
Cotações ao vivo.

Fontes, da melhor para a pior (cada ativo usa a melhor disponível):
- mt5           : terminal MetaTrader 5 da corretora — tempo real, com bid/ask (agente no Windows ou MT5 local);
- brapi         : brapi.dev — só ações, dados renovados a cada 30 min (plano gratuito, ritmo em BrapiBudget);
- tradingfloors : `preco_atual` das opções abertas nos sinais (gravado pelo monitor) — atraso desconhecido;
- manual        : digitado na Carteira.

Reserva: se o MT5 cair ou não tiver cotação de um ativo, ações passam para a brapi e opções voltam ao preço do
TradingFloors em ~2 min — e a tela avisa qual fonte está valendo.

O feed é uma thread: no pregão consulta o MT5 a cada QUOTES_INTERVAL segundos (padrão 2) e a brapi no ritmo
do orçamento, para os ativos que importam — posições (real e simulação), ordens abertas, o que estiver aberto
na tela e os sinais abertos dos analistas seguidos —, grava as mudanças na tabela `quotes` e acorda os
navegadores conectados em /api/stream (SSE). Com ordens abertas, também confere os preenchimentos.
"""
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.core import b3_tickers, db
from src.core.config import market_data_flags, now_iso, now_utc
from src.core.market_hours import BRT, is_business_day, market_status, now_brt, session_times, to_brt
from src.integrations.market_data import ProviderError, make_providers

log = logging.getLogger("copiloto.quotes")

WATCH_REFRESH_SECONDS = 20      # recalcula a lista de ativos acompanhados
ADHOC_TTL_SECONDS = 600         # ativo aberto na tela (boleta/modal) fica acompanhado por 10 min
DB_TOUCH_SECONDS = 30           # cotação sem mudança é regravada no banco no máximo a cada 30 s
LIVE_MAX_AGE_SECONDS = 15 * 60  # cotação em tempo real mais velha que isso sai da memória
DELAYED_MAX_AGE_SECONDS = 24 * 3600  # cotação atrasada (brapi) vale até 24 h (a tela mostra o horário dela)
MT5_FALLBACK_MINUTES = 2        # MT5 sem atualizar há mais que isso: TradingFloors volta a valer (reserva)
BETTER_SOURCE_MINUTES = 30      # TradingFloors não sobrescreve brapi/manual mais novos que isso
ORDER_SYNC_SECONDS = 5
LIVE_CLASSES = ("ACAO", "OPCAO")


def mark_price(q: Dict[str, Any]) -> Optional[float]:
    """Preço para marcar a posição: último negócio; sem negócio, o meio do book."""
    if q.get("last"):
        return float(q["last"])
    bid, ask = q.get("bid"), q.get("ask")
    if bid and ask:
        return round((float(bid) + float(ask)) / 2, 4)
    return float(bid or ask) if (bid or ask) else None


def upsert_quote(conn, ticker: str, price: float, source: str, *, bid=None, ask=None, last=None,
                 quote_time=None, change_pct=None, now: Optional[str] = None) -> None:
    conn.execute(
        "INSERT INTO quotes(ticker, price, source, updated_at, bid, ask, last, quote_time, change_pct) VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(ticker) DO UPDATE SET price = excluded.price, source = excluded.source, updated_at = excluded.updated_at, "
        "bid = excluded.bid, ask = excluded.ask, last = excluded.last, quote_time = excluded.quote_time, change_pct = excluded.change_pct",
        (ticker, float(price), source, now or now_iso(), bid, ask, last, quote_time, change_pct),
    )


def upsert_tradingfloors_quote(conn, ticker: str, price: Optional[float], now: str) -> None:
    """
    Preço do TradingFloors (reserva): entra se a cotação atual for do próprio TradingFloors, se o MT5 parou de
    atualizar há mais de MT5_FALLBACK_MINUTES (o feed regrava a cada 30 s) ou se brapi/manual estiver velho.
    """
    if price is None or not ticker:
        return
    mt5_cutoff = (now_utc() - timedelta(minutes=MT5_FALLBACK_MINUTES)).isoformat(timespec="seconds")
    cutoff = (now_utc() - timedelta(minutes=BETTER_SOURCE_MINUTES)).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO quotes(ticker, price, source, updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(ticker) DO UPDATE SET price = excluded.price, source = excluded.source, updated_at = excluded.updated_at, "
        "bid = NULL, ask = NULL, last = NULL, quote_time = NULL, change_pct = NULL "
        "WHERE quotes.source = 'tradingfloors' OR (quotes.source = 'mt5' AND quotes.updated_at < ?) OR quotes.updated_at < ?",
        (ticker, float(price), "tradingfloors", now, mt5_cutoff, cutoff),
    )


class BrapiBudget:
    """
    Dimensiona as consultas à brapi para caber no plano gratuito — 15.000 requisições numa janela móvel de
    30 dias (~500/dia), um ativo por requisição, dados renovados a cada 30 min:
    - teto diário (BRAPI_DAILY_BUDGET, padrão 450 = 90% de 500), contado no banco (sobrevive a reinícios);
    - no pregão, cada ação no máximo a cada 30 min; com muitas ações o intervalo cresce para o teto durar até o
      fechamento;
    - depois do pregão, uma consulta por ação para o fechamento; fora do pregão, só o que nunca teve preço;
    - se a brapi disser que restam poucas requisições na janela (< BRAPI_RESERVE) ou responder 429, pausa.
    """

    MAX_PER_CYCLE = 5

    def __init__(self, daily_budget: int = 450, min_interval: float = 1800, reserve: int = 1000):
        self.daily_budget = int(daily_budget)
        self.min_interval = float(min_interval)
        self.reserve = int(reserve)
        self.last: Dict[str, float] = {}        # epoch da última consulta por ativo
        self.skip_until: Dict[str, float] = {}  # ativos recusados (fora do plano/inexistentes)
        self.paused_until = 0.0
        self.pause_reason = ""
        self.remaining: Optional[int] = None
        self.limit: Optional[int] = None
        self.interval = self.min_interval

    @staticmethod
    def _key(d) -> str:
        return f"brapi_used:{d.isoformat()}"

    def used_today(self, now: Optional[datetime] = None) -> int:
        return int(db.kv_get(self._key((now or now_brt()).date())) or 0)

    def add_used(self, n: int = 1) -> None:
        today = now_brt().date()
        with db.transaction() as c:
            c.execute("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = CAST(kv.value AS INTEGER) + ?",
                      (self._key(today), str(n), n))
            c.execute("DELETE FROM kv WHERE key LIKE 'brapi_used:%' AND key < ?", (self._key(today - timedelta(days=40)),))

    def pause(self, seconds: float, reason: str) -> None:
        self.paused_until = max(self.paused_until, time.time() + seconds)
        self.pause_reason = reason

    def after_fetch(self, provider, requested: Iterable[str]) -> None:
        ts = time.time()
        for t in requested:
            self.last[t] = ts
        for t in provider.unsupported:
            self.skip_until[t] = ts + 86400
        if provider.remaining is not None:
            self.remaining, self.limit = provider.remaining, provider.limit
        if provider.retry_after:
            self.pause(provider.retry_after, "a brapi pediu para aguardar (cota da janela de 30 dias ou requisições simultâneas)")

    def due(self, tickers: List[str], now: Optional[datetime] = None, eager: bool = False) -> List[str]:
        now = (now or now_brt()).astimezone(BRT)
        ts = now.timestamp()
        if ts < self.paused_until:
            return []
        if self.remaining is not None and self.remaining <= self.reserve:
            tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), BRT)
            self.pause((tomorrow - now).total_seconds(), f"restam só {self.remaining} requisições na janela de 30 dias da brapi")
            return []
        left = self.daily_budget - self.used_today(now)
        if left <= 0:
            return []
        cands = [t for t in tickers if self.skip_until.get(t, 0) <= ts]
        if not cands:
            return []
        today = now.date()
        s = session_times(today)
        open_dt = datetime.combine(today, s["open"], BRT)
        close_dt = datetime.combine(today, s["close"], BRT)
        settle_dt = datetime.combine(today, s["closing_call_end"], BRT) + timedelta(seconds=self.min_interval)
        if eager:  # boleta aberta na tela: busca se nunca buscou ou se a brapi já renovou o dado
            out = [t for t in cands if ts - self.last.get(t, 0) >= self.min_interval]
        elif is_business_day(today) and open_dt <= now < close_dt:
            n = len(cands)
            spare = left - n  # guarda uma consulta por ação para o fechamento
            self.interval = max(self.min_interval, (close_dt - now).total_seconds() * n / spare) if spare > 0 else float("inf")
            out = [t for t in cands if ts - self.last.get(t, 0) >= self.interval]
        elif is_business_day(today) and now >= settle_dt:
            out = [t for t in cands if self.last.get(t, 0) < settle_dt.timestamp()]  # preço de fechamento
        else:
            out = [t for t in cands if t not in self.last]  # nunca teve preço
        out.sort(key=lambda t: self.last.get(t, 0))
        return out[: min(self.MAX_PER_CYCLE, left)]

    def status(self) -> Dict[str, Any]:
        paused = self.paused_until > time.time()
        return {
            "used_today": self.used_today(),
            "daily_budget": self.daily_budget,
            "remaining": self.remaining,
            "limit": self.limit,
            "interval_minutes": None if self.interval == float("inf") else round(self.interval / 60),
            "paused": paused,
            "pause_reason": self.pause_reason if paused else "",
        }


class QuoteFeed:
    def __init__(self, provider_factory: Callable[..., Tuple[Any, Any]] = make_providers,
                 flags_loader: Callable[[], Dict[str, Any]] = market_data_flags):
        self.provider_factory = provider_factory
        self.flags_loader = flags_loader
        self._flags: Dict[str, Any] = {}
        self._flags_at = 0.0
        self._rt = None      # fonte em tempo real (MT5)
        self._slow = None    # fonte atrasada (brapi)
        self._budget: Optional[BrapiBudget] = None
        self._providers_key: Optional[Tuple] = None
        self._provider_error: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._run_lock = threading.Lock()
        self._cond = threading.Condition()
        self._version = 0
        self._live: Dict[str, Dict[str, Any]] = {}
        self._adhoc: Dict[str, float] = {}
        self._watch: List[str] = []
        self._watch_at = 0.0
        self._has_open_orders = False
        self._db_touch: Dict[str, float] = {}
        self._last_order_sync = 0.0
        self._rt_errors = 0
        self._rt_error = ""
        self._rt_missing: List[str] = []
        self._slow_error = ""
        self._slow_ok_at: Optional[str] = None
        self._state: Dict[str, Any] = {"state": "starting", "message": "", "last_ok_at": None, "latency_ms": None}
        self._last_ok_mono = 0.0

    # ------------------------------------------------------------------ ciclo de vida
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="quote-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # nunca derrubar a thread
                log.exception("Erro no feed de cotações")
            self._wake.wait(self.interval())
            self._wake.clear()

    def interval(self) -> float:
        flags = self.flags()
        closed = market_status()["phase"] == "closed"
        if self._rt is not None:
            if self._rt_errors:
                return min(60.0, flags["interval"] * 2 ** min(self._rt_errors, 5))
            if closed:
                return min(flags["closed_interval"], 60.0) if self._slow is not None else flags["closed_interval"]
            return flags["interval"]
        if self._slow is not None:  # só brapi: o orçamento decide o que consultar a cada volta
            return 60.0 if closed else 30.0
        return 60.0

    # ------------------------------------------------------------------ configuração
    def flags(self, refresh: bool = False) -> Dict[str, Any]:
        if refresh or not self._flags or time.monotonic() - self._flags_at > WATCH_REFRESH_SECONDS:
            self._flags = self.flags_loader()
            self._flags_at = time.monotonic()
        return self._flags

    def _count_brapi(self) -> None:
        if self._budget is not None:
            self._budget.add_used(1)

    def _get_providers(self) -> Tuple[Any, Any]:
        flags = self.flags()
        key = (flags["mt5"], flags["brapi"], flags.get("brapi_token"), flags.get("brapi_daily_budget"))
        if key != self._providers_key:
            self._providers_key, self._rt, self._slow, self._provider_error = key, None, None, None
            try:
                self._rt, self._slow = self.provider_factory(flags, self._count_brapi)
            except Exception as exc:
                self._provider_error = str(exc)
                log.warning("Fonte de cotações indisponível: %s", exc)
            self._budget = BrapiBudget(flags["brapi_daily_budget"], flags["brapi_min_interval"], flags["brapi_reserve"]) if self._slow else None
            if self._budget:
                self._seed_delayed()
        return self._rt, self._slow

    def _seed_delayed(self) -> None:
        """Depois de reiniciar: reaproveita as cotações da brapi já gravadas (não gasta requisições de novo)."""
        now_m, now_ts = time.monotonic(), time.time()
        with db.connection() as c:
            rows = c.execute("SELECT * FROM quotes WHERE source = 'brapi'").fetchall()
        for r in rows:
            at = to_brt(r["updated_at"])
            if not at:
                continue
            age = max(0.0, now_ts - at.timestamp())
            self._budget.last[r["ticker"]] = at.timestamp()
            if age <= DELAYED_MAX_AGE_SECONDS and r["ticker"] not in self._live:
                self._live[r["ticker"]] = {
                    "ticker": r["ticker"], "price": r["price"], "bid": r["bid"], "ask": r["ask"], "last": r["last"],
                    "time": r["quote_time"], "change_pct": r["change_pct"], "source": "brapi", "realtime": False,
                    "delay_minutes": self._slow.delay_minutes, "at": r["updated_at"], "_mono": now_m - age,
                }
                self._db_touch[r["ticker"]] = now_m

    # ------------------------------------------------------------------ ativos acompanhados
    def watch(self, tickers: Iterable[str]) -> List[str]:
        """Acompanha ativos abertos na tela por alguns minutos. Devolve os que eram novos."""
        expires = time.monotonic() + ADHOC_TTL_SECONDS
        new = []
        for t in tickers:
            t = b3_tickers.clean_ticker(t)
            if not t or b3_tickers.asset_class(None, t) not in LIVE_CLASSES:
                continue
            if t not in self._adhoc and t not in self._watch:
                new.append(t)
            self._adhoc[t] = expires
        if new:
            self._watch_at = 0.0
        return new

    def watchlist(self, force: bool = False) -> List[str]:
        now = time.monotonic()
        if force or now - self._watch_at > WATCH_REFRESH_SECONDS:
            self._watch = self._compute_watch()
            self._watch_at = now
        return self._watch

    def _compute_watch(self) -> List[str]:
        from src.services import journal, signals

        now = time.monotonic()
        self._adhoc = {t: exp for t, exp in self._adhoc.items() if exp > now}
        tickers: List[str] = []
        with db.connection() as c:
            for account in ("real", "paper"):
                tickers += [p["ticker"] for p in journal.ledger(c, account)["positions"]]
            rows = c.execute("SELECT DISTINCT ticker FROM orders WHERE status IN ('sending', 'open', 'partial')").fetchall()
            self._has_open_orders = bool(rows)
            tickers += [r[0] for r in rows]
            tickers += list(self._adhoc)
            tickers += [s["ticker"] for s in signals.open_followed(c)]
        out = [t for t in dict.fromkeys(b3_tickers.clean_ticker(t) for t in tickers)
               if t and b3_tickers.asset_class(None, t) in LIVE_CLASSES]
        return out[: self.flags()["max_tickers"]]

    # ------------------------------------------------------------------ consulta
    def run_once(self, only: Optional[List[str]] = None) -> Dict[str, Any]:
        """Um ciclo: busca as cotações dos ativos acompanhados (ou só de `only`) e publica as mudanças."""
        with self._run_lock:
            result = self._cycle(only)
        if only is None:
            self._maybe_sync_orders()  # fora do lock: a conferência de ordens pode demorar
        return result

    def _rt_live(self, ticker: str) -> bool:
        e = self._live.get(ticker)
        return bool(e and e["realtime"] and not self._rt_errors and self._public(e, time.monotonic())["live"])

    def _cycle(self, only: Optional[List[str]]) -> Dict[str, Any]:
        rt, slow = self._get_providers()
        if rt is None and slow is None:
            self._set_state("error" if self._provider_error else "off",
                            self._provider_error or "Sem fonte de cotação ao vivo — usando o preço do TradingFloors")
            return {"fetched": 0, "changed": []}
        watch = list(only) if only is not None else self.watchlist()
        changed: List[str] = []
        fetched = 0

        # 1) tempo real (MT5): tudo o que ele cobre
        if rt is not None:
            tickers = [t for t in watch if rt.supports(t)]
            if tickers:
                t0 = time.monotonic()
                try:
                    got = rt.fetch(tickers)
                except ProviderError as exc:
                    self._rt_errors += 1
                    self._rt_error = str(exc)
                else:
                    self._rt_errors, self._rt_error = 0, ""
                    self._last_ok_mono = time.monotonic()
                    self._rt_missing = [t for t, q in got.items() if not q]
                    changed += self._store(rt, got)
                    fetched += len(tickers)
                    self._state.update(latency_ms=int((time.monotonic() - t0) * 1000), last_ok_at=now_iso())

        # 2) brapi: ações sem cotação ao vivo do MT5, no ritmo do orçamento
        if slow is not None and self._budget is not None:
            cands = [t for t in watch if slow.supports(t) and not self._rt_live(t)]
            due = self._budget.due(cands, eager=only is not None)
            if due:
                try:
                    got = slow.fetch(due)
                    self._slow_error = ""
                    self._slow_ok_at = now_iso()
                except ProviderError as exc:
                    got = {}
                    self._slow_error = str(exc)
                    self._budget.pause(3600, str(exc))
                self._budget.after_fetch(slow, list(got))
                changed += self._store(slow, got)
                fetched += len(got)

        self._refresh_state(rt, slow, force_bump=bool(changed))
        return {"fetched": fetched, "changed": changed}

    def _refresh_state(self, rt, slow, force_bump: bool = False) -> None:
        if rt is not None and self._rt_errors:
            reserve = "brapi (ações) e TradingFloors" if slow is not None else "TradingFloors"
            self._set_state("error", f"{self._rt_error} — usando {reserve}", force_bump)
        elif rt is not None:
            msg = f"sem cotação no MT5: {', '.join(self._rt_missing[:5])}" if self._rt_missing else ""
            self._set_state("live", msg, force_bump)
        elif self._slow_error:
            self._set_state("error", f"{self._slow_error} — usando TradingFloors", force_bump)
        else:
            b = self._budget.status() if self._budget else {}
            self._set_state("delayed", b.get("pause_reason") or "", force_bump)

    def ensure(self, tickers: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """Acompanha e busca já (boleta aberta na tela). Devolve as cotações conhecidas desses ativos."""
        wanted = [b3_tickers.clean_ticker(t) for t in tickers if t]
        self.watch(wanted)
        missing = [t for t in wanted if not self.live_quote(t)]
        rt, slow = self._get_providers()
        if missing and (rt is not None or slow is not None):
            self.run_once(only=missing)
        _, snap = self.snapshot()
        return {t: snap[t] for t in wanted if t in snap}

    def ensure_fresh(self, max_age: float = 10.0) -> bool:
        """Antes da automação decidir: garante cotações com no máximo `max_age` segundos (fonte em tempo real)."""
        rt, _ = self._get_providers()
        if rt is None:
            return False
        if time.monotonic() - self._last_ok_mono > max_age:
            self.run_once()
        return True

    def _store(self, provider, got: Dict[str, Optional[Dict[str, Any]]]) -> List[str]:
        now_m, now_s = time.monotonic(), now_iso()
        changed, to_write = [], []
        for ticker, q in got.items():
            price = mark_price(q) if q else None
            if price is None:
                continue
            entry = {
                "ticker": ticker, "price": price, "bid": q.get("bid"), "ask": q.get("ask"), "last": q.get("last"),
                "time": q.get("time"), "change_pct": q.get("change_pct"), "source": provider.name,
                "realtime": provider.realtime, "delay_minutes": provider.delay_minutes, "at": now_s, "_mono": now_m,
            }
            prev = self._live.get(ticker)
            diff = prev is None or prev["source"] != entry["source"] or any(
                prev.get(k) != entry[k] for k in ("price", "bid", "ask", "last", "change_pct"))
            self._live[ticker] = entry
            if diff:
                changed.append(ticker)
            if diff or now_m - self._db_touch.get(ticker, 0) > DB_TOUCH_SECONDS:
                to_write.append(entry)
                self._db_touch[ticker] = now_m
        if to_write:
            with db.transaction() as c:
                for e in to_write:
                    upsert_quote(c, e["ticker"], e["price"], e["source"], bid=e["bid"], ask=e["ask"], last=e["last"],
                                 quote_time=e["time"], change_pct=e["change_pct"], now=now_s)
        return changed

    def _maybe_sync_orders(self) -> None:
        if not self._has_open_orders or time.monotonic() - self._last_order_sync < ORDER_SYNC_SECONDS:
            return
        self._last_order_sync = time.monotonic()
        try:
            from src.execution import orders

            stats = orders.sync_open_orders()
            if stats.get("closed") or stats.get("fills"):
                self._watch_at = 0.0
        except Exception as exc:
            log.warning("Falha ao conferir ordens abertas: %s", exc)

    # ------------------------------------------------------------------ publicação (SSE)
    def _set_state(self, state: str, message: str, force_bump: bool = False) -> None:
        changed = state != self._state["state"] or message != self._state["message"]
        self._state.update(state=state, message=message)
        if changed or force_bump:
            with self._cond:
                self._version += 1
                self._cond.notify_all()

    def wait(self, version: int, timeout: float) -> int:
        with self._cond:
            self._cond.wait_for(lambda: self._version != version or self._stop.is_set(), timeout)
            return self._version

    def _valid(self, e: Dict[str, Any], now_m: float) -> bool:
        return now_m - e["_mono"] <= (LIVE_MAX_AGE_SECONDS if e["realtime"] else DELAYED_MAX_AGE_SECONDS)

    def _public(self, e: Dict[str, Any], now_m: float) -> Dict[str, Any]:
        age = now_m - e["_mono"]
        live = (e["realtime"] and self._rt is not None and not self._rt_errors
                and age <= max(15.0, 5 * self.flags()["interval"]))
        out = {k: v for k, v in e.items() if not k.startswith("_")}
        out.update(live=bool(live), age_seconds=int(age))
        return out

    def snapshot(self) -> Tuple[int, Dict[str, Dict[str, Any]]]:
        now_m = time.monotonic()
        return self._version, {t: self._public(e, now_m) for t, e in list(self._live.items()) if self._valid(e, now_m)}

    def live_quote(self, ticker: Optional[str]) -> Optional[Dict[str, Any]]:
        """Cotação utilizável agora: MT5 só enquanto está ao vivo (senão vale a reserva); brapi até 24 h."""
        e = self._live.get(ticker or "")
        if not e:
            return None
        now_m = time.monotonic()
        if not self._valid(e, now_m):
            return None
        q = self._public(e, now_m)
        return q if (q["live"] or not e["realtime"]) else None

    def fallback_reason(self, ticker: Optional[str]) -> Optional[str]:
        """Com MT5 configurado mas sem cotação ao vivo deste ativo: por quê (para avisar que vale o TradingFloors)."""
        rt = self._rt
        if not self.running or rt is None or self.live_quote(ticker):
            return None
        if self._rt_errors:
            return f"{rt.label} indisponível"
        return f"{rt.label} sem cotação de {ticker}"

    def status(self) -> Dict[str, Any]:
        flags = self.flags()
        rt, slow = self._rt, self._slow
        primary = rt or slow
        out = {
            **self._state,
            "provider": primary.name if primary else ("error" if self._provider_error else "off"),
            "label": primary.label if primary else "TradingFloors",
            "realtime": rt is not None,
            "delay_minutes": slow.delay_minutes if slow is not None and rt is None else None,
            "interval": self.interval() if self.running else flags["interval"],
            "watching": len(self._watch),
            "running": self.running,
            "brapi": None,
        }
        if slow is not None and self._budget is not None:
            out["brapi"] = {**self._budget.status(), "error": self._slow_error, "last_ok_at": self._slow_ok_at}
        return out


_feed: Optional[QuoteFeed] = None
_feed_lock = threading.Lock()


def get_feed() -> QuoteFeed:
    global _feed
    with _feed_lock:
        if _feed is None:
            _feed = QuoteFeed()
        return _feed


def live_quote(ticker: Optional[str]) -> Optional[Dict[str, Any]]:
    """Cotação do feed (em memória) se houver uma utilizável; None caso contrário (vale o banco/TradingFloors)."""
    return _feed.live_quote(ticker) if _feed is not None else None


def fallback_reason(ticker: Optional[str]) -> Optional[str]:
    return _feed.fallback_reason(ticker) if _feed is not None else None


__all__ = ["BrapiBudget", "QuoteFeed", "get_feed", "live_quote", "fallback_reason", "mark_price", "upsert_quote",
           "upsert_tradingfloors_quote"]
