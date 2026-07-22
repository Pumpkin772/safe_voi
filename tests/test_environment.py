from __future__ import annotations

import json
from pathlib import Path

from d5freq.utils.environment import (
    collect_environment_info,
    redact_sensitive,
    write_environment_info,
)


def test_environment_collection_is_allowlisted_and_python_311(
    monkeypatch,
) -> None:
    secrets = {
        "MOSEKLM_LICENSE_FILE": "license-secret-value",
        "GUROBI_KEY": "gurobi-secret-value",
        "EXAMPLE_API_TOKEN": "api-secret-value",
    }
    for name, value in secrets.items():
        monkeypatch.setenv(name, value)

    info = collect_environment_info(package_names=("numpy", "PyYAML"))
    rendered = json.dumps(info, sort_keys=True)

    assert info["python"]["version_info"][:2] == [3, 11]
    assert "numpy" in info["packages"]
    assert info["solvers"]["interface_discovery_only"] is True
    for name, value in secrets.items():
        assert name not in rendered
        assert value not in rendered


def test_recursive_redaction_covers_required_sensitive_key_fragments() -> None:
    unsafe = {
        "solver_license_path": "C:/private/license.lic",
        "api_secret": "secret-value",
        "access_token": "token-value",
        "private_key": "key-value",
        "db_password": "password-value",
        "cloud_credential": "credential-value",
        "safe": {"status": "installed"},
    }

    safe = redact_sensitive(unsafe)

    assert safe["safe"] == {"status": "installed"}
    for key in unsafe.keys() - {"safe"}:
        assert safe[key] == "<redacted>"


def test_write_environment_info_redacts_caller_supplied_metadata(
    tmp_path: Path,
) -> None:
    path = write_environment_info(
        tmp_path / "environment.json",
        {"python": {"version": "3.11"}, "api_key": "never-write-this"},
        extra={"license_status": "do-not-export-license-details"},
    )

    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert "never-write-this" not in text
    assert "do-not-export-license-details" not in text
    assert payload["api_key"] == "<redacted>"
    assert payload["extra"]["license_status"] == "<redacted>"
