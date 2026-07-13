"""Open-source hygiene — audit script and required files."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_required_oss_files_exist():
    for name in ("LICENSE", "README.md", "CONTRIBUTING.md", "SECURITY.md", ".env.example", ".gitignore"):
        assert (ROOT / name).exists(), f"missing {name}"


def test_audit_secrets_passes():
    proc = subprocess.run(
        ["bash", "scripts/audit_secrets.sh"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_env_example_has_kite_placeholders_only():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "KITE_API_KEY=" in text
    assert "KITE_API_SECRET=" in text
    assert "gem-bid-automation" not in text
    assert "34.93.102" not in text


def test_production_template_uses_placeholders():
    text = (ROOT / "deploy/bharatquant.env.production").read_text(encoding="utf-8")
    assert "__KITE_API_KEY__" in text
    assert "__BHARATQUANT_PUBLIC_HOST__" in text
    assert "34-93-102" not in text
