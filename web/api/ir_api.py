"""Calculadora de IRPF: apuração mensal (fechado com notas x estimado) e simulação de encerrar tudo."""
from flask import Blueprint, jsonify

from src.services import irpf

bp = Blueprint("ir_api", __name__, url_prefix="/api/ir")


@bp.get("")
def report():
    return jsonify(irpf.report())


@bp.get("/simulate-close")
def simulate_close():
    return jsonify(irpf.simulate_close_all())
