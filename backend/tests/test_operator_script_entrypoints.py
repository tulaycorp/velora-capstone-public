from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.rotate_provider_credentials import validate_apply_confirmation


BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "script_name",
    [
        "cleanup_orphaned_media.py",
        "prune_ai_generations.py",
        "rotate_provider_credentials.py",
        "scrub_provider_store_metadata.py",
    ],
)
def test_operator_script_supports_documented_direct_invocation(script_name: str) -> None:
    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts" / script_name), "--help"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()


def test_credential_rotation_apply_requires_exact_project_and_key_confirmation() -> None:
    validate_apply_confirmation(
        apply=True,
        confirmed_project_id="project-a",
        confirmed_active_key_id="v2",
        configured_project_id="project-a",
        configured_active_key_id="v2",
    )


@pytest.mark.parametrize(
    ("confirmed_project_id", "confirmed_active_key_id", "configured_project_id"),
    [
        (None, "v2", "project-a"),
        ("project-b", "v2", "project-a"),
        ("project-a", "v1", "project-a"),
        ("project-a", "v2", None),
    ],
)
def test_credential_rotation_apply_rejects_wrong_environment_confirmation(
    confirmed_project_id: str | None,
    confirmed_active_key_id: str | None,
    configured_project_id: str | None,
) -> None:
    with pytest.raises(ValueError):
        validate_apply_confirmation(
            apply=True,
            confirmed_project_id=confirmed_project_id,
            confirmed_active_key_id=confirmed_active_key_id,
            configured_project_id=configured_project_id,
            configured_active_key_id="v2",
        )


def test_credential_rotation_dry_run_does_not_require_apply_confirmation() -> None:
    validate_apply_confirmation(
        apply=False,
        confirmed_project_id=None,
        confirmed_active_key_id=None,
        configured_project_id=None,
        configured_active_key_id="v1",
    )
