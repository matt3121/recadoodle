"""Run the preserved-client development backend over local HTTPS."""

from rrserver import create_app
from setup_local_certificate import ensure_local_certificate


if __name__ == "__main__":
    certificate, key, _ = ensure_local_certificate()
    app = create_app({
        "RECNET_DOMAIN": "127.0.0.1:5051",
        "SINGLE_HOST_MODE": True,
    })
    print("Local server: https://127.0.0.1:5051", flush=True)
    app.run(
        host="127.0.0.1",
        port=5051,
        threaded=True,
        use_reloader=False,
        ssl_context=(str(certificate), str(key)),
    )
