"""Importador de notas de corretagem SINACOR (XP / Genial): parser, conciliação, custos, calibração e IRRF."""
import io

import pytest

from src.core import db
from src.core.config import get_prefs
from src.services import brokerage_notes as bn
from src.services import journal, results

XP_PAGE = """NOTA DE CORRETAGEM
Nr. nota Folha Data pregão
75104212 1 05/10/2026
XP INVESTIMENTOS CCTVM S/A
Av. Ataulfo de Paiva, 153 - Sala 201 - Leblon - Rio de Janeiro - RJ
Cliente
1234567 FULANO DE TAL
Negócios realizados
Q Negociação C/V Tipo mercado Prazo Especificação do título Obs. (*) Quantidade Preço / Ajuste Valor Operação / Ajuste D/C
1-BOVESPA C OPCAO DE COMPRA 11/26 NATUK800 ON 8,00 NATU 2.600 0,39 1.014,00 D
1-BOVESPA V VISTA PETROBRAS PN N2 100 38,50 3.850,00 C
Resumo dos Negócios Resumo Financeiro
Debêntures 0,00 Clearing
Vendas à vista 3.850,00 Valor líquido das operações 2.836,00 C
Compras à vista 0,00 Taxa de liquidação 0,95 D
Opções - compras 1.014,00 Taxa de Registro 0,30 D
Opções - vendas 0,00 Total CBLC 2.834,75 C
Operações à termo 0,00 Bolsa
Valor das oper. c/ títulos públ. (v. nom.) 0,00 Taxa de termo/opções 0,00 D
Valor das operações 4.864,00 Taxa A.N.A. 0,00 D
Emolumentos 0,24 D
Total Bovespa / Soma 0,24 D
Especificações diversas Custos Operacionais
Taxa Operacional 0,00 D
Execução 0,00
Taxa de Custódia 0,00
Impostos 0,00
I.R.R.F. s/ operações, base R$3.850,00 0,19
Outros 0,00 D
Total Custos / Despesas 0,00 D
Líquido para 07/10/2026 2.834,32 C"""

GENIAL_P1 = """NOTA DE NEGOCIAÇÃO
Nr. nota Folha Data pregão
998877 1 06/10/2026
GENIAL INVESTIMENTOS CORRETORA DE VALORES MOBILIÁRIOS S.A.
Negócios realizados
Q Negociação C/V Tipo mercado Prazo Especificação do título Obs. (*) Quantidade Preço / Ajuste Valor Operação / Ajuste D/C
B3 RV LISTADO C OPCAO DE COMPRA 10/26 BBASJ216 ON 21,04 BBAS D 1.000 1,30 1.300,00 D
B3 RV LISTADO V OPCAO DE COMPRA 10/26 BBASJ216 ON 21,04 BBAS D 1.000 1,45 1.450,00 C
Resumo Financeiro
Valor líquido das operações CONTINUA...
Líquido para CONTINUA..."""

GENIAL_P2 = """NOTA DE NEGOCIAÇÃO
Nr. nota Folha Data pregão
998877 2 06/10/2026
GENIAL INVESTIMENTOS CORRETORA DE VALORES MOBILIÁRIOS S.A.
Negócios realizados
B3 RV LISTADO C OPCAO DE VENDA 10/26 PETRV480 PN 45,86 PETR 500 0,20 100,00 D
Resumo dos Negócios Resumo Financeiro
Valor líquido das operações 50,00 C
Taxa de liquidação 0,50 D
Taxa de Registro 0,40 D
Taxa de termo/opções 0,00 D
Emolumentos 0,90 D
Corretagem 2,00 D
Impostos 0,20 D
I.R.R.F. s/ operações, base R$0,00 0,00
Outros 0,00 D
Líquido para 07/10/2026 46,00 C"""


def make_pdf(pages, password=None) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    kw = {}
    if password:
        from reportlab.lib import pdfencrypt

        kw["encrypt"] = pdfencrypt.StandardEncryption(password, canPrint=1)
    c = canvas.Canvas(buf, pagesize=A4, **kw)
    for page in pages:
        y = 810
        c.setFont("Helvetica", 7)
        for line in page.splitlines():
            c.drawString(20, y, line)
            y -= 11
        c.showPage()
    c.save()
    return buf.getvalue()


def test_parse_trade_lines():
    t = bn.parse_trade_line("1-BOVESPA C OPCAO DE COMPRA 11/26 NATUK800 ON 8,00 NATU 2.600 0,39 1.014,00 D")
    assert t["side"] == "BUY" and t["quantity"] == 2600 and t["price"] == 0.39 and t["value"] == 1014.0 and t["prazo"] == "11/26"
    assert bn.resolve_ticker(t["spec"], t["market"]) == ("NATUK800", "opcao")
    t2 = bn.parse_trade_line("B3 RV LISTADO V OPCAO DE COMPRA 10/26 BBASJ216 ON 21,04 BBAS D 1.000 1,45 1.450,00 C")
    assert t2["obs"] == "D" and t2["side"] == "SELL"
    t3 = bn.parse_trade_line("1-BOVESPA V VISTA PETROBRAS PN N2 100 38,50 3.850,00 C")
    assert bn.resolve_ticker(t3["spec"], t3["market"]) == ("PETR4", "nome")
    assert bn.resolve_ticker("ISHARE BOVA CI", "VISTA") == ("BOVA11", "nome")
    assert bn.resolve_ticker("EMPRESA DESCONHECIDA ON NM", "VISTA") == (None, "")
    assert bn.parse_trade_line("Resumo dos Negócios Resumo Financeiro") is None


