"""
Importador de notas de corretagem no padrão SINACOR/B3 (XP, Genial e outras corretoras que usam o mesmo layout).

Fluxo:
1. `read_pdf()` extrai o texto de cada página (aceita PDF com senha — XP usa os 3 primeiros dígitos do CPF).
2. `parse_pages()` agrupa as páginas por nota e extrai negócios + resumo financeiro (custos, IRRF, líquido).
3. `build_preview()` resolve os tickers e concilia com as execuções já registradas (mesmo dia/ativo/lado).
4. `apply_preview()` grava: atualiza custos (rateados pelo valor de cada negócio), cria as execuções que
   faltam e guarda a nota (evita importar duas vezes).
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
from typing import Any, Dict, List, Optional, Tuple

from src.core import b3_tickers, db
from src.core.config import get_prefs, now_iso, update_prefs
from src.core.market_hours import BRT, to_brt
from src.services import journal

MONEY = r"-?\d{1,3}(?:\.\d{3})*,\d{2,}"
_MONEY_RE = re.compile(MONEY)

MARKET_TYPES = [
    "OPCAO DE COMPRA", "OPCAO DE VENDA", "EXERC OPC COMPRA", "EXERC OPC VENDA", "EXERCICIO OPC COMPRA",
    "EXERCICIO OPC VENDA", "VISTA", "FRACIONARIO", "TERMO", "LEILAO", "OPCOES",
]
LINE_RE = re.compile(r"^(?:\S{1,3}\s+)?(1-BOVESPA|B3\s+RV\s+LISTADO|BOVESPA|B3\s+RV)\s+(C|V)\s+(.+)$")
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
    import pdfplumber

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
    out: Dict[str, Any] = {"items": fees, "irrf": irrf}
    m = re.search(r"valor liquido das operacoes\s*(" + MONEY + r")\s*([dc])?", scope)
    if m:
        v = _money(m.group(1))
        out["net_ops"] = -v if (m.group(2) == "d") else v
    m = re.search(r"liquido para\s*(\d{2}/\d{2}/\d{4})\s*(" + MONEY + r")\s*([dc])?", scope)
    if m:
        v = _money(m.group(2))
        out["settlement_date"] = m.group(1)
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
def _group_trades(note: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    total_value = sum(t["value"] for t in note["trades"]) or 1.0
    for t in note["trades"]:
        ticker, how = resolve_ticker(t["spec"], t["market"])
        key = (ticker or f"?{t['spec']}", t["side"])
        g = groups.setdefault(key, {"ticker": ticker, "resolved_by": how, "spec": t["spec"], "market": t["market"],
                                    "side": t["side"], "quantity": 0.0, "value": 0.0, "lines": 0, "day_trade": False})
        g["quantity"] += t["quantity"]
        g["value"] += t["value"]
        g["lines"] += 1
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


def _match(c, note: Dict[str, Any], g: Dict[str, Any]) -> None:
    g["matches"], g["action"], g["match_note"] = [], "create", ""
    if not note.get("trade_date") or not g["ticker"]:
        g["action"] = "skip" if not g["ticker"] else "create"
        g["match_note"] = "Informe o ticker para importar." if not g["ticker"] else ""
        return
    rows = [dict(r) for r in c.execute(
        "SELECT * FROM executions WHERE account = 'real' AND ticker = ? AND side = ? AND (note_id IS NULL)", (g["ticker"], g["side"]))]
    same_day = [r for r in rows if (to_brt(r["executed_at"]) or datetime.min.replace(tzinfo=BRT)).date().isoformat() == note["trade_date"]]
    if not same_day:
        g["match_note"] = "Não há execução registrada — será criada."
        return
    q = sum(r["quantity"] for r in same_day)
    g["matches"] = [{"id": r["id"], "quantity": r["quantity"], "price": r["price"], "fees": r["fees"], "fees_source": r["fees_source"]} for r in same_day]
    if abs(q - g["quantity"]) < 1e-6:
        g["action"] = "update"
        price_diff = len(same_day) == 1 and abs(same_day[0]["price"] - g["price"]) > 0.00005
        g["match_note"] = "Custos reais serão aplicados" + (f"; preço corrigido de {same_day[0]['price']:.2f} para {g['price']:.4f}" if price_diff else "") + "."
    else:
        g["action"] = "skip"
        g["match_note"] = f"Quantidade não bate (nota {g['quantity']:,.0f} x registrado {q:,.0f}). Revise e escolha."


def build_preview(files: List[Tuple[str, bytes]], password: Optional[str] = None) -> Dict[str, Any]:
    notes_out, errors = [], []
    with db.connection() as c:
        for name, data in files:
            try:
                pages = read_pdf(data, password)
            except ValueError as exc:
                errors.append({"file": name, "error": str(exc)})
                continue
            file_hash = hashlib.sha256(data).hexdigest()
            parsed = parse_pages(pages)
            if not parsed:
                errors.append({"file": name, "error": "Nenhum negócio de Bovespa reconhecido (é uma nota SINACOR de ações/opções?)."})
                continue
            for n in parsed:
                exists = c.execute("SELECT id FROM notes WHERE broker = ? AND number = ? AND trade_date = ?",
                                   (n["broker"], n["number"], n["trade_date"] or "")).fetchone()
                groups = _group_trades(n)
                for g in groups:
                    _match(c, n, g)
                notes_out.append({
                    "file": name, "file_hash": file_hash, "broker": n["broker"], "number": n["number"],
                    "trade_date": n["trade_date"], "settlement_date": n["fees"].get("settlement_date"),
                    "fees": n["fees"].get("items", {}), "irrf": n["irrf"], "b3_fees": n["b3_fees"], "broker_fees": n["broker_fees"],
                    "total_costs": n["total_costs"], "gross_value": n["gross_value"], "net_value": n["fees"].get("net_value"),
                    "warnings": n["warnings"], "already_imported": bool(exists), "groups": groups,
                    "trades": [{k: t[k] for k in ("side", "market", "spec", "obs", "quantity", "price", "value", "dc")} for t in n["trades"]],
                })
    notes_out.sort(key=lambda n: (n["trade_date"] or "", n["number"]))
    return {"notes": notes_out, "errors": errors}


# ---------------------------------------------------------------- gravação
def apply_preview(payload: Dict[str, Any], update_estimates: bool = True) -> Dict[str, Any]:
    stats = {"notes": 0, "updated": 0, "created": 0, "skipped": 0, "errors": []}
    for n in sorted(payload.get("notes", []), key=lambda n: (n.get("trade_date") or "", n.get("number") or "")):
        if n.get("already_imported") or not n.get("trade_date"):
            stats["skipped"] += len(n.get("groups", []))
            continue
        with db.transaction() as c:
            if c.execute("SELECT 1 FROM notes WHERE broker = ? AND number = ? AND trade_date = ?", (n["broker"], n["number"], n["trade_date"])).fetchone():
                stats["skipped"] += len(n.get("groups", []))
                continue
            cur = c.execute(
                "INSERT INTO notes(broker, number, trade_date, settlement_date, file_name, file_hash, gross_value, net_value, total_costs, "
                "brokerage, b3_fees, taxes, irrf, fees_json, trades_json, imported_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (n["broker"], n["number"], n["trade_date"], n.get("settlement_date"), n.get("file"), n.get("file_hash"),
                 n.get("gross_value"), n.get("net_value"), n.get("total_costs"), (n.get("fees") or {}).get("corretagem", 0.0),
                 n.get("b3_fees"), (n.get("fees") or {}).get("impostos", 0.0), n.get("irrf"),
                 json.dumps(n.get("fees") or {}), json.dumps(n.get("groups") or [], ensure_ascii=False), now_iso()),
            )
            note_id = cur.lastrowid
            # compras antes das vendas (day trade na mesma nota)
            for g in sorted(n.get("groups", []), key=lambda g: 0 if g.get("side") == "BUY" else 1):
                action = g.get("action")
                ticker = b3_tickers.clean_ticker(g.get("ticker"))
                try:
                    if action == "update" and g.get("matches"):
                        _apply_update(c, note_id, g)
                        stats["updated"] += len(g["matches"])
                    elif action == "create" and ticker:
                        journal.add_execution(
                            {"ticker": ticker, "side": g["side"], "quantity": g["quantity"], "price": g["price"], "fees": g["fees"],
                             "executed_at": f"{n['trade_date']}T10:00:00-03:00",
                             "asset_class": b3_tickers.asset_class(None, ticker),
                             "note": f"Importado da nota {n['broker']} nº {n['number']}"},
                            account="real", source="note", note_id=note_id, fees_source="note", conn=c,
                        )
                        stats["created"] += 1
                    else:
                        stats["skipped"] += 1
                except ValueError as exc:
                    stats["errors"].append(f"Nota {n['number']} · {ticker or g.get('spec')}: {exc}")
            stats["notes"] += 1
    if update_estimates and stats["notes"]:
        stats["calibration"] = fee_calibration(apply=True)
    return stats


def _apply_update(c, note_id: int, g: Dict[str, Any]) -> None:
    ids = [m["id"] for m in g["matches"]]
    rows = [dict(r) for r in c.execute(f"SELECT * FROM executions WHERE id IN ({','.join('?' * len(ids))})", ids)]
    total = sum(r["quantity"] * r["price"] for r in rows) or 1.0
    fix_price = len(rows) == 1
    remaining = round(float(g["fees"]), 2)
    for i, r in enumerate(rows):
        share = remaining if i == len(rows) - 1 else round(g["fees"] * (r["quantity"] * r["price"]) / total, 2)
        remaining = round(remaining - share, 2)
        price = float(g["price"]) if fix_price else r["price"]
        c.execute("UPDATE executions SET fees = ?, price = ?, note_id = ?, fees_source = 'note' WHERE id = ?",
                  (share, round(price, 6), note_id, r["id"]))


def list_notes(limit: int = 50) -> List[Dict[str, Any]]:
    with db.connection() as c:
        rows = [dict(r) for r in c.execute("SELECT id, broker, number, trade_date, gross_value, total_costs, b3_fees, brokerage, irrf, net_value, imported_at "
                                           "FROM notes ORDER BY trade_date DESC, id DESC LIMIT ?", (limit,))]
        for r in rows:
            r["executions"] = c.execute("SELECT COUNT(*) FROM executions WHERE note_id = ?", (r["id"],)).fetchone()[0]
    return rows


def delete_note(note_id: int) -> Dict[str, int]:
    """Desfaz a importação: apaga execuções criadas pela nota e desvincula as atualizadas (os custos ficam)."""
    with db.transaction() as c:
        if not c.execute("SELECT 1 FROM notes WHERE id = ?", (note_id,)).fetchone():
            raise KeyError(note_id)
        created = c.execute("DELETE FROM executions WHERE note_id = ? AND source = 'note'", (note_id,)).rowcount
        unlinked = c.execute("UPDATE executions SET note_id = NULL, fees_source = 'manual' WHERE note_id = ?", (note_id,)).rowcount
        c.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    return {"deleted_executions": created, "unlinked": unlinked}


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


def irrf_by_month() -> Dict[str, float]:
    with db.connection() as c:
        out: Dict[str, float] = defaultdict(float)
        for r in c.execute("SELECT trade_date, irrf FROM notes WHERE irrf IS NOT NULL"):
            out[r["trade_date"][:7]] += float(r["irrf"] or 0)
    return dict(out)


__all__ = ["read_pdf", "parse_pages", "parse_trade_line", "resolve_ticker", "build_preview", "apply_preview",
           "list_notes", "delete_note", "fee_calibration", "irrf_by_month", "NotePasswordError"]
