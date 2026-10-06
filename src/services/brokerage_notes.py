"""
Importador de notas de corretagem no padrão SINACOR/B3 (XP, Genial e outras corretoras que usam o mesmo layout).

Fluxo:
1. `read_pdf()` extrai o texto de cada página (aceita PDF com senha — XP usa os 3 primeiros dígitos do CPF).
2. `parse_pages()` agrupa as páginas por nota e extrai negócios + resumo financeiro (custos, IRRF, líquido).
3. `build_preview()` resolve os tickers e concilia com as execuções já registradas — a nota é a verdade:
   quantidade, preço, custos (rateados pelo valor) e data do pregão passam a ser os da nota; o que falta é criado
   e o que foi registrado no pregão mas não aparece na nota é listado para manter ou excluir.
4. `apply_preview()` grava tudo numa transação por nota e guarda o estado anterior (desfazer restaura).
5. `fee_calibration()` calcula as taxas B3 efetivas das suas notas para alimentar as estimativas.

Notas de BM&F (futuros) têm outro layout e não são lidas aqui.
"""
import hashlib
import io
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

from src.core import b3_tickers, db
from src.core.config import get_prefs, now_iso, update_prefs
from src.core.market_hours import BRT, to_brt
from src.services import auto_link, journal

MONEY = r"-?\d{1,3}(?:\.\d{3})*,\d{2,}"
_MONEY_RE = re.compile(MONEY)

MARKET_TYPES = [
    "OPCAO DE COMPRA", "OPCAO DE VENDA", "EXERC OPC COMPRA", "EXERC OPC VENDA", "EXERCICIO OPC COMPRA",
    "EXERCICIO OPC VENDA", "VISTA", "FRACIONARIO", "TERMO", "LEILAO", "OPCOES",
]
# C/V pode vir colado ao mercado na extração do PDF (Genial: "B3 RV LISTADOC OPCAO DE COMPRA ...")
LINE_RE = re.compile(r"^(?:\S{1,3}\s+)?(1-BOVESPA|B3\s+RV\s+LISTADO|BOVESPA|B3\s+RV)\s*(C|V)\s+(.+)$")
OBS_RE = re.compile(r"^(?:[#DFBACHXYLPIT]|D#|#D|D8|8)$")

FEE_LABELS = {
    "liquidacao": r"taxa de liquidacao",
    "registro": r"taxa de registro",
    "termo_opcoes": r"taxa de termo/opcoes",
    "ana": r"taxa a\.?n\.?a\.?",
    "emolumentos": r"emolumentos",
    "corretagem": r"(?:taxa operacional|corretagem)",
    "execucao": r"execucao",
    "custodia": r"taxa de custodia",
    "impostos": r"impostos",
    "outros": r"outros",
}
B3_FEE_KEYS = ("liquidacao", "registro", "termo_opcoes", "ana", "emolumentos")
BROKER_FEE_KEYS = ("corretagem", "execucao", "custodia", "impostos", "outros")

