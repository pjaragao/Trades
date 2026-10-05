"""
Taxas de referência do Banco Central (API SGS), com cache de 12 h no banco.

- CDI anualizado (base 252) : série 4389
- Meta Selic (Copom)        : série 432
Se a API falhar, usa o último valor salvo; sem nada salvo, um padrão marcado como "fixo".
"""
import json
import time
from typing import Any, Dict

import requests

from src.core import db

SERIES = {"cdi": 4389, "selic": 432}
FALLBACK = {"cdi": 11.75, "selic": 11.75}
CACHE_SECONDS = 12 * 3600
URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados/ultimos/1?formato=json"


def _fetch(code: int) -> Dict[str, Any]:
    resp = requests.get(URL.format(code=code), timeout=10)
    resp.raise_for_status()
    row = resp.json()[-1]
    return {"value": float(str(row["valor"]).replace(",", ".")), "date": row["data"]}


def get_rates(force: bool = False) -> Dict[str, Any]:
    """{'cdi': {'value': 13.65, 'date': '01/10/2026', 'source': 'bcb'|'cache'|'fixo'}, 'selic': {...}}"""
    cached = db.kv_get("rates_bcb")
    data = json.loads(cached) if cached else {}
    fresh = data and not force and time.time() - data.get("fetched_at", 0) < CACHE_SECONDS
    if fresh:
        return {k: {**v, "source": "bcb"} for k, v in data["rates"].items()}

    rates: Dict[str, Any] = {}
    for name, code in SERIES.items():
        try:
            rates[name] = {**_fetch(code), "source": "bcb"}
        except (requests.RequestException, ValueError, KeyError, IndexError):
            old = (data.get("rates") or {}).get(name)
            rates[name] = {**old, "source": "cache"} if old else {"value": FALLBACK[name], "date": None, "source": "fixo"}

    if all(r["source"] == "bcb" for r in rates.values()):
        db.kv_set("rates_bcb", json.dumps({"fetched_at": time.time(), "rates": {k: {"value": v["value"], "date": v["date"]} for k, v in rates.items()}}))
    return rates


def cdi_annual_fraction() -> float:
    return get_rates()["cdi"]["value"] / 100.0