def test_parse_xp_note_text():
    notes = bn.parse_pages([XP_PAGE])
    assert len(notes) == 1
    n = notes[0]
    assert n["broker"] == "XP" and n["number"] == "75104212" and n["trade_date"] == "2026-10-05"
    assert n["b3_fees"] == pytest.approx(1.49) and n["total_costs"] == pytest.approx(1.49)
    assert n["irrf"] == pytest.approx(0.19)
    assert n["fees"]["net_value"] == pytest.approx(2834.32)
    assert n["warnings"] == []


def test_parse_genial_multipage_note_text():
    notes = bn.parse_pages([GENIAL_P1, GENIAL_P2])
    assert len(notes) == 1
    n = notes[0]
    assert n["broker"] == "Genial" and n["pages"] == [1, 2] and len(n["trades"]) == 3
    assert n["b3_fees"] == pytest.approx(1.80) and n["broker_fees"] == pytest.approx(2.20)
    assert n["warnings"] == []


def test_pdf_with_password_roundtrip(tmp_db):
    data = make_pdf([XP_PAGE], password="123")
    with pytest.raises(bn.NotePasswordError):
        bn.read_pdf(data)
    pages = bn.read_pdf(data, "123")
    assert "75104212" in pages[0]
    prev = bn.build_preview([("nota.pdf", data)], password="123")
    assert prev["errors"] == [] and len(prev["notes"]) == 1
    groups = {g["ticker"]: g for g in prev["notes"][0]["groups"]}
    assert set(groups) == {"NATUK800", "PETR4"}
    assert sum(g["fees"] for g in groups.values()) == pytest.approx(1.49)


def test_preview_matches_and_apply_updates_fees_and_creates_missing(tmp_db):
    journal.add_execution({"ticker": "NATUK800", "side": "BUY", "quantity": 2600, "price": 0.40, "fees": 0.66,
                           "executed_at": "2026-10-05T11:00:00-03:00"}, fees_source="estimate")
    journal.add_execution({"ticker": "PETR4", "side": "BUY", "quantity": 100, "price": 37.0, "fees": 0.0,
                           "executed_at": "2026-10-01T11:00:00-03:00"})
    prev = bn.build_preview([("xp.pdf", make_pdf([XP_PAGE]))])
    note = prev["notes"][0]
    g = {x["ticker"]: x for x in note["groups"]}
    assert g["NATUK800"]["action"] == "update" and "preço 0,4 → 0,39" in g["NATUK800"]["match_note"]
    assert g["PETR4"]["action"] == "create"

    res = bn.apply_preview(prev)
    assert res["notes"] == 1 and res["updated"] == 1 and res["created"] == 1 and not res["errors"]
    ex = {e["ticker"] + e["side"]: e for e in journal.list_executions()}
    natu = ex["NATUK800BUY"]
    assert natu["fees_source"] == "note" and natu["price"] == pytest.approx(0.39)
    assert natu["fees"] + ex["PETR4SELL"]["fees"] == pytest.approx(1.49)
    assert ex["PETR4SELL"]["source"] == "note"

    # importar de novo não duplica
    again = bn.build_preview([("xp.pdf", make_pdf([XP_PAGE]))])
    assert again["notes"][0]["already_imported"]
    assert bn.apply_preview(again)["notes"] == 0

    # calibração aplicada às estimativas (nota mista não entra; precisa de nota de uma classe só)
    cal = res["calibration"]
    assert cal["brokerage_per_order"] == 0.0

    # IRRF real da nota entra na apuração
    tax = results.tax_report()
    oct_ = next(m for m in tax["months"] if m["month"] == "2026-10")
    assert oct_["irrf_source"] == "nota"

    # desfazer
    nid = bn.list_notes()[0]["id"]
    out = bn.delete_note(nid)
    assert out == {"deleted_executions": 1, "restored": 1, "unlinked": 0}
    natu = next(e for e in journal.list_executions() if e["ticker"] == "NATUK800")
    assert natu["price"] == pytest.approx(0.40) and natu["fees"] == pytest.approx(0.66) and natu["fees_source"] == "estimate"


def test_calibration_from_single_class_note(tmp_db):
    prev = bn.build_preview([("genial.pdf", make_pdf([GENIAL_P1, GENIAL_P2]))])
    assert prev["notes"][0]["broker"] == "Genial"
    res = bn.apply_preview(prev)
    assert res["created"] == 3 and not res["errors"]
    cal = res["calibration"]
    assert cal["classes"]["OPCAO"]["pct"] == pytest.approx(1.80 / 2850 * 100, rel=1e-3)
    assert get_prefs()["costs"]["b3_fee_pct"]["OPCAO"] == pytest.approx(cal["classes"]["OPCAO"]["pct"])
    # day trade da nota: compra e venda de BBASJ216 no mesmo dia -> evento 'day'
    kinds = {e["kind"] for e in journal.ledger()["events"]}
    assert "day" in kinds


def test_api_endpoints(tmp_db):
    from web.app import create_app

    app = create_app(start_monitor=False, db_path=tmp_db)
    client = app.test_client()
    data = make_pdf([XP_PAGE], password="123")
    r = client.post("/api/notes/parse", data={"files": (io.BytesIO(data), "nota.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 200 and r.get_json()["errors"][0]["error"].startswith("PDF protegido")
    r = client.post("/api/notes/parse", data={"files": (io.BytesIO(data), "nota.pdf"), "password": "123"}, content_type="multipart/form-data")
    prev = r.get_json()
    assert len(prev["notes"]) == 1
    r = client.post("/api/notes/apply", json={"preview": prev, "update_estimates": False})
    body = r.get_json()
    # a nota é a verdade: as duas linhas viram execuções (a venda de PETR4 abre posição vendida)
    assert r.status_code == 200 and body["created"] == 2 and not body["errors"]
    assert len(client.get("/api/notes").get_json()["notes"]) == 1