# Nome de pregão (SINACOR) -> prefixo do ticker. Classe: ON=3, PN=4, PNA=5, PNB=6, UNT/CI=11.
NAME_TO_PREFIX = {
    "PETROBRAS": "PETR", "VALE": "VALE", "ITAUUNIBANCO": "ITUB", "ITAU UNIBANCO": "ITUB", "BRADESCO": "BBDC",
    "BRASIL": "BBAS", "BANCO DO BRASIL": "BBAS", "AMBEV S/A": "ABEV", "AMBEV": "ABEV", "B3": "B3SA", "MAGAZ LUIZA": "MGLU",
    "WEG": "WEGE", "SUZANO S.A.": "SUZB", "SUZANO": "SUZB", "GERDAU": "GGBR", "GERDAU MET": "GOAU", "USIMINAS": "USIM",
    "ELETROBRAS": "ELET", "AXIA": "AXIA", "AXIA ENERGIA": "AXIA", "NATURA": "NATU", "NATURA &CO": "NATU", "CSNMINERACAO": "CMIN",
    "SID NACIONAL": "CSNA", "JBS": "JBSS", "MARFRIG": "MRFG", "MINERVA": "BEEF", "BRF SA": "BRFS", "LOCALIZA": "RENT",
    "RAIADROGASIL": "RADL", "HAPVIDA": "HAPV", "REDE D OR": "RDOR", "ASSAI": "ASAI", "CARREFOUR BR": "CRFB",
    "LOJAS RENNER": "LREN", "AZZAS 2154": "AZZA", "C&A MODAS": "CEAB", "VIVARA S.A.": "VIVA", "VIVARA": "VIVA",
    "COSAN": "CSAN", "RUMO S.A.": "RAIL", "RUMO": "RAIL", "PRIO": "PRIO", "PETRORECSA": "RECV", "PETRORECONCAVO": "RECV",
    "ENEVA": "ENEV", "EQUATORIAL": "EQTL", "CEMIG": "CMIG", "COPEL": "CPLE", "SABESP": "SBSP", "TIM": "TIMS",
    "TELEF BRASIL": "VIVT", "TOTVS": "TOTS", "YDUQS PART": "YDUQ", "COGNA": "COGN", "ANIMA": "ANIM", "CYRELA REALT": "CYRE",
    "MRV": "MRVE", "DIRECIONAL": "DIRR", "TENDA": "TEND", "EZTEC": "EZTC", "IRBBRASIL RE": "IRBR", "IRB BRASIL RE": "IRBR",
    "BBSEGURIDADE": "BBSE", "BTGP BANCO": "BPAC", "SANTANDER BR": "SANB", "ITAUSA": "ITSA", "EMBRAER": "EMBJ",
    "AZUL": "AZUL", "MOVIDA": "MOVI", "VAMOS": "VAMO", "SIMPAR": "SIMH", "QUALICORP": "QUAL", "ECORODOVIAS": "ECOR",
    "SER EDUCA": "SEER", "GUARARAPES": "GUAR", "ULTRAPAR": "UGPA", "KLABIN S/A": "KLBN", "BRASKEM": "BRKM",
    "CPFL ENERGIA": "CPFE", "ENGIE BRASIL": "EGIE", "TAESA": "TAEE", "MULTIPLAN": "MULT", "ALLOS": "ALOS",
    "LWSA": "LWSA", "NEOENERGIA": "NEOE", "TUPY": "TUPY", "BRAVA": "BRAV", "GPA": "PCAR", "CVC BRASIL": "CVCB",
    "AUREN": "AURE", "SAO MARTINHO": "SMTO", "3TENTOS": "TTEN", "SMARTFIT": "SMFT", "GRUPO MATEUS": "GMAT",
    "ISHARE BOVA": "BOVA", "ISHARES BOVA": "BOVA", "ISHARE SMAL": "SMAL", "ISHARES SMAL": "SMAL",
}
CLASS_SUFFIX = {"ON": "3", "PN": "4", "PNA": "5", "PNB": "6", "PNC": "7", "PND": "8", "UNT": "11", "CI": "11"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _money(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _qty(s: str) -> Optional[float]:
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


# ---------------------------------------------------------------- leitura do PDF
class NotePasswordError(ValueError):
    pass


def read_pdf(data: bytes, password: Optional[str] = None) -> List[str]:
    import logging

    import pdfplumber

    logging.getLogger("pdfminer").setLevel(logging.ERROR)  # avisos de fonte das notas (FontBBox) são inofensivos

    try:
        with pdfplumber.open(io.BytesIO(data), password=password or "") as pdf:
            return [(p.extract_text(x_tolerance=1.5, y_tolerance=3) or "") for p in pdf.pages]
    except Exception as exc:  # senha / PDF corrompido / não é PDF
        if _is_password_error(exc):
            msg = "PDF protegido: informe a senha correta." if password else "PDF protegido: informe a senha (na XP são os 3 primeiros dígitos do CPF)."
            raise NotePasswordError(msg) from exc
        raise ValueError(f"Não foi possível ler o PDF: {exc.__class__.__name__}") from exc


def _is_password_error(exc: BaseException) -> bool:
    """O pdfplumber embrulha o erro de senha do pdfminer (PdfminerException(PDFPasswordIncorrect))."""
    from pdfminer.pdfdocument import PDFPasswordIncorrect

    seen, stack = set(), [exc]
    while stack:
        e = stack.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        if isinstance(e, PDFPasswordIncorrect) or "password" in e.__class__.__name__.lower() or "password" in str(e).lower():
            return True
        stack.extend([e.__cause__, e.__context__, *[a for a in getattr(e, "args", ()) if isinstance(a, BaseException)]])
    return False


# ---------------------------------------------------------------- parser
def detect_broker(text: str) -> str:
    t = _norm(text).upper()
    if "XP INVESTIMENTOS" in t:
        return "XP"
    if "GENIAL" in t:
        return "Genial"
    if "CLEAR CORRETORA" in t or "CLEAR CTVM" in t:
        return "Clear"
    if "RICO INVESTIMENTOS" in t or "RICO CTVM" in t:
        return "Rico"
    if "BTG PACTUAL" in t:
        return "BTG"
    return "SINACOR"


def _header(text: str) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """(número da nota, data do pregão dd/mm/aaaa, folha)"""
    t = _norm(text)
    m = re.search(r"Nr\.?\s*nota\s+Folha\s+Data\s+preg\w*\s*\n\s*(\d[\d.]*)\s+(\d+)\s+(\d{2}/\d{2}/\d{4})", t, re.I)
    if m:
        return m.group(1).replace(".", ""), m.group(3), int(m.group(2))
    m = re.search(r"(\d{4,12})\s+(\d{1,3})\s+(\d{2}/\d{2}/\d{4})", t)
    if m:
        return m.group(1), m.group(3), int(m.group(2))
    m = re.search(r"Data\s+preg\w*\D{0,40}(\d{2}/\d{2}/\d{4})", t, re.I)
    return None, (m.group(1) if m else None), None


def parse_trade_line(line: str) -> Optional[Dict[str, Any]]:
    raw = line.strip()
    norm = _norm(raw).upper()
    m = LINE_RE.match(norm)
    if not m:
        return None
    side = "BUY" if m.group(2) == "C" else "SELL"
    rest = m.group(3).split()
    if len(rest) < 5 or rest[-1] not in ("D", "C"):
        return None
    value, price, qty = _money(rest[-2]), _money(rest[-3]), _qty(rest[-4])
    if value is None or price is None or qty is None or qty <= 0:
        return None
    body = rest[:-4]
    market = None
    joined = " ".join(body)
    for mt in sorted(MARKET_TYPES, key=len, reverse=True):
        if joined.startswith(mt + " ") or joined == mt:
            market = mt
            body = joined[len(mt):].split()
            break
    if market is None:
        return None
    prazo = None
    if body and re.match(r"^\d{2}/\d{2,4}$", body[0]):
        prazo = body.pop(0)
    obs = []
    while body and OBS_RE.match(body[-1]):
        obs.insert(0, body.pop())
    spec = " ".join(body)
    return {
        "side": side, "market": market, "prazo": prazo, "spec": spec, "obs": "".join(obs),
        "quantity": qty, "price": price, "value": value, "dc": rest[-1], "raw": raw,
    }


def resolve_ticker(spec: str, market: str) -> Tuple[Optional[str], str]:
    """(ticker, como foi resolvido: 'opcao' | 'nome' | 'ticker' | '')"""
    tokens = spec.upper().split()
    if not tokens:
        return None, ""
    first = tokens[0].replace(".", "")
    is_option = b3_tickers.decode_option(first) is not None
    if is_option and ("OPC" in market or "EXERC" in market):
        return first, "opcao"
    if re.match(r"^[A-Z]{4}\d{1,2}F?$", first):
        return (first[:-1] if len(first) > 5 and first.endswith("F") else first), "ticker"
    if is_option:
        return first, "opcao"
    cls_idx = next((i for i, t in enumerate(tokens) if t in CLASS_SUFFIX), None)
    if cls_idx is None or cls_idx == 0:
        return None, ""
    name = " ".join(tokens[:cls_idx])
    prefix = NAME_TO_PREFIX.get(name) or NAME_TO_PREFIX.get(name.replace(" S.A.", "").replace(" S/A", "").strip())
    if not prefix:
        return None, ""
    return f"{prefix}{CLASS_SUFFIX[tokens[cls_idx]]}", "nome"


def _fees(text: str) -> Dict[str, Any]:
    t = _norm(text).lower()
    fees: Dict[str, float] = {}
    start = t.find("resumo financeiro")
    scope = t[start:] if start >= 0 else t
    for key, label in FEE_LABELS.items():
        m = re.search(label + r"[^\d\n-]{0,30}(" + MONEY + r")", scope)
        if m:
            fees[key] = abs(_money(m.group(1)) or 0.0)
    irrf = None
    m = re.search(r"i\.?r\.?r\.?f\.?\s*s/\s*operac\w*,?\s*base\s*r\$\s*(" + MONEY + r")?\s*(" + MONEY + r")", scope)
    if m:
        irrf = _money(m.group(2))
    irrf_day = None  # "IRRF Day Trade: Base R$ x Projeção R$ y" (1% do ganho do day trade no dia)
    m = re.search(r"i\.?r\.?r\.?f\.?\s*day\s*trade[^\n]*?proje\w*\s*r?\$?\s*(" + MONEY + r")", t)
    if m:
        irrf_day = _money(m.group(1))
    out: Dict[str, Any] = {"items": fees, "irrf": irrf, "irrf_day": irrf_day}
    m = re.search(r"valor liquido das operacoes\s*(" + MONEY + r")\s*([dc])?", scope)
    if m:
        v = _money(m.group(1))
        out["net_ops"] = -v if (m.group(2) == "d") else v
    # a extração às vezes desloca o espaço da data ("liquido para0 6/10/2026")
    m = re.search(r"liquido para\s*(\d\s?\d/\d{2}/\d{4})\s*(" + MONEY + r")\s*([dc])?", scope)
    if m:
        v = _money(m.group(2))
        out["settlement_date"] = m.group(1).replace(" ", "")
        out["net_value"] = -v if m.group(3) == "d" else v
    m = re.search(r"valor das operacoes\s*(" + MONEY + r")", scope)
    if m:
        out["gross"] = _money(m.group(1))
    return out


def parse_pages(pages: List[str]) -> List[Dict[str, Any]]:
    """Agrupa páginas por nota e devolve as notas com negócios e custos."""
    notes: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for idx, text in enumerate(pages):
        number, day, _folha = _header(text)
        if current is None or (number and number != current["number"]) or (day and day != current["trade_date_br"] and number is None):
            current = {"number": number or f"sem-numero-{idx + 1}", "trade_date_br": day, "broker": detect_broker(text),
                       "trades": [], "pages": [], "fees": {}, "warnings": []}
            notes.append(current)
        current["pages"].append(idx + 1)
        for line in text.splitlines():
            tr = parse_trade_line(line)
            if tr:
                current["trades"].append(tr)
        f = _fees(text)
        if f.get("net_value") is not None or not current["fees"]:
            current["fees"] = f
    for n in notes:
        _finish(n)
    return [n for n in notes if n["trades"]]


def _finish(n: Dict[str, Any]) -> None:
    try:
        n["trade_date"] = datetime.strptime(n["trade_date_br"], "%d/%m/%Y").date().isoformat() if n["trade_date_br"] else None
    except ValueError:
        n["trade_date"] = None
    if not n["trade_date"]:
        n["warnings"].append("Data do pregão não encontrada.")
    items = n["fees"].get("items", {})
    n["b3_fees"] = round(sum(items.get(k, 0.0) for k in B3_FEE_KEYS), 2)
    n["broker_fees"] = round(sum(items.get(k, 0.0) for k in BROKER_FEE_KEYS), 2)
    n["total_costs"] = round(n["b3_fees"] + n["broker_fees"], 2)
    n["irrf"] = n["fees"].get("irrf")
    n["gross_value"] = round(sum(t["value"] for t in n["trades"]), 2)
    ops = sum(t["value"] if t["dc"] == "C" else -t["value"] for t in n["trades"])
    n["ops_net"] = round(ops, 2)
    if n["fees"].get("net_ops") is not None and abs(n["fees"]["net_ops"] - ops) > 0.05:
        n["warnings"].append(f"Soma dos negócios ({ops:,.2f}) difere do valor líquido da nota ({n['fees']['net_ops']:,.2f}) — "
                             "alguma linha pode não ter sido lida.")
    if not items:
        n["warnings"].append("Resumo financeiro (custos) não encontrado.")


# ---------------------------------------------------------------- prévia e conciliação
EPS = 1e-6
NEAR_DAYS = 7          # execução registrada em outra data (até 7 dias) sem nota própria: a data é corrigida
MAX_SUBSET = 12        # combinações de execuções do mesmo dia testadas para bater a quantidade da nota


def _group_trades(note: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    total_value = sum(t["value"] for t in note["trades"]) or 1.0
    for t in note["trades"]:
        ticker, how = resolve_ticker(t["spec"], t["market"])
        key = (ticker or f"?{t['spec']}", t["side"])
        g = groups.setdefault(key, {"ticker": ticker, "resolved_by": how, "spec": t["spec"], "market": t["market"],
                                    "side": t["side"], "quantity": 0.0, "value": 0.0, "lines": [], "day_trade": False})
        g["quantity"] += t["quantity"]
        g["value"] += t["value"]
        g["lines"].append({"quantity": t["quantity"], "price": t["price"]})
        g["day_trade"] = g["day_trade"] or "D" in t["obs"]
    out = []
    for g in groups.values():
        g["price"] = round(g["value"] / g["quantity"], 6) if g["quantity"] else 0.0
        g["fees"] = round(note["total_costs"] * g["value"] / total_value, 2)
        g["value"] = round(g["value"], 2)
        g["asset_class"] = b3_tickers.asset_class(None, g["ticker"]) if g["ticker"] else ("OPCAO" if "OPC" in g["market"] else "ACAO")
        out.append(g)
    # ajusta arredondamento do rateio para fechar com o total da nota
    diff = round(note["total_costs"] - sum(g["fees"] for g in out), 2)
    if out and diff:
        max(out, key=lambda g: g["value"])["fees"] = round(max(out, key=lambda g: g["value"])["fees"] + diff, 2)
    return out


def _day(row: Dict[str, Any]) -> str:
    return (to_brt(row["executed_at"]) or datetime.min.replace(tzinfo=BRT)).date().isoformat()


def _exact_subset(rows: List[Dict[str, Any]], qty: float) -> Optional[List[Dict[str, Any]]]:
    """Execuções do mesmo dia cuja soma bate a quantidade da nota (todas, ou a menor combinação que bate)."""
    if abs(sum(r["quantity"] for r in rows) - qty) < EPS:
        return rows
    if len(rows) > MAX_SUBSET:
        return None
    for size in range(1, len(rows)):
        for combo in combinations(rows, size):
            if abs(sum(r["quantity"] for r in combo) - qty) < EPS:
                return list(combo)
    return None


def _fmt_q(q: float) -> str:
    return f"{q:,.0f}".replace(",", ".") if float(q).is_integer() else f"{q:,.2f}"


def _fmt_p(p: float) -> str:
    return f"{p:,.4f}".rstrip("0").rstrip(",.").replace(",", "X").replace(".", ",").replace("X", ".") if p else "0"


def _fmt_d(iso: str) -> str:
    return f"{iso[8:10]}/{iso[5:7]}"


def _reconcile(c, note: Dict[str, Any], g: Dict[str, Any], claimed: set, note_dates: set) -> None:
    """
    Decide o que fazer com um ativo/lado da nota (a nota é a verdade):
      update  : execuções registradas batem a quantidade -> preço, custos (e data) passam a ser os da nota
      replace : quantidade não bate -> as execuções do dia viram uma só, com quantidade/preço/custos da nota
      create  : não há registro -> cria a execução
      skip    : sem data/ticker (ou escolha do usuário)
    """
    g.update(matches=[], action="create", match_note="Não há execução registrada — será criada.", registered=None)
    if not note.get("trade_date"):
        g.update(action="skip", match_note="Nota sem data do pregão.")
        return
    if not g["ticker"]:
        g.update(action="skip", match_note="Informe o ticker para importar.")
        return
    D = note["trade_date"]
    rows = [dict(r) for r in c.execute(
        "SELECT * FROM executions WHERE account = 'real' AND ticker = ? AND side = ? AND note_id IS NULL ORDER BY executed_at, id",
        (g["ticker"], g["side"]))]
    rows = [r for r in rows if r["id"] not in claimed]
    same = [r for r in rows if _day(r) == D]
    date_fix = None
    if same:
        subset = _exact_subset(same, g["quantity"])
        matches, action = (subset, "update") if subset else (same, "replace")
    else:
        near = [r for r in rows if _day(r) not in note_dates and abs(abs((datetime.fromisoformat(_day(r)) - datetime.fromisoformat(D)).days)) <= NEAR_DAYS
                and abs(r["quantity"] - g["quantity"]) < EPS]
        if not near:
            return
        near.sort(key=lambda r: abs((datetime.fromisoformat(_day(r)) - datetime.fromisoformat(D)).days))
        matches, action, date_fix = [near[0]], "update", _day(near[0])
    claimed.update(r["id"] for r in matches)
    q = sum(r["quantity"] for r in matches)
    avg = sum(r["quantity"] * r["price"] for r in matches) / q if q else 0.0
    g["matches"] = [{k: r[k] for k in ("id", "quantity", "price", "fees", "fees_source", "executed_at", "signal_id")} for r in matches]
    g["registered"] = {"quantity": q, "price": round(avg, 6), "fees": round(sum(r["fees"] for r in matches), 2), "date": date_fix or D}
    g["action"] = action
    changes = []
    if action == "replace":
        changes.append(f"quantidade {_fmt_q(q)} → {_fmt_q(g['quantity'])}" + (f" ({len(matches)} execuções viram 1)" if len(matches) > 1 else ""))
    if abs(avg - g["price"]) > 0.00005:
        changes.append(f"preço {_fmt_p(avg)} → {_fmt_p(g['price'])}")
    if date_fix:
        changes.append(f"data {_fmt_d(date_fix)} → {_fmt_d(D)}")
    changes.append("custos reais")
    g["match_note"] = ("Ajusta para a nota: " if action == "replace" else "Atualiza: ") + "; ".join(changes) + "."


def build_preview(files: List[Tuple[str, bytes]], password: Optional[str] = None) -> Dict[str, Any]:
    parsed, errors = [], []
    for name, data in files:
        try:
            pages = read_pdf(data, password)
        except ValueError as exc:
            errors.append({"file": name, "error": str(exc)})
            continue
        notes = parse_pages(pages)
        if not notes:
            errors.append({"file": name, "error": "Nenhum negócio de Bovespa reconhecido (é uma nota SINACOR de ações/opções?)."})
            continue
        file_hash = hashlib.sha256(data).hexdigest()
        parsed += [(name, file_hash, n) for n in notes]
    parsed.sort(key=lambda x: (x[2]["trade_date"] or "", x[2]["number"]))

    notes_out = []
    claimed: set = set()
    with db.connection() as c:
        imported = {(r["broker"], r["number"], r["trade_date"]) for r in c.execute("SELECT broker, number, trade_date FROM notes")}
        note_dates = {r[0] for r in c.execute("SELECT DISTINCT trade_date FROM notes")} | {n["trade_date"] for _, _, n in parsed if n["trade_date"]}
        seen_in_batch = set()
        for name, file_hash, n in parsed:
            key = (n["broker"], n["number"], n["trade_date"] or "")
            exists = key in imported or key in seen_in_batch
            seen_in_batch.add(key)
            groups = _group_trades(n)
            for g in groups:
                if exists:
                    g.update(matches=[], action="skip", match_note="Nota já importada.", registered=None)
                else:
                    _reconcile(c, n, g, claimed, note_dates)
            notes_out.append({
                "file": name, "file_hash": file_hash, "broker": n["broker"], "number": n["number"],
                "trade_date": n["trade_date"], "settlement_date": n["fees"].get("settlement_date"),
                "fees": n["fees"].get("items", {}), "irrf": n["irrf"], "irrf_day": n["fees"].get("irrf_day"),
                "b3_fees": n["b3_fees"], "broker_fees": n["broker_fees"],
                "total_costs": n["total_costs"], "gross_value": n["gross_value"], "net_value": n["fees"].get("net_value"),
                "warnings": n["warnings"], "already_imported": exists, "groups": groups, "extras": [],
                "trades": [{k: t[k] for k in ("side", "market", "spec", "obs", "quantity", "price", "value", "dc")} for t in n["trades"]],
            })
        # execuções registradas nos pregões das notas que não aparecem em nenhuma delas
        first_by_date: Dict[str, Dict[str, Any]] = {}
        for n in notes_out:
            if not n["already_imported"] and n["trade_date"]:
                first_by_date.setdefault(n["trade_date"], n)
        for day, n in first_by_date.items():
            for r in c.execute("SELECT * FROM executions WHERE account = 'real' AND note_id IS NULL ORDER BY executed_at, id"):
                r = dict(r)
                if r["id"] in claimed or _day(r) != day:
                    continue
                n["extras"].append({"id": r["id"], "ticker": r["ticker"], "side": r["side"], "quantity": r["quantity"],
                                    "price": r["price"], "executed_at": r["executed_at"], "signal_id": r["signal_id"], "action": "keep"})
    return {"notes": notes_out, "errors": errors}


# ---------------------------------------------------------------- gravação
_EXEC_COLS = ("id", "signal_id", "ticker", "side", "quantity", "price", "fees", "executed_at", "asset_class", "note", "created_at",
              "account", "source", "order_id", "note_id", "fees_source")


def _backup(c, ids: List[int]) -> List[Dict[str, Any]]:
    if not ids:
        return []
    return [{k: r[k] for k in _EXEC_COLS} for r in c.execute(f"SELECT * FROM executions WHERE id IN ({','.join('?' * len(ids))})", ids)]


def _with_date(executed_at: str, day: str) -> str:
    """Mesma hora, outro dia (pregão da nota)."""
    dt = to_brt(executed_at) or datetime.fromisoformat(f"{day}T10:00:00-03:00")
    y, m, d = map(int, day.split("-"))
    return dt.replace(year=y, month=m, day=d).isoformat(timespec="seconds")


def _line_prices(rows: List[Dict[str, Any]], lines: List[Dict[str, Any]]) -> Optional[List[float]]:
    """Se cada execução tem um negócio da nota com a mesma quantidade, usa o preço de cada negócio."""
    pool = list(lines or [])
    out = []
    for r in rows:
        hit = next((ln for ln in pool if abs(ln["quantity"] - r["quantity"]) < EPS), None)
        if hit is None:
            return None
        pool.remove(hit)
        out.append(float(hit["price"]))
    return out


def _apply_group(c, note_id: int, day: str, g: Dict[str, Any], undo: Dict[str, Any]) -> str:
    ids = [m["id"] for m in g.get("matches") or []]
    rows = [dict(r) for r in c.execute(f"SELECT * FROM executions WHERE id IN ({','.join('?' * len(ids))}) ORDER BY executed_at, id", ids)] if ids else []
    if len(rows) != len(ids):
        raise ValueError("as execuções mudaram desde a leitura da nota — leia a nota de novo")
    undo["updated"] += _backup(c, ids)
    if g["action"] == "replace" or (g["action"] == "update" and len(rows) == 1):
        keep, extra = rows[0], rows[1:]
        c.execute("UPDATE executions SET quantity = ?, price = ?, fees = ?, executed_at = ?, note_id = ?, fees_source = 'note' WHERE id = ?",
                  (float(g["quantity"]), round(float(g["price"]), 6), round(float(g["fees"]), 2), _with_date(keep["executed_at"], day),
                   note_id, keep["id"]))
        for r in extra:  # várias execuções do dia viram uma só, com os números da nota
            undo["fills"] += [[f["id"], r["id"]] for f in c.execute("SELECT id FROM order_fills WHERE execution_id = ?", (r["id"],))]
            c.execute("UPDATE order_fills SET execution_id = ? WHERE execution_id = ?", (keep["id"], r["id"]))
            c.execute("DELETE FROM executions WHERE id = ?", (r["id"],))
        return "replaced" if g["action"] == "replace" else "updated"
    # update com várias execuções: mesmo total — cada uma recebe o preço do seu negócio (ou o médio) e custos rateados
    prices = _line_prices(rows, g.get("lines")) or [float(g["price"])] * len(rows)
    total = sum(r["quantity"] * p for r, p in zip(rows, prices)) or 1.0
    remaining = round(float(g["fees"]), 2)
    for i, (r, p) in enumerate(zip(rows, prices)):
        share = remaining if i == len(rows) - 1 else round(float(g["fees"]) * r["quantity"] * p / total, 2)
        remaining = round(remaining - share, 2)
        c.execute("UPDATE executions SET price = ?, fees = ?, executed_at = ?, note_id = ?, fees_source = 'note' WHERE id = ?",
                  (round(p, 6), share, _with_date(r["executed_at"], day), note_id, r["id"]))
    return "updated"


def _delete_extra(c, exec_id: int, undo: Dict[str, Any]) -> bool:
    rows = _backup(c, [exec_id])
    if not rows:
        return False
    undo["deleted"] += rows
    undo["fills"] += [[f["id"], exec_id] for f in c.execute("SELECT id FROM order_fills WHERE execution_id = ?", (exec_id,))]
    c.execute("UPDATE order_fills SET execution_id = NULL WHERE execution_id = ?", (exec_id,))
    c.execute("DELETE FROM executions WHERE id = ?", (exec_id,))
    sid = rows[0]["signal_id"]
    if sid and not c.execute("SELECT 1 FROM executions WHERE signal_id = ? AND account = 'real'", (sid,)).fetchone():
        c.execute("DELETE FROM decisions WHERE signal_id = ? AND status = 'executed'", (sid,))
    return True


def apply_preview(payload: Dict[str, Any], update_estimates: bool = True) -> Dict[str, Any]:
    stats = {"notes": 0, "updated": 0, "replaced": 0, "created": 0, "deleted": 0, "skipped": 0, "linked": 0, "errors": []}
    for n in sorted(payload.get("notes", []), key=lambda n: (n.get("trade_date") or "", n.get("number") or "")):
        if n.get("already_imported") or not n.get("trade_date"):
            stats["skipped"] += len(n.get("groups", []))
            continue
        day = n["trade_date"]
        try:
            with db.transaction() as c:
                if c.execute("SELECT 1 FROM notes WHERE broker = ? AND number = ? AND trade_date = ?", (n["broker"], n["number"], day)).fetchone():
                    stats["skipped"] += len(n.get("groups", []))
                    continue
                cur = c.execute(
                    "INSERT INTO notes(broker, number, trade_date, settlement_date, file_name, file_hash, gross_value, net_value, total_costs, "
                    "brokerage, b3_fees, taxes, irrf, irrf_day, fees_json, trades_json, imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (n["broker"], n["number"], day, n.get("settlement_date"), n.get("file"), n.get("file_hash"),
                     n.get("gross_value"), n.get("net_value"), n.get("total_costs"), (n.get("fees") or {}).get("corretagem", 0.0),
                     n.get("b3_fees"), (n.get("fees") or {}).get("impostos", 0.0), n.get("irrf"), n.get("irrf_day"),
                     json.dumps(n.get("fees") or {}), json.dumps(n.get("groups") or [], ensure_ascii=False), now_iso()),
                )
                note_id = cur.lastrowid
                undo: Dict[str, Any] = {"updated": [], "deleted": [], "fills": []}
                counts = {"updated": 0, "replaced": 0, "created": 0, "deleted": 0, "skipped": 0, "linked": 0}
                # compras antes das vendas (day trade na mesma nota)
                for g in sorted(n.get("groups", []), key=lambda g: 0 if g.get("side") == "BUY" else 1):
                    action = g.get("action")
                    ticker = b3_tickers.clean_ticker(g.get("ticker"))
                    if action in ("update", "replace") and g.get("matches"):
                        counts[_apply_group(c, note_id, day, g, undo)] += 1
                    elif action in ("create", "update", "replace") and ticker:
                        created = journal.add_execution(
                            {"ticker": ticker, "side": g["side"], "quantity": g["quantity"], "price": g["price"], "fees": g["fees"],
                             "executed_at": f"{day}T10:00:00-03:00", "asset_class": b3_tickers.asset_class(None, ticker),
                             "note": f"Importado da nota {n['broker']} nº {n['number']}"},
                            allow_short=True, account="real", source="note", note_id=note_id, fees_source="note", conn=c,
                        )
                        if auto_link.link_execution(c, created["id"], until_end_of_day=True):
                            counts["linked"] += 1
                        counts["created"] += 1
                    else:
                        counts["skipped"] += 1
                for x in n.get("extras") or []:
                    if x.get("action") == "delete" and _delete_extra(c, int(x["id"]), undo):
                        counts["deleted"] += 1
                c.execute("UPDATE notes SET undo_json = ? WHERE id = ?", (json.dumps(undo, ensure_ascii=False), note_id))
        except ValueError as exc:
            stats["errors"].append(f"Nota {n.get('number')} ({_fmt_d(day)}): {exc} — nada desta nota foi gravado.")
            continue
        for k, v in counts.items():
            stats[k] += v
        stats["notes"] += 1
    if update_estimates and stats["notes"]:
        stats["calibration"] = fee_calibration(apply=True)
    return stats


def list_notes(limit: int = 200) -> List[Dict[str, Any]]:
    with db.connection() as c:
        rows = [dict(r) for r in c.execute("SELECT id, broker, number, trade_date, gross_value, total_costs, b3_fees, brokerage, irrf, irrf_day, "
                                           "net_value, imported_at FROM notes ORDER BY trade_date DESC, id DESC LIMIT ?", (limit,))]
        for r in rows:
            r["executions"] = c.execute("SELECT COUNT(*) FROM executions WHERE note_id = ?", (r["id"],)).fetchone()[0]
    return rows


def delete_note(note_id: int) -> Dict[str, int]:
    """Desfaz a importação: apaga o que a nota criou e devolve as execuções ajustadas/excluídas ao estado anterior."""
    with db.transaction() as c:
        row = c.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        if not row:
            raise KeyError(note_id)
        undo = json.loads(row["undo_json"] or "null")
        created = c.execute("DELETE FROM executions WHERE note_id = ? AND source = 'note'", (note_id,)).rowcount
        restored = 0
        if undo:
            for r in undo.get("updated", []) + undo.get("deleted", []):
                exists = c.execute("SELECT 1 FROM executions WHERE id = ?", (r["id"],)).fetchone()
                if exists:
                    c.execute("UPDATE executions SET quantity = ?, price = ?, fees = ?, executed_at = ?, note_id = ?, fees_source = ? WHERE id = ?",
                              (r["quantity"], r["price"], r["fees"], r["executed_at"], r["note_id"], r["fees_source"], r["id"]))
                else:
                    c.execute(f"INSERT INTO executions({','.join(_EXEC_COLS)}) VALUES({','.join('?' * len(_EXEC_COLS))})",
                              [r[k] for k in _EXEC_COLS])
                restored += 1
            for fill_id, exec_id in undo.get("fills", []):
                c.execute("UPDATE order_fills SET execution_id = ? WHERE id = ?", (exec_id, fill_id))
        # notas antigas (sem histórico para desfazer): só desvincula
        unlinked = c.execute("UPDATE executions SET note_id = NULL, fees_source = 'manual' WHERE note_id = ?", (note_id,)).rowcount
        c.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    return {"deleted_executions": created, "restored": restored, "unlinked": unlinked}


# ---------------------------------------------------------------- calibração das taxas
def fee_calibration(apply: bool = False) -> Dict[str, Any]:
    """Taxas B3 efetivas (% do volume) por classe, a partir das notas com uma única classe de ativo."""
    by_class: Dict[str, Dict[str, float]] = defaultdict(lambda: {"fees": 0.0, "volume": 0.0, "notes": 0})
    brokerage, orders_n = 0.0, 0
    with db.connection() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM notes")]
    for n in rows:
        groups = json.loads(n["trades_json"] or "[]")
        classes = {g.get("asset_class") for g in groups}
        fees = json.loads(n["fees_json"] or "{}")
        brokerage += sum(float(fees.get(k, 0.0)) for k in BROKER_FEE_KEYS)
        orders_n += len(groups)
        if len(classes) == 1 and n["gross_value"]:
            cls = classes.pop()
            b = by_class[cls]
            b["fees"] += float(n["b3_fees"] or 0)
            b["volume"] += float(n["gross_value"])
            b["notes"] += 1
    result: Dict[str, Any] = {"classes": {}, "notes": len(rows)}
    for cls, b in by_class.items():
        if b["volume"] > 0:
            result["classes"][cls] = {"pct": round(b["fees"] / b["volume"] * 100, 4), "notes": b["notes"], "volume": round(b["volume"], 2)}
    result["brokerage_per_order"] = round(brokerage / orders_n, 2) if orders_n else None
    if apply and (result["classes"] or result["brokerage_per_order"] is not None):
        prefs = get_prefs()
        costs = prefs["costs"]
        for cls, v in result["classes"].items():
            costs["b3_fee_pct"][cls] = v["pct"]
        if result["brokerage_per_order"] is not None:
            costs["brokerage_per_order"] = result["brokerage_per_order"]
        update_prefs({"costs": costs})
        result["applied"] = True
    return result


def irrf_by_day() -> Dict[str, Dict[str, Optional[float]]]:
    """IRRF das notas por pregão: {'AAAA-MM-DD': {'swing': x, 'day': y | None}}."""
    out: Dict[str, Dict[str, Optional[float]]] = {}
    with db.connection() as c:
        for r in c.execute("SELECT trade_date, irrf, irrf_day FROM notes"):
            d = out.setdefault(r["trade_date"], {"swing": 0.0, "day": None})
            d["swing"] = round((d["swing"] or 0.0) + float(r["irrf"] or 0.0), 2)
            if r["irrf_day"] is not None:
                d["day"] = round((d["day"] or 0.0) + float(r["irrf_day"]), 2)
    return out


def coverage(conn=None) -> Dict[str, Any]:
    """
    Quais pregões com operações (conta real) já têm nota importada. Um pregão está coberto quando todas as
    execuções dele vieram de/foram conferidas com uma nota; um mês só "fecha" com todos os pregões cobertos.
    """
    days: Dict[str, Dict[str, Any]] = {}
    with db.connection(conn) as c:
        for r in c.execute("SELECT ticker, executed_at, note_id FROM executions WHERE account = 'real'"):
            d = days.setdefault(_day(dict(r)), {"executions": 0, "with_note": 0, "tickers": set()})
            d["executions"] += 1
            if r["note_id"]:
                d["with_note"] += 1
            else:
                d["tickers"].add(r["ticker"])
    months: Dict[str, Dict[str, Any]] = {}
    for day in sorted(days):
        d = days[day]
        m = months.setdefault(day[:7], {"days": 0, "covered": 0, "missing": []})
        m["days"] += 1
        if d["with_note"] == d["executions"]:
            m["covered"] += 1
        else:
            m["missing"].append({"date": day, "executions": d["executions"] - d["with_note"], "tickers": sorted(d["tickers"])})
    for m in months.values():
        m["complete"] = m["days"] > 0 and m["covered"] == m["days"]
    return {"months": months, "days_total": len(days), "days_covered": sum(m["covered"] for m in months.values())}


__all__ = ["read_pdf", "parse_pages", "parse_trade_line", "resolve_ticker", "build_preview", "apply_preview",
           "list_notes", "delete_note", "fee_calibration", "irrf_by_day", "coverage", "NotePasswordError"]
