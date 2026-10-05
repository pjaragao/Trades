"""
YouTube Channel & Video Strategy Crawler.
Fluxo implementado:
1. Recebe URL de um vídeo informado pelo usuário.
2. Extrai metadados do vídeo e identifica o canal do autor.
3. Varre todos os vídeos do canal buscando conteúdos com estratégias de trade.
4. Extrai a transcrição completa do vídeo via youtube-transcript-api.
5. Cataloga o canal e a estratégia na Base de Conhecimento (strategies/knowledge_base/youtube/).
"""

import os
import re
import json
import argparse
import urllib.request
from typing import Dict, Any, List, Optional
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi

STRATEGY_KEYWORDS = [
    "opções", "opcoes", "venda de put", "put", "call", "trava", "bull spread",
    "renda", "cdi", "300%", "backtest", "swing trade", "day trade", "setup",
    "indicador", "atr", "volatilidade", "acerto", "lucro", "estratégia", "estrategia"
]

class YouTubeStrategyCrawler:
    def __init__(self, base_output_dir: str = "strategies/knowledge_base/youtube"):
        self.base_output_dir = base_output_dir
        os.makedirs(self.base_output_dir, exist_ok=True)

    def extract_video_id(self, url: str) -> Optional[str]:
        m = re.search(r"(?:v=|\/live\/|\/shorts\/|youtu\.be\/)([a-zA-Z0-9_-]{11})", url)
        return m.group(1) if m else None

    def fetch_video_transcript(self, video_id: str, languages: List[str] = ["pt", "en"]) -> Optional[str]:
        api = YouTubeTranscriptApi()
        for lang in languages:
            try:
                transcript = api.fetch(video_id, languages=[lang])
                text = " ".join([snippet.text for snippet in transcript.snippets])
                return text
            except Exception:
                continue
        return None

    def get_channel_videos(self, channel_id_or_url: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Lista os vídeos do canal via yt-dlp sem baixar a mídia."""
        if not channel_id_or_url.startswith("http"):
            channel_url = f"https://www.youtube.com/channel/{channel_id_or_url}/videos"
        else:
            channel_url = channel_id_or_url.rstrip("/") + "/videos" if not channel_id_or_url.endswith("/videos") else channel_id_or_url

        ydl_opts = {
            "extract_flat": True,
            "quiet": True,
            "playlist_items": f"1-{limit}"
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(channel_url, download=False)
                return info.get("entries", [])
            except Exception as e:
                print(f"Erro ao listar vídeos do canal ({channel_url}): {e}")
                return []

    def classify_strategy_videos(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filtra vídeos que abordam estratégias operacionais e de trade."""
        candidates = []
        for e in entries:
            title = e.get("title", "")
            title_lower = title.lower()
            matched_keywords = [kw for kw in STRATEGY_KEYWORDS if kw in title_lower]
            if matched_keywords:
                candidates.append({
                    "video_id": e.get("id"),
                    "title": title,
                    "url": f"https://www.youtube.com/watch?v={e.get('id')}",
                    "matched_topics": matched_keywords,
                    "duration": e.get("duration"),
                    "view_count": e.get("view_count")
                })
        return candidates

    def process_video_and_channel(self, video_url: str, max_channel_videos: int = 40) -> Dict[str, Any]:
        """Fluxo completo: inspeciona o vídeo alvo e varre todo o canal correspondente."""
        video_id = self.extract_video_id(video_url)
        if not video_id:
            raise ValueError(f"ID do vídeo não encontrado na URL: {video_url}")

        print(f"\n[1/4] Extraindo metadados do vídeo: {video_id}...")
        ydl_opts = {"quiet": True, "extract_flat": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            v_info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)

        title = v_info.get("title", "Sem Título")
        author = v_info.get("uploader") or v_info.get("channel", "Autor Desconhecido")
        channel_id = v_info.get("channel_id")
        channel_url = v_info.get("channel_url") or (f"https://www.youtube.com/channel/{channel_id}" if channel_id else None)

        print(f" -> Título: {title}")
        print(f" -> Canal/Autor: {author} (ID: {channel_id})")

        # Pasta própria do canal
        slug_author = re.sub(r"[^a-zA-Z0-9_]", "_", author.lower()).strip("_")
        channel_dir = os.path.join(self.base_output_dir, slug_author)
        os.makedirs(channel_dir, exist_ok=True)

        # 2. Transcrição do vídeo informado
        print(f"[2/4] Buscando transcrição do vídeo informado...")
        transcript = self.fetch_video_transcript(video_id)
        transcript_chars = len(transcript) if transcript else 0
        print(f" -> Transcrição capturada: {transcript_chars:,} caracteres.")

        # Salva transcrição se obtida
        if transcript:
            raw_transcript_path = os.path.join(channel_dir, f"transcript_{video_id}.txt")
            with open(raw_transcript_path, "w", encoding="utf-8") as f:
                f.write(transcript)

        # 3. Varredura dos demais vídeos do canal
        print(f"[3/4] Varrendo outros vídeos com potencial de estratégia no canal de '{author}'...")
        all_entries = self.get_channel_videos(channel_id, limit=max_channel_videos) if channel_id else []
        candidates = self.classify_strategy_videos(all_entries)
        print(f" -> Encontrados {len(candidates)} vídeos abordando estratégias no canal!")

        # 4. Atualiza o perfil do canal
        profile_path = os.path.join(channel_dir, "channel_profile.json")
        profile_data = {
            "channel_id": channel_id,
            "channel_name": author,
            "channel_url": channel_url,
            "last_inspected_video": {
                "video_id": video_id,
                "title": title,
                "url": video_url,
                "has_transcript": transcript is not None
            },
            "strategy_candidates_count": len(candidates),
            "strategy_candidates": candidates
        }

        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile_data, f, indent=2, ensure_ascii=False)

        print(f"[4/4] Base de Conhecimento atualizada com sucesso em: {channel_dir}\n")

        return {
            "success": True,
            "channel_name": author,
            "channel_id": channel_id,
            "video_id": video_id,
            "video_title": title,
            "candidates_found": len(candidates),
            "output_dir": channel_dir
        }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube Strategy Crawler")
    parser.add_argument("--video", type=str, required=True, help="URL do vídeo do YouTube")
    parser.add_argument("--limit", type=int, default=35, help="Limite de vídeos do canal a inspecionar")
    args = parser.parse_args()

    crawler = YouTubeStrategyCrawler()
    res = crawler.process_video_and_channel(args.video, max_channel_videos=args.limit)
    print("Resultado:", json.dumps(res, indent=2, ensure_ascii=False))
