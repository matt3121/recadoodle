from flask import Flask

from .blobs import register_blob_routes
from .profile_photos import register_profile_photo_routes
from .room_images import register_room_image_routes


def register_media_routes(app: Flask) -> None:
    register_blob_routes(app)
    register_profile_photo_routes(app)
    register_room_image_routes(app)
