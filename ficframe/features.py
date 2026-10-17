"""Internal release switches; retained features stay dormant until enabled here."""

COMPOSITION_REFERENCES_ENABLED = False


def visual_preset_kinds() -> tuple[str, ...]:
    return ("style", "composition") if COMPOSITION_REFERENCES_ENABLED else ("style",)
