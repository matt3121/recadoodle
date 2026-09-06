import uuid

from flask import Flask, current_app, jsonify, request, send_file

from ...auth import require_account
from ...extensions import db
from ...models import Account
from .storage import safe_blob_path


def photo_type(content: bytes) -> tuple[str, str] | None:
    signatures = (
        (b"\xff\xd8\xff", ".jpg", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n", ".png", "image/png"),
    )
    detected = next(
        (
            (suffix, mimetype)
            for signature, suffix, mimetype in signatures
            if content.startswith(signature)
        ),
        None,
    )
    if detected is None and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp", "image/webp"
    return detected


def register_profile_photo_routes(app: Flask) -> None:
    @app.post("/account/me/profilephoto")
    @require_account
    def upload_profile_photo(account: Account):
        uploaded = next(iter(request.files.values()), None)
        if uploaded is None:
            return jsonify(error="missing photo"), 400
        maximum = current_app.config["PROFILE_PHOTO_MAX_BYTES"]
        content = uploaded.stream.read(maximum + 1)
        if len(content) > maximum:
            return jsonify(error="photo too large", maxBytes=maximum), 413
        detected = photo_type(content)
        if detected is None:
            return jsonify(error="photo must be JPEG, PNG, or WebP"), 400
        suffix, mimetype = detected
        blob_name = f"profile/{account.id}/{uuid.uuid4()}{suffix}"
        destination = safe_blob_path("image", blob_name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        account.profile_image = blob_name
        db.session.commit()
        return jsonify(
            accountId=account.id,
            imageName=blob_name,
            contentType=mimetype,
            url=f"/account/{account.id}/profilephoto",
        )

    @app.get("/account/<int:account_id>/profilephoto")
    def profile_photo(account_id: int):
        account = db.session.get(Account, account_id)
        if account is None or not account.profile_image:
            return "", 404
        candidate = safe_blob_path("image", account.profile_image)
        if candidate is None or not candidate.is_file():
            return "", 404
        response = send_file(candidate, conditional=True)
        response.headers["Cache-Control"] = "public, max-age=300"
        return response
