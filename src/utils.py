import unicodedata
from typing import Optional

TRADER_ALIASES = {
    "ferri": "Ferri",
    "sanita": "Sanita",
    "felipe corleta": "Felipe Corleta",
    "felipe felipe corleta": "Felipe Corleta",
    "artur horta": "Artur Horta",
    "luis fontes": "Luis Fontes",
    "pedro prado": "Pedro Prado",
    "wanderson assis": "Wanderson Assis",
    "leon suhett": "Leon Suhett",
    "alexandre": "Alexandre",
    "amilton": "Amilton",
    "brondi": "Brondi",
    "calvete": "Calvete",
    "guilherme": "Guilherme",
    "guto": "Guto",
    "saviola": "Saviola",
    "ademar": "Ademar",
    "relatorios": "Relatórios",
    "relatrios": "Relatórios",
    "relatorios trader": "Relatórios",
}

def normalize_trader_name(raw_name: Optional[str]) -> str:
    """
    Padroniza e unifica o nome do analista/trader.
    Resolve:
    - Diferenças de maiúsculas/minúsculas ('FERRI' vs 'Ferri' -> 'Ferri')
    - Nomes duplicados ('Felipe Felipe Corleta' -> 'Felipe Corleta')
    - Variações com/sem acento e aliases comuns
    """
    if not raw_name:
        return "Desconhecido"

    # Remove espaços extras
    raw_str = str(raw_name).strip()
    words = raw_str.split()
    
    # Remove repetições consecutivas de palavras (ex: 'Felipe Felipe Corleta' -> 'Felipe Corleta')
    deduped_words = []
    for w in words:
        if not deduped_words or deduped_words[-1].lower() != w.lower():
            deduped_words.append(w)
            
    clean = " ".join(deduped_words)
    clean_lower = clean.lower()

    # Normalização sem acentos para comparação
    clean_ascii = "".join(
        c for c in unicodedata.normalize('NFD', clean_lower)
        if unicodedata.category(c) != 'Mn'
    )

    if "relat" in clean_lower:
        return "Relatórios"

    if clean_lower in TRADER_ALIASES:
        return TRADER_ALIASES[clean_lower]
        
    if clean_ascii in TRADER_ALIASES:
        return TRADER_ALIASES[clean_ascii]

    return clean.title()


