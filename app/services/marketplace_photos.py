"""Listing photos: a few pictures per listing, stored with the operator's other files."""
from __future__ import annotations

import io

from flask import current_app

from ..extensions import db
from ..models import MarketplaceListing, MarketplaceListingPhoto
from .marketplace import MarketplaceError

TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
MAX_PHOTOS = 6
MAX_BYTES = 3 * 1024 * 1024


def _looks_like(ext: str, head: bytes) -> bool:
    if ext in ("jpg", "jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if ext == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


def add_photo(listing: MarketplaceListing, file_storage) -> MarketplaceListingPhoto:
    from .storage import storage_service
    count = MarketplaceListingPhoto.query.filter_by(listing_id=listing.id).count()
    if count >= MAX_PHOTOS:
        raise MarketplaceError(f"A listing can have up to {MAX_PHOTOS} photos.")
    name = (getattr(file_storage, "filename", "") or "").strip()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in TYPES:
        raise MarketplaceError("Photos must be JPG, PNG or WebP.")
    data = file_storage.stream.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise MarketplaceError("Each photo must be under 3 MB.")
    if not _looks_like(ext, data[:16]):
        raise MarketplaceError("That file doesn't look like a valid image.")
    stored = storage_service.upload(namespace=f"operators/{listing.operator_id}/marketplace-photos",
                                    filename=f"photo.{ext}", stream=io.BytesIO(data), content_type=TYPES[ext],
                                    scope="operator")
    photo = MarketplaceListingPhoto(operator_id=listing.operator_id, listing_id=listing.id, storage_key=stored.key,
                                    content_type=TYPES[ext], sort_order=count)
    db.session.add(photo)
    db.session.commit()
    return photo


def delete_photo(photo: MarketplaceListingPhoto) -> None:
    from .storage import storage_service
    try:
        storage_service.delete(photo.storage_key, scope="operator")
    except Exception:  # noqa: BLE001 - a missing file must not block removing the row
        current_app.logger.warning("Could not delete marketplace photo %s", photo.storage_key)
    db.session.delete(photo)
    db.session.commit()
