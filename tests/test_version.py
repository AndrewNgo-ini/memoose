"""One version number, four files. A tag ships whatever these say, so they must agree."""

import json
import tomllib
from pathlib import Path

import memoose

ROOT = Path(__file__).resolve().parent.parent


def test_versions_agree():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    plugin = json.loads((ROOT / "plugin.json").read_text())["version"]
    claude_plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())["plugins"][0]["version"]
    assert pyproject == plugin == claude_plugin == marketplace == memoose.__version__
