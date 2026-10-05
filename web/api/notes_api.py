"""Importação de notas de corretagem (XP, Genial e demais no padrão SINACOR)."""
from flask import Blueprint, jsonify, request

from src.services import brokerage_notes as bn

bp = Blueprint("notes_api", __name__, url_prefix="/api/notes")


@bp.get("")
def list_notes():
    return jsonify({"notes": bn.list_notes(), "calibration": bn.fee_calibration(apply=False), "coverage": bn.coverage()})


@bp.post("/parse")
def parse():
    files = request.files.getlist("files")
    if not files:
        raise ValueError("Envie ao menos um PDF de nota de corretagem.")
    payload = [(f.filename or "nota.pdf", f.read()) for f in files]
    return jsonify(bn.build_preview(payload, password=(request.form.get("password") or "").strip() or None))


@bp.post("/apply")
def apply():
    d = request.get_json(silent=True) or {}
    return jsonify(bn.apply_preview(d.get("preview") or {}, update_estimates=bool(d.get("update_estimates", True))))


@bp.delete("/<int:note_id>")
def delete(note_id):
    return jsonify(bn.delete_note(note_id))
