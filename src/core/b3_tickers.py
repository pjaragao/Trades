"""
Utilidades de tickers da B3, sem dependências pesadas (substitui o mapeamento que vivia no TimesFM).

- Classe de ativo normalizada (OPCAO, ACAO, FUTURO, FOREX, INDICE, COMMODITY, CRIPTO, OUTRO)
- Decodificação de opções: ativo-objeto, CALL/PUT, mês e data de vencimento
"""
import re
from datetime import date
from typing import Any, Dict, Optional

from src.core.market_hours import option_expiration

# Prefixo da opção -> papel principal (ativo-objeto)
UNDERLYING_BY_PREFIX = {
    "ABEV": "ABEV3", "ALOS": "ALOS3", "ANIM": "ANIM3", "ASAI": "ASAI3", "AUAU": "AUAU3", "AXIA": "AXIA3",
    "AZUL": "AZUL4", "AZZA": "AZZA3", "B3SA": "B3SA3", "BBAS": "BBAS3", "BBDC": "BBDC4", "BBSE": "BBSE3",
    "BEEF": "BEEF3", "BHIA": "BHIA3", "BOVA": "BOVA11", "BPAC": "BPAC11", "BRAP": "BRAP4", "BRAV": "BRAV3", "BRFS": "BRFS3",
    "BRKM": "BRKM5", "CEAB": "CEAB3", "CMIG": "CMIG4", "CMIN": "CMIN3", "COGN": "COGN3", "CPFE": "CPFE3",
    "CPLE": "CPLE6", "CRFB": "CRFB3", "CSAN": "CSAN3", "CSNA": "CSNA3", "CYRE": "CYRE3", "DIRR": "DIRR3",
    "ECOR": "ECOR3", "EGIE": "EGIE3", "ELET": "ELET3", "EMBJ": "EMBJ3", "EMBR": "EMBR3", "ENEV": "ENEV3",
    "EQTL": "EQTL3", "EZTC": "EZTC3", "GGBR": "GGBR4", "GOAU": "GOAU4", "HAPV": "HAPV3", "HYPE": "HYPE3",
    "IRBR": "IRBR3", "ITSA": "ITSA4", "ITUB": "ITUB4", "JBSS": "JBSS3", "KLBN": "KLBN11", "LREN": "LREN3",
    "LWSA": "LWSA3", "MGLU": "MGLU3", "MOVI": "MOVI3", "MRFG": "MRFG3", "MRVE": "MRVE3", "MULT": "MULT3",
    "NATU": "NATU3", "NEOE": "NEOE3", "NTCO": "NTCO3", "PCAR": "PCAR3", "PETR": "PETR4", "POMO": "POMO4", "PRIO": "PRIO3",
    "RADL": "RADL3", "RAIL": "RAIL3", "RAIZ": "RAIZ4", "RDOR": "RDOR3", "RECV": "RECV3", "RENT": "RENT3",
    "RIAA": "RIAA3", "ROXO": "ROXO34", "SANB": "SANB11", "SAUD": "QUAL3", "SBSP": "SBSP3", "SEER": "SEER3", "SIMH": "SIMH3",
    "SMAL": "SMAL11", "SUZB": "SUZB3", "TAEE": "TAEE11", "TEND": "TEND3", "TIMS": "TIMS3", "TOTS": "TOTS3",
    "TUPY": "TUPY3", "UGPA": "UGPA3", "USIM": "USIM5", "VALE": "VALE3", "VAMO": "VAMO3", "VIVA": "VIVA3",
    "VIVT": "VIVT3", "WEGE": "WEGE3", "YDUQ": "YDUQ3",
}

CALL_MONTHS = "ABCDEFGHIJKL"
PUT_MONTHS = "MNOPQRSTUVWX"

_OPTION_RE = re.compile(r"^([A-Z]{4})([A-X])(\d{1,4})(W(\d))?([A-Z0-9]*)$")
_STOCK_RE = re.compile(r"^[A-Z]{4}\d{1,2}F?$")

ASSET_CLASS_LABELS = {
    "OPCAO": "Opções",
    "ACAO": "Ações/FIIs",
    "FUTURO": "Futuros",
    "FOREX": "Forex",
    "INDICE": "Índices/CFDs",
    "COMMODITY": "Commodities",
    "CRIPTO": "Cripto",
    "OUTRO": "Outros",
}


def clean_ticker(ticker: Any) -> str:
    return str(ticker or "").strip().upper().replace(".SA", "")


def asset_class(tipo_ativo: Any, ticker: Any = "") -> str:
    t = str(tipo_ativo or "").upper()
    if "OPC" in t or "OPÇ" in t:
        return "OPCAO"
    if "FUTUR" in t:
        return "FUTURO"
    if "AÇÕES" in t or "ACOES" in t or "FII" in t or "BDR" in t:
        return "ACAO"
    if "FOREX" in t:
        return "FOREX"
    if "CRIPTO" in t:
        return "CRIPTO"
    if "COMMOD" in t:
        return "COMMODITY"
    if "ÍNDICE" in t or "INDICE" in t or "CFD" in t:
        return "INDICE"

    tk = clean_ticker(ticker)
    if not tk:
        return "OUTRO"
    if tk.endswith("FUT") or tk[:3] in ("WIN", "WDO", "IND", "DOL"):
        return "FUTURO"
    if _STOCK_RE.match(tk):
        return "ACAO"
    if _OPTION_RE.match(tk):
        return "OPCAO"
    return "OUTRO"


def underlying_of(ticker: Any) -> Optional[str]:
    tk = clean_ticker(ticker)
    m = _OPTION_RE.match(tk)
    if m:
        prefix = m.group(1)
        return UNDERLYING_BY_PREFIX.get(prefix, f"{prefix}3")
    if _STOCK_RE.match(tk):
        return tk.rstrip("F") if tk.endswith("F") and len(tk) > 5 else tk
    return None


def decode_option(ticker: Any, reference: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """
    Decodifica um ticker de opção da B3 (ex.: PETRV480, BBASJ216, BPACV430W2).
    O ano do vencimento é o primeiro cujo vencimento cai em ou após `reference` (data do sinal).
    """
    tk = clean_ticker(ticker)
    m = _OPTION_RE.match(tk)
    if not m:
        return None
    prefix, letter, _code, _w, week = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    if letter in CALL_MONTHS:
        kind, month = "CALL", CALL_MONTHS.index(letter) + 1
    else:
        kind, month = "PUT", PUT_MONTHS.index(letter) + 1

    ref = reference or date.today()
    week_n = int(week) if week else None
    year = ref.year
    exp = option_expiration(year, month, week_n)
    if exp < ref:
        exp = option_expiration(year + 1, month, week_n)

    return {
        "underlying": UNDERLYING_BY_PREFIX.get(prefix, f"{prefix}3"),
        "kind": kind,
        "month": month,
        "weekly": week_n is not None,
        "expiration": exp.isoformat(),
    }


def default_lot(asset: str) -> int:
    return 1 if asset in ("FUTURO", "FOREX", "INDICE", "COMMODITY", "CRIPTO") else 100
