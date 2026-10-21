"""
Sincronizador externo para:
1. Varrer TODOS os vídeos de um canal do YouTube (ex: @norisknogainoficial) via yt-dlp.
2. Extrair transcrições dos vídeos de estratégias via youtube-transcript-api.
3. Baixar séries históricas multi-timeframe (1d, 60m, 15m, 5m) do Ibovespa (^BVSP, BOVA11.SA) e Blue Chips B3 via yfinance.
"""

import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parents[2]
ROBO_DATA_DIR = ROOT_DIR / "robo_lab" / "data"
EXISTING_CACHE_DB = ROOT_DIR / "strategies" / "data_cache" / "market_prices.db"
MARKET_CACHE_DB = ROBO_DATA_DIR / "market_cache.db"

STRATEGY_KEYWORDS = [
    "robô", "robo", "estratégia", "estrategia", "setup", "day trade", "swing trade",
    "keltner", "fvg", "fair value gap", "gradiente", "cash bands", "bandas",
    "média", "media", "madrid", "vwap", "ifr", "rsi", "z-score", "zscore",
    "consolidação", "consolidacao", "range", "rompimento", "pullback", "scalp",
    "mini índice", "mini indice", "winfut", "wdofut", "dólar", "dolar", "backtest",
    "preço médio", "preco medio", "gain", "loss", "stop", "alvo", "candle",
    "fluxo", "volume", "automação", "automacao", "mt5", "metatrader", "profit"
]


