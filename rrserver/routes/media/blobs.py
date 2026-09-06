import hashlib
import uuid
from datetime import UTC, datetime

from flask import Flask, jsonify, request, send_file

from ...auth import require_account
from ...models import Account
from .storage import safe_blob_path

CATEGORIES = {
    "1": "room",
    "2": "data",
    "3": "image",
    "4": "video",
    "5": "invention",
    "6": "roommetadata",
}


def register_blob_routes(app: Flask) -> None:
    @app.post("/upload")
    @require_account
    def upload_blob(_account: Account):
        file_type = request.form.get("FileType", request.form.get("fileType", "0"))
        uploaded = next(iter(request.files.values()), None)
        if uploaded is None:
            explicit = (
                request.form.get("imageName")
                or request.form.get("filename")
                or request.form.get("name")
            )
            if explicit:
                return jsonify(filename=explicit)
            return jsonify(error="missing filename or valid upload data"), 400
        category = CATEGORIES.get(str(file_type))
        if category is None:
            return jsonify(error="missing or unknown FileType"), 400
        suffix = ".inv" if str(file_type) == "5" else ""
        blob_name = f"{datetime.now(UTC).date().isoformat()}/{uuid.uuid4()}{suffix}"
        destination = safe_blob_path(category, blob_name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        uploaded.save(destination)
        return jsonify(filename=blob_name)

    @app.get("/<category>/<path:blob_name>")
    def download_blob(category: str, blob_name: str):
        if category not in CATEGORIES.values():
            return "", 404
        candidate = safe_blob_path(category, blob_name)
        if candidate is None or not candidate.is_file():
            return "", 404
        response = send_file(candidate, mimetype="application/octet-stream", conditional=True)
        response.headers["X-Content-SHA256"] = hashlib.sha256(candidate.read_bytes()).hexdigest()
        return response
