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
    assert bn.resolve_ticker("CASAS BAHIA ON NM", "VISTA") == ("BHIA3", "nome")
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


# Layout real da Genial (dados fictícios): C/V colado em "B3 RV LISTADOC", obs "#", "/EJ" na especificação,
# código de opção com 1 e 2 dígitos e a data de liquidação com o espaço deslocado ("para0 6/10/2026").
GENIAL_REAL = """NOTA DE CORRETAGEM
Nr.Nota Folha Data pregão
12345 1 05/10/2026
GENIAL CCTVM S/A
Cliente C.P.F./C.N.P.J./C.V.M./C.O.B.
1234567-1 CLIENTE FICTICIO 000.000.000-00
Negócios realizados
Q Negociação C/V Tipo mercado Prazo Especificação do título Obs. (*) Quantidade Preço / Ajuste Valor Operação / Ajuste D/C
B3 RV LISTADOC OPCAO DE COMPRA 11/26 PETRK420 PN 42,00 PETR # 1.000 0,50 500,00 D
B3 RV LISTADOC OPCAO DE COMPRA 10/26 ROXOJ15 DRN 15,00 ROXO 1.000 0,40 400,00 D
B3 RV LISTADOC OPCAO DE COMPRA 11/26 VALEK600 ON 60,00 VALE /EJ 200 1,00 200,00 D
B3 RV LISTADOC OPCAO DE COMPRA 11/26 BBASK3 ON 21,00 BBAS 1.000 0,30 300,00 D
Resumo dos Negócios Resumo Financeiro D/C
Vendas à vista 0,00 Clearing
Opções - Compras 1.400,00 Valor líquido das operações 1.400,00 D
Opções - Vendas 0,00 Taxa de liquidação/CCP 0,39 D
Compras à Futuro 0,00 Taxa de Registro 0,98 D
Vendas à Futuro 0,00 Total CBLC 1.401,37 D
Ajuste do Dia 0,00 Bolsa
Ajuste da Posição 0,00 Taxa de termo/opções 0,00 D
Ajuste de Day-Trade 0,00 Emolumentos 0,52 D
Valor das operações 1.400,00 Total Bovespa / Soma 0,52 D
Corretagem / Despesas
Clearing 4,95 D
Execução 0,00 D
Execução casa 0,00 D
ISS ( SÃO PAULO ) 0,24
ISS/PIS/COFINS 0,47 D
Total corretagem / Despesas 5,42
(*) - Observações: A - Posição Futuro T - Liquidação pelo Bruto Líquido para0 6/10/2026 1.407,31 D"""


def test_parse_genial_real_layout():
    notes = bn.parse_pages([GENIAL_REAL])
    assert len(notes) == 1
    n = notes[0]
    assert n["broker"] == "Genial" and n["number"] == "12345" and n["trade_date"] == "2026-10-05" and n["warnings"] == []
    assert [t["quantity"] for t in n["trades"]] == [1000, 1000, 200, 1000]
    groups = {g["ticker"]: g for g in bn._group_trades(n)}
    assert set(groups) == {"PETRK420", "ROXOJ15", "VALEK600", "BBASK3"}
    assert n["b3_fees"] == pytest.approx(0.39 + 0.98 + 0.52) and n["broker_fees"] == pytest.approx(5.42)
    assert n["total_costs"] == pytest.approx(7.31) and sum(g["fees"] for g in groups.values()) == pytest.approx(7.31)
    assert n["fees"]["settlement_date"] == "06/10/2026" and n["fees"]["net_value"] == pytest.approx(-1407.31)


