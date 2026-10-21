"""
Minerador Completo de Canais do YouTube para Fábrica de Robôs.
Categoriza todos os vídeos varridos do canal por família operacional (Bandas de Volatilidade, Keltner,
Gradiente Linear, IFR/Osciladores, Cruzamento/Alinhamento de Médias, Setup 123/Price Action, VWAP/Fluxo,
Range/Golden Hour, Gestão de Risco/MT5) e analisa as transcrições extraídas.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from robo_lab.config import CHANNELS_DIR
from robo_lab.strategies.bots_norisknogain import NORISKNOGAIN_BOTS

VIDEO_FAMILY_RULES = [
    ("CASH_BANDS_VOLATILITY", "Cash Bands / Bandas de True Range", ["cash band", "cashband", "oscilação natural", "natural price", "true range"]),
    ("KELTNER_BOLLINGER", "Canais de Keltner & Bandas de Bollinger", ["keltner", "bollinger", "fechou fora", "round 6"]),
    ("LINEAR_GRADIENT_GRID", "Gradiente Linear & Malha / Preço Médio", ["gradiente", "linear gradient", "linear grid", "preço médio", "preco medio", "grid"]),
    ("VWAP_ORDERFLOW", "VWAP Bands & Saldo de Agressão / Fluxo", ["vwap", "agressão", "agressao", "fluxo", "times and trades", "volume"]),
    ("IFR_OSCILLATORS", "IFR2 Stormer, Estocástico & Z-Score", ["ifr", "rsi", "estocástico", "estocastico", "z-score", "zscore", "96%"]),
    ("MOVING_AVERAGES_TREND", "Alinhamento/Cruzamento de Médias, Tilson & Madrid", ["média", "media", "alinhamento", "cruzamento", "tilson", "madrid", "triple screen", "200"]),
    ("PRICE_ACTION_123_FVG", "Setup 123, 2MV Padrão, HiLo, MACD & FVG", ["123", "2mv", "hilo", "macd", "fvg", "fair value gap", "renko", "virada"]),
    ("OPENING_RANGE_SCALP", "1º Candle do Dia, Golden Hour & Scalping 5m", ["first candle", "primeiro candle", "golden hour", "1h por dia", "5m setup", "scalp", "87%", "74%"]),
    ("RISK_AND_MT5_INFRA", "Gestão de Risco, Alvo/Stop Variável, IA & MT5", ["gestão de risco", "alvo e stop", "metatrader", "mt5", "ai", "ia"]),
]


def classify_video_family(title: str) -> str:
    t = title.lower()
    for code, label, kws in VIDEO_FAMILY_RULES:
        if any(k in t for k in kws):
            return label
    return "Automação Geral & Programação de Robôs"


def build_channel_strategy_catalog(channel_slug: str = "norisknogainoficial") -> Dict[str, Any]:
    channel_dir = CHANNELS_DIR / channel_slug
    manifest_path = channel_dir / "channel_manifest.json"
    transcripts_dir = channel_dir / "transcripts"

    if not manifest_path.exists():
        return {"error": f"Manifesto não encontrado em {manifest_path}"}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    all_videos = manifest.get("all_videos", [])

    # Carrega resumo das transcrições salvas
    transcript_summaries = []
    if transcripts_dir.exists():
        for tf in sorted(transcripts_dir.glob("*.txt")):
            vid = tf.stem
            txt = tf.read_text(encoding="utf-8", errors="ignore")
            v_match = next((v for v in all_videos if v.get("video_id") == vid), {})
            transcript_summaries.append({
                "video_id": vid,
                "title": v_match.get("title", vid),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "chars": len(txt),
                "family": classify_video_family(v_match.get("title", "")),
                "excerpt": txt[:380] + "..." if len(txt) > 380 else txt,
            })

    # Agrupa todos os 250 vídeos por família de estratégia
    by_family: Dict[str, List[Dict[str, Any]]] = {}
    for v in all_videos:
        fam = classify_video_family(v.get("title", ""))
        v["strategy_family"] = fam
        by_family.setdefault(fam, []).append(v)

    family_summary = [
        {"family": fam, "videos_count": len(vids), "sample_titles": [x["title"] for x in vids[:5]]}
        for fam, vids in sorted(by_family.items(), key=lambda item: len(item[1]), reverse=True)
    ]

    catalog = {
        "channel_id": manifest.get("channel_id"),
        "channel_name": manifest.get("channel_name"),
        "channel_url": manifest.get("channel_url"),
        "analyzed_at": datetime.now().isoformat(),
        "total_videos_scanned": len(all_videos),
        "strategy_videos_identified": manifest.get("strategy_videos_count", 0),
        "transcripts_extracted_count": len(transcript_summaries),
        "families_breakdown": family_summary,
        "transcripts_analyzed": transcript_summaries,
        "programmed_bots": [
            {
                "bot_id": b.bot_id,
                "name": b.name,
                "family": b.family,
                "preferred_regimes": b.preferred_regimes,
                "video_ids": b.video_ids,
                "video_titles": b.video_titles,
                "thesis": b.thesis,
                "default_params": b.default_params,
                "param_grid": b.param_grid,
            }
            for b in NORISKNOGAIN_BOTS
        ],
    }

    out_path = channel_dir / "strategy_catalog.json"
    out_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    return catalog
