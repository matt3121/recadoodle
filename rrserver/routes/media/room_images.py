import base64

from flask import Flask, request, send_file

from ...catalog import ROOM_IMAGE_DIR


def register_room_image_routes(app: Flask) -> None:
    @app.get("/<image_name>.jpg")
    def room_image(image_name: str):
        candidate = ROOM_IMAGE_DIR / f"{image_name}.jpg"
        if not candidate.is_file():
            candidate = ROOM_IMAGE_DIR / "DefaultProfileImage.jpg"
        response = send_file(candidate, mimetype="image/jpeg", conditional=True)
        response.headers["Cache-Control"] = "public, max-age=2592000, immutable"
        if request.args.get("sig") == "p1":
            placeholder = base64.b64encode(bytes(256)).decode("ascii")
            response.headers["Content-Signature"] = f"key-id=KEY:RSA:p1.rec.net; data={placeholder}"
        return response