GENIAL_OPTIONS_535 = """NOTA DE CORRETAGEM
Nr.Nota Folha Data pregão 535 1 09/10/2026
GENIAL CCTVM S/A
Cliente C.P.F./C.N.P.J./C.V.M./C.O.B.
4399987-1 PAULO JOSE ARAGAO JUNIOR 064.623.619-99
Negócios realizados
Q Negociação C/V Tipo mercado Prazo Especificação do título Obs. (*) Quantidade Preço / Ajuste Valor Operação / Ajuste D/C
B3 RV LISTADOC OPCAO DE COMPRA 10/26 COGNJ320 ON 3,20 COGN 1.000 0,09 90,00 D
B3 RV LISTADOC OPCAO DE COMPRA 10/26 COGNJ320 ON 3,20 COGN 1.000 0,09 90,00 D
B3 RV LISTADOV OPCAO DE COMPRA 11/26 AZZAK275 ON 27,53 AZZA 100 1,50 150,00 C
B3 RV LISTADOC OPCAO DE COMPRA 11/26 TENDK327 ON 32,12 TEND 100 2,64 264,00 D
B3 RV LISTADOC OPCAO DE COMPRA 11/26 TENDK327 ON 32,12 TEND 400 2,64 1.056,00 D
B3 RV LISTADOV OPCAO DE COMPRA 11/26 HAPVK920 ON 9,20 HAPV FM 1.000 0,97 970,00 C
B3 RV LISTADOV OPCAO DE COMPRA 11/26 TOTSK401 ON 40,06 TOTS FM 300 4,34 1.302,00 C
B3 RV LISTADOC OPCAO DE COMPRA 10/26 COGNJ320 ON 3,20 COGN 1.000 0,09 90,00 D
B3 RV LISTADOV OPCAO DE COMPRA 11/26 AZZAK275 ON 27,53 AZZA 900 1,50 1.350,00 C
B3 RV LISTADOV OPCAO DE COMPRA 11/26 HAPVK920 ON 9,20 HAPV FM 200 0,96 192,00 C
B3 RV LISTADOV OPCAO DE COMPRA 11/26 TOTSK401 ON 40,06 TOTS FM 200 4,34 868,00 C
B3 RV LISTADOV OPCAO DE COMPRA 11/26 BBASK254 ON 25,29 BBAS FM 1.800 1,34 2.412,00 C
Resumo dos Negócios Resumo Financeiro D/C
Vendas à vista 0,00 Clearing
Compras à vista 0,00 Valor líquido das operações 5.654,00 C
Opções - Compras 1.590,00 Taxa de liquidação/CCP 2,42 D
Opções - Vendas 7.244,00 Taxa de Registro 6,13 D
Total CBLC 5.645,45 C
Bolsa
Taxa de termo/opções 0,00 D
Emolumentos 3,26 D
Total Bovespa / Soma 3,26 D
Clearing 8,91 D
Execução 0,00 D
Execução casa 0,00 D
ISS ( SÃO PAULO ) 0,44
I.R.R.F s/ operações, base R$ 5.654,00 0,28
ISS/PIS/COFINS 0,85 D
Total corretagem / Despesas 9,76
Líquido para13/10/2026 5.632,43 C"""

GENIAL_STOCKS_13516 = """NOTA DE CORRETAGEM
Nr.Nota Folha Data pregão 13516 1 09/10/2026
GENIAL CCTVM S/A
Cliente C.P.F./C.N.P.J./C.V.M./C.O.B.
4399987-1 PAULO JOSE ARAGAO JUNIOR 064.623.619-99
Negócios realizados
Q Negociação C/V Tipo mercado Prazo Especificação do título Obs. (*) Quantidade Preço / Ajuste Valor Operação / Ajuste D/C
B3 RV LISTADOC VISTA CASAS BAHIA ON NM @ 1.000 1,50 1.500,00 D
Resumo dos Negócios Resumo Financeiro D/C
Compras à vista 1.500,00 Valor líquido das operações 1.500,00 D
Taxa de liquidação/CCP 0,33 D
Taxa de Registro 0,00 D
Total CBLC 1.500,33 D
Emolumentos 0,07 D
Total Bovespa / Soma 0,07 D
Clearing 0,99 D
ISS ( SÃO PAULO ) 0,04
ISS/PIS/COFINS 0,09 D
Total corretagem / Despesas 1,08
Líquido para14/10/2026 1.501,51 D"""


