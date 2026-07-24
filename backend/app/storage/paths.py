from __future__ import annotations

from pathlib import Path


ORGANIZATIONS_PREFIX = "organizations"


def _normalized_extension(file_name: str | None) -> str:
    return Path(file_name or "").suffix.lower()


def build_design_asset_storage_key(
    *,
    organization_id: str,
    design_asset_id: str,
    file_name: str | None,
) -> str:
    extension = _normalized_extension(file_name)
    return f"{ORGANIZATIONS_PREFIX}/{organization_id}/design-assets/{design_asset_id}/source{extension}"


def build_mockup_storage_key(
    *,
    organization_id: str,
    draft_id: str,
    mockup_id: str,
    file_name: str | None,
) -> str:
    extension = _normalized_extension(file_name)
    return (
        f"{ORGANIZATIONS_PREFIX}/{organization_id}/draft-mockups/{draft_id}/{mockup_id}/source{extension}"
    )
