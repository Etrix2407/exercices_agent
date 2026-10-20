"""Tests des outils de l'agent (sans réseau)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from agent_tools import build_tools
from llm_providers.base import ToolError


@pytest.fixture
def tools(tmp_path: Path) -> dict:
    """Dossier candidat factice avec un sous-dossier garant/ et une grille factice."""
    candidate = tmp_path / "candidats" / "jane-doe"
    (candidate / "garant").mkdir(parents=True)
    (candidate / "identite.txt").write_text("Nom : Doe", encoding="utf-8")
    (candidate / "garant" / "identite.txt").write_text("Garant : Smith", encoding="utf-8")
    (candidate / "scan.pdf").write_text("pdf", encoding="utf-8")
    (candidate / ".hidden.txt").write_text("caché", encoding="utf-8")
    (tmp_path / "candidats" / "secret.txt").write_text("secret", encoding="utf-8")
    grid = tmp_path / "grille.json"
    grid.write_text('{"grille_version": "test"}', encoding="utf-8")
    specs = build_tools(candidate, grid, tmp_path / "sorties" / "jane-doe")
    return {spec.name: spec.handler for spec in specs} | {"_root": tmp_path}


def test_exactly_four_tools(tools: dict) -> None:
    assert sorted(k for k in tools if not k.startswith("_")) == ["list_folder", "read_file", "read_grid", "write_file"]


def test_read_grid_returns_raw_text(tools: dict) -> None:
    assert tools["read_grid"]({}) == '{"grille_version": "test"}'


def test_list_folder_includes_garant_posix(tools: dict) -> None:
    assert tools["list_folder"]({}).splitlines() == ["garant/identite.txt", "identite.txt", "scan.pdf"]


def test_read_file_nested_and_logged(tools: dict, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="agent_tools"):
        assert tools["read_file"]({"path": "garant/identite.txt"}) == "Garant : Smith"
    assert "[jane-doe] read_file garant/identite.txt" in caplog.text
    assert "Smith" not in caplog.text


@pytest.mark.parametrize("bad_path", ["../secret.txt", "garant/../../secret.txt", "scan.pdf", "absent.txt"])
def test_read_file_refuses_bad_paths(tools: dict, bad_path: str) -> None:
    with pytest.raises(ToolError):
        tools["read_file"]({"path": bad_path})


def test_read_file_refuses_absolute_path(tools: dict) -> None:
    absolute = tools["_root"] / "candidats" / "jane-doe" / "identite.txt"
    with pytest.raises(ToolError):
        tools["read_file"]({"path": str(absolute.resolve())})


@pytest.mark.parametrize("args", [{}, {"path": 42}, None])
def test_missing_or_wrong_argument(tools: dict, args: object) -> None:
    with pytest.raises(ToolError):
        tools["read_file"](args)


def test_write_file_rules(tools: dict) -> None:
    out_dir = tools["_root"] / "sorties" / "jane-doe"
    for bad_name in ["../evil.txt", "Relance.TXT", "a/b.txt"]:
        with pytest.raises(ToolError):
            tools["write_file"]({"filename": bad_name, "content": "x"})
    with pytest.raises(ToolError):
        tools["write_file"]({"filename": "relance.txt", "content": "   "})
    with pytest.raises(ToolError):
        tools["write_file"]({"filename": "relance.txt"})
    message = tools["write_file"]({"filename": "relance.txt", "content": "Bonjour"})
    assert "relance.txt" in message
    assert (out_dir / "relance.txt").read_text(encoding="utf-8") == "Bonjour"
    assert not (tools["_root"] / "sorties" / "evil.txt").exists()


def test_os_error_becomes_tool_error(tools: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_rglob(self: Path, pattern: str):
        raise PermissionError("accès refusé")

    monkeypatch.setattr(Path, "rglob", failing_rglob)
    with pytest.raises(ToolError, match="accès refusé"):
        tools["list_folder"]({})