def test_parse_genial_options_3_digit_and_fm():
    notes = bn.parse_pages([GENIAL_OPTIONS_535])
    assert len(notes) == 1
    n = notes[0]
    assert n["broker"] == "Genial" and n["number"] == "535" and n["trade_date"] == "2026-10-09"
    assert len(n["trades"]) == 12
    groups = {g["ticker"]: g for g in bn._group_trades(n)}
    assert set(groups) == {"COGNJ320", "AZZAK275", "TENDK327", "HAPVK920", "TOTSK401", "BBASK254"}
    assert n["irrf"] == pytest.approx(0.28)
    assert n["fees"]["net_value"] == pytest.approx(5632.43)
    assert n["gross_value"] == pytest.approx(8834.0)


def test_parse_genial_stocks_at_symbol():
    notes = bn.parse_pages([GENIAL_STOCKS_13516])
    assert len(notes) == 1
    n = notes[0]
    assert n["broker"] == "Genial" and n["number"] == "13516" and n["trade_date"] == "2026-10-09"
    assert len(n["trades"]) == 1
    t = n["trades"][0]
    assert t["obs"] == "@"
    ticker, how = bn.resolve_ticker(t["spec"], t["market"])
    assert ticker == "BHIA3" and how == "nome"
    assert n["fees"]["net_value"] == pytest.approx(-1501.51)


def test_same_day_two_notes_and_coverage(tmp_db):
    # Duas execuções no dia 09/10/2026 (uma de Ações e outra de Opções)
    journal.add_execution({
        "ticker": "BHIA3", "side": "BUY", "quantity": 1000, "price": 1.50,
        "executed_at": "2026-10-09T10:15:00-03:00", "fees": 1.40,
    }, account="real")
    journal.add_execution({
        "ticker": "BBASK254", "side": "SELL", "quantity": 1800, "price": 1.34,
        "executed_at": "2026-10-09T11:30:00-03:00", "fees": 3.00,
    }, allow_short=True, account="real")

    # 1. Sem notas: coverage indica ambas as operações com detalhes
    cov = bn.coverage()
    assert cov["days_total"] == 1 and cov["days_covered"] == 0
    miss = cov["months"]["2026-10"]["missing"][0]
    assert miss["date"] == "2026-10-09" and miss["executions"] == 2
    assert set(miss["tickers"]) == {"BHIA3", "BBASK254"}
    assert len(miss["operations"]) == 2
    op_tickers = {op["ticker"]: op for op in miss["operations"]}
    assert op_tickers["BHIA3"]["side"] == "BUY" and op_tickers["BHIA3"]["value"] == 1500.0
    assert op_tickers["BBASK254"]["side"] == "SELL" and op_tickers["BBASK254"]["value"] == 2412.0
    assert miss["imported_notes"] == []

    # 2. Importa apenas a nota de opções (535)
    prev1 = bn.build_preview([("opcoes.pdf", make_pdf([GENIAL_OPTIONS_535]))])
    assert len(prev1["notes"]) == 1 and prev1["notes"][0]["number"] == "535"
    res1 = bn.apply_preview(prev1)
    assert res1["notes"] == 1 and res1["updated"] == 1  # atualizou BBASK254

    # 3. Coverage agora mostra que falta APENAS BHIA3, e lista a nota 535 importada
    cov2 = bn.coverage()
    assert cov2["days_covered"] == 0  # o dia ainda não fechou totalmente
    miss2 = cov2["months"]["2026-10"]["missing"][0]
    assert miss2["executions"] == 1
    assert miss2["tickers"] == ["BHIA3"]
    assert len(miss2["operations"]) == 1 and miss2["operations"][0]["ticker"] == "BHIA3"
    assert len(miss2["imported_notes"]) == 1 and miss2["imported_notes"][0]["number"] == "535"

    # 4. Importa a nota de ações (13516) do mesmo dia
    prev2 = bn.build_preview([("acoes.pdf", make_pdf([GENIAL_STOCKS_13516]))])
    assert len(prev2["notes"]) == 1 and prev2["notes"][0]["number"] == "13516"
    res2 = bn.apply_preview(prev2)
    assert res2["notes"] == 1 and res2["updated"] == 1  # atualizou BHIA3

    # 5. Coverage agora está 100% coberto!
    cov3 = bn.coverage()
    assert cov3["days_covered"] == 1 and cov3["days_total"] == 1
    assert cov3["months"]["2026-10"]["missing"] == []
    assert cov3["months"]["2026-10"]["complete"] is True


