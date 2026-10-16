"""Shared resolution aliases for image providers and local workflows."""


def normalize_image_size(size: str) -> str:
    value = size.strip()
    return {"1K": "1024x1024", "2K": "2048x2048", "4K": "2880x2880"}.get(value.upper(), value)
