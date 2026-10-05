"""Resultados reais, IR e exportação."""
from flask import Blueprint, Response, jsonify, request

from src.core.market_hours import now_brt
from src.services import results

bp = Blueprint("results_api", __name__, url_prefix="/api")


@bp.get("/results")
def get_results():
    return jsonify(results.summary(request.args.get("from") or None, request.args.get("to") or None))


@bp.get("/results/tax")
def get_tax():
    return jsonify(results.tax_report())


@bp.get("/export/<kind>.csv")
def export_csv(kind):
    if kind == "execucoes":
        body = results.executions_csv()
    elif kind == "operacoes":
        body = results.trades_csv()
    else:
        raise KeyError(kind)
    stamp = now_brt().strftime("%Y%m%d")
    return Response(
        "﻿" + body,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="copiloto_{kind}_{stamp}.csv"'},
    )