def init_market_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv_bars (
                symbol TEXT,
                timeframe TEXT,
                ts TEXT,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (symbol, timeframe, ts)
            )
        """)
        conn.commit()


def import_existing_daily_cache(target_db: Path, source_db: Path) -> int:
    if not source_db.exists():
        return 0
    count = 0
    with sqlite3.connect(source_db) as src, sqlite3.connect(target_db) as dst:
        rows = src.execute("SELECT symbol, date, open, high, low, close, volume FROM daily_bars").fetchall()
        dst.executemany(
            "INSERT OR IGNORE INTO ohlcv_bars (symbol, timeframe, ts, open, high, low, close, volume) VALUES (?, '1d', ?, ?, ?, ?, ?, ?)",
            [(r[0], r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows]
        )
        count = len(rows)
        dst.commit()
    return count


def fetch_channel_videos(channel_url: str, max_videos: int = 250) -> Dict[str, Any]:
    import yt_dlp

    clean_url = channel_url.rstrip("/")
    if not clean_url.endswith("/videos"):
        videos_url = clean_url + "/videos"
    else:
        videos_url = clean_url

    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "playlistend": max_videos,
        "socket_timeout": 15,
    }

    print(f"[YouTube] Listando vídeos de {videos_url} (até {max_videos})...")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(videos_url, download=False)

    entries = info.get("entries") or []
    videos = []
    strategy_candidates = []

    for idx, entry in enumerate(entries):
        if not entry:
            continue
        vid = entry.get("id")
        title = entry.get("title") or ""
        desc = entry.get("description") or ""
        text_lower = f"{title} {desc}".lower()
        matched = [kw for kw in STRATEGY_KEYWORDS if kw in text_lower]

        v_obj = {
            "index": idx + 1,
            "video_id": vid,
            "title": title,
            "url": f"https://www.youtube.com/watch?v={vid}" if vid else "",
            "duration": entry.get("duration"),
            "view_count": entry.get("view_count"),
            "matched_keywords": matched,
            "is_strategy_candidate": len(matched) > 0,
        }
        videos.append(v_obj)
        if matched:
            strategy_candidates.append(v_obj)

    return {
        "channel_id": info.get("channel_id") or info.get("id"),
        "channel_name": info.get("channel") or info.get("uploader") or info.get("title") or "No Risk No Gain",
        "channel_url": channel_url,
        "fetched_at": datetime.now().isoformat(),
        "total_videos_found": len(videos),
        "strategy_videos_count": len(strategy_candidates),
        "all_videos": videos,
        "strategy_videos": strategy_candidates,
    }


def fetch_transcripts_for_candidates(candidates: List[Dict[str, Any]], out_dir: Path, max_transcripts: int = 25) -> Dict[str, str]:
    from youtube_transcript_api import YouTubeTranscriptApi

    out_dir.mkdir(parents=True, exist_ok=True)
    api = YouTubeTranscriptApi()
    saved: Dict[str, str] = {}

    # Prioriza vídeos com mais keywords operacionais e mais visualizações
    sorted_cands = sorted(
        candidates,
        key=lambda x: (len(x.get("matched_keywords", [])), x.get("view_count") or 0),
        reverse=True,
    )[:max_transcripts]

    print(f"[YouTube] Buscando transcrições para os {len(sorted_cands)} vídeos mais relevantes...")
    for c in sorted_cands:
        vid = c.get("video_id")
        if not vid:
            continue
        t_file = out_dir / f"{vid}.txt"
        if t_file.exists() and t_file.stat().st_size > 100:
            saved[vid] = t_file.read_text(encoding="utf-8")
            continue
        try:
            transcript = api.fetch(vid, languages=["pt", "pt-BR", "en"])
            text = " ".join(s.text for s in transcript.snippets)
            if text:
                t_file.write_text(text, encoding="utf-8")
                saved[vid] = text
                print(f"  + Transcrição salva: {vid} ({len(text):,} chars) - {c.get('title')[:50]}")
        except Exception as exc:
            print(f"  - Sem transcrição para {vid}: {type(exc).__name__}")
    return saved


def sync_yfinance_data(db_path: Path) -> None:
    import yfinance as yf

    symbols_1d = ["^BVSP", "BOVA11.SA", "VALE3.SA", "PETR4.SA", "ITUB4.SA", "BBAS3.SA", "B3SA3.SA", "WEGE3.SA", "PRIO3.SA"]
    intraday_symbols = ["^BVSP", "BOVA11.SA", "VALE3.SA", "PETR4.SA"]
    intraday_plans = [
        ("60m", "720d"),
        ("15m", "59d"),
        ("5m", "59d"),
    ]

    with sqlite3.connect(db_path) as conn:
        for sym in symbols_1d:
            try:
                print(f"[yfinance] Baixando 1d para {sym} (desde 2018-01-01)...")
                df = yf.Ticker(sym).history(start="2018-01-01", interval="1d", auto_adjust=True)
                if not df.empty:
                    rows = []
                    for ts, row in df.iterrows():
                        ts_str = ts.strftime("%Y-%m-%d")
                        rows.append((sym, "1d", ts_str, float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), float(row["Volume"] or 0)))
                    conn.executemany(
                        "INSERT OR REPLACE INTO ohlcv_bars (symbol, timeframe, ts, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        rows,
                    )
                    conn.commit()
                    print(f"  -> {sym} [1d]: {len(rows)} barras salvas.")
            except Exception as e:
                print(f"  -> Aviso em {sym} [1d]: {e}")

        for sym in intraday_symbols:
            for tf, period in intraday_plans:
                try:
                    print(f"[yfinance] Baixando {tf} ({period}) para {sym}...")
                    df = yf.Ticker(sym).history(period=period, interval=tf, auto_adjust=True)
                    if not df.empty:
                        rows = []
                        for ts, row in df.iterrows():
                            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
                            rows.append((sym, tf, ts_str, float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"]), float(row["Volume"] or 0)))
                        conn.executemany(
                            "INSERT OR REPLACE INTO ohlcv_bars (symbol, timeframe, ts, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            rows,
                        )
                        conn.commit()
                        print(f"  -> {sym} [{tf}]: {len(rows)} barras salvas.")
                except Exception as e:
                    print(f"  -> Aviso em {sym} [{tf}]: {e}")


def main():
    channel_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/@norisknogainoficial"
    slug = "norisknogainoficial"
    channel_dir = ROBO_DATA_DIR / "channels" / slug
    channel_dir.mkdir(parents=True, exist_ok=True)

    init_market_db(MARKET_CACHE_DB)
    imported = import_existing_daily_cache(MARKET_CACHE_DB, EXISTING_CACHE_DB)
    print(f"[Cache] {imported} barras diárias importadas do cache existente.")

    try:
        manifest = fetch_channel_videos(channel_url, max_videos=250)
        manifest_path = channel_dir / "channel_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[YouTube] Manifesto salvo: {manifest['total_videos_found']} vídeos totais, {manifest['strategy_videos_count']} vídeos de estratégias.")

        fetch_transcripts_for_candidates(
            manifest["strategy_videos"],
            channel_dir / "transcripts",
            max_transcripts=25,
        )
    except Exception as exc:
        print(f"[YouTube] Erro durante varredura online: {exc}")

    try:
        sync_yfinance_data(MARKET_CACHE_DB)
    except Exception as exc:
        print(f"[yfinance] Erro durante sincronização: {exc}")


if __name__ == "__main__":
    main()
