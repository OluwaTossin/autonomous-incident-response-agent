from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.runtime import migrate


def test_verify_image_head_accepts_exact_single_head(monkeypatch: pytest.MonkeyPatch) -> None:
    scripts = SimpleNamespace(get_heads=lambda: ["9e4b7a2c6d10"])
    monkeypatch.setattr(migrate.ScriptDirectory, "from_config", lambda config: scripts)

    migrate._verify_image_head(migrate.Config("alembic.ini"), "9e4b7a2c6d10")


@pytest.mark.parametrize("heads", [[], ["different"], ["9e4b7a2c6d10", "other"]])
def test_verify_image_head_rejects_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    heads: list[str],
) -> None:
    scripts = SimpleNamespace(get_heads=lambda: heads)
    monkeypatch.setattr(migrate.ScriptDirectory, "from_config", lambda config: scripts)

    with pytest.raises(RuntimeError, match="does not match the release manifest"):
        migrate._verify_image_head(migrate.Config("alembic.ini"), "9e4b7a2c6d10")