def test_reconcile_existing_note_with_pending_execution(tmp_db):
    """
    Cenário real: a nota já foi inserida no banco de dados (ex: importação anterior parcial),
    mas a execução de BHIA3 está registrada com note_id IS NULL.
    Ao reler a nota, o sistema deve reconhecer que ela já existe no banco, mas vincular
    a execução pendente a ela e permitir apply_preview para completar a cobertura.
    """
    # 1. Cria execução pendente sem nota
    ex = journal.add_execution({
        "ticker": "BHIA3", "side": "BUY", "quantity": 1000, "price": 1.50,
        "executed_at": "2026-10-09T10:15:00-03:00", "fees": 0.0,
    }, account="real")

    # 2. Simula que a nota 13516 já existe no banco (ex: importada vazia anteriormente)
    with db.transaction() as c:
        cur = c.execute(
            "INSERT INTO notes(broker, number, trade_date, gross_value, total_costs, b3_fees, brokerage, imported_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            ("Genial", "13516", "2026-10-09", 1500.0, 1.48, 0.40, 1.08, "2026-10-09T12:00:00-03:00"),
        )
        existing_nid = cur.lastrowid

    # Coverage acusa pendência
    cov = bn.coverage()
    assert cov["days_covered"] == 0
    assert cov["months"]["2026-10"]["missing"][0]["tickers"] == ["BHIA3"]

    # 3. Lê o PDF da nota 13516
    prev = bn.build_preview([("acoes_13516.pdf", make_pdf([GENIAL_STOCKS_13516]))])
    assert len(prev["notes"]) == 1
    n = prev["notes"][0]
    assert n["already_imported"] is True
    assert n["existing_id"] == existing_nid
    assert n["has_pending_actions"] is True

    g = n["groups"][0]
    assert g["ticker"] == "BHIA3"
    assert g["already_linked"] is False
    assert g["action"] == "update"
    assert len(g["matches"]) == 1
    assert g["matches"][0]["id"] == ex["id"]

    # 4. Aplica o preview
    res = bn.apply_preview(prev)
    assert res["notes"] == 1
    assert res["updated"] == 1

    # 5. A execução agora está vinculada ao existing_nid com custos reais
    ex_updated = next(e for e in journal.list_executions() if e["id"] == ex["id"])
    assert ex_updated["note_id"] == existing_nid
    assert ex_updated["fees"] == pytest.approx(1.48)
    assert ex_updated["fees_source"] == "note"

    # 6. Coverage agora está 100%
    cov2 = bn.coverage()
    assert cov2["days_covered"] == 1
    assert cov2["months"]["2026-10"]["complete"] is True

    # 7. Se reler novamente agora que tudo está vinculado:
    again = bn.build_preview([("acoes_13516.pdf", make_pdf([GENIAL_STOCKS_13516]))])
    assert again["notes"][0]["already_imported"] is True
    assert again["notes"][0]["has_pending_actions"] is False
    assert again["notes"][0]["groups"][0]["already_linked"] is True
    assert again["notes"][0]["groups"][0]["action"] == "skip"
    assert bn.apply_preview(again)["notes"] == 0
