from pathlib import Path

from flask import current_app


def upload_root() -> Path:
    path = Path(current_app.instance_path) / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_blob_path(category: str, blob_name: str) -> Path | None:
    relative = Path(blob_name.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        return None
    root = (upload_root() / category).resolve()
    candidate = (root / relative).resolve()
    return candidate if candidate == root or root in candidate.parents else None
