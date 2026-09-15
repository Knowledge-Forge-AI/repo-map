from flask import Blueprint

bp = Blueprint("admin", __name__)


@bp.post("/admin/jobs")
def create_job():
    return "queued"
