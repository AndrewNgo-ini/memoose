"""`mnemoth install <host>`: wire the MCP server and the skill into a host.

Modelled on OpenWiki's integration installer. Each host gets exactly two things,
both in its own conventions: an MCP server entry and a copy of skills/mnemoth.
User scope by default so one install works from every repository.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

SERVER_NAME = "mnemoth"
SKILL_SRC = Path(__file__).resolve().parents[2] / "skills" / "mnemoth"


@dataclass(frozen=True)
class HostTarget:
    id: str
    display: str
    user_skill_dir: str
    user_mcp: str
    user_kind: str
    project_skill_dir: str
    project_mcp: str
    project_kind: str


HOSTS: dict[str, HostTarget] = {
    "claude": HostTarget("claude", "Claude Code", ".claude/skills/mnemoth", ".claude.json", "json", ".claude/skills/mnemoth", ".mcp.json", "json"),
    "codex": HostTarget("codex", "Codex", ".agents/skills/mnemoth", ".codex/config.toml", "codex-toml", ".agents/skills/mnemoth", ".codex/config.toml", "codex-toml"),
    "opencode": HostTarget("opencode", "OpenCode", ".config/opencode/skills/mnemoth", ".config/opencode/opencode.jsonc", "opencode-json", ".opencode/skills/mnemoth", "opencode.jsonc", "opencode-json"),
    "cursor": HostTarget("cursor", "Cursor", ".cursor/skills/mnemoth", ".cursor/mcp.json", "json", ".cursor/skills/mnemoth", ".cursor/mcp.json", "json"),
}


def default_command() -> list[str]:
    """`uvx mnemoth serve` once published; from a source checkout, point uvx at the checkout."""
    root = Path(__file__).resolve().parents[2]
    if (root / "pyproject.toml").exists() and (root / "src" / "mnemoth").exists():
        return ["uvx", "--from", str(root), "mnemoth", "serve"]
    return ["uvx", "mnemoth", "serve"]


def _paths(host: str, project: str | None) -> tuple[HostTarget, Path, Path, str]:
    t = HOSTS[host]
    if project is None:
        root = Path.home()
        return t, root / t.user_skill_dir, root / t.user_mcp, t.user_kind
    root = Path(project).resolve()
    return t, root / t.project_skill_dir, root / t.project_mcp, t.project_kind


def install(host: str, project: str | None = None, command: list[str] | None = None) -> dict:
    t, skill_dir, mcp_path, kind = _paths(host, project)
    command = command or default_command()
    skill_dir.mkdir(parents=True, exist_ok=True)
    for src in SKILL_SRC.rglob("*"):
        if src.is_file():
            dst = skill_dir / src.relative_to(SKILL_SRC)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    _write_mcp(kind, mcp_path, command)
    return {"host": t.display, "scope": "project" if project else "user", "skill": str(skill_dir), "mcp_config": str(mcp_path), "command": command}


def uninstall(host: str, project: str | None = None) -> dict:
    t, skill_dir, mcp_path, kind = _paths(host, project)
    removed_skill = skill_dir.exists()
    shutil.rmtree(skill_dir, ignore_errors=True)
    removed_mcp = _remove_mcp(kind, mcp_path)
    return {"host": t.display, "skill_removed": removed_skill, "mcp_removed": removed_mcp}


def status(project: str | None = None) -> dict:
    out = {}
    for host in HOSTS:
        t, skill_dir, mcp_path, kind = _paths(host, project)
        out[host] = {"skill": skill_dir.exists(), "mcp": _has_mcp(kind, mcp_path), "mcp_config": str(mcp_path)}
    return out


# ----- config writers ---------------------------------------------------------
def _write_mcp(kind: str, path: Path, command: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if kind == "json":
        data = _read_json(path) or {}
        servers = data.setdefault("mcpServers", {})
        servers[SERVER_NAME] = {"command": command[0], "args": command[1:]}
        path.write_text(json.dumps(data, indent=2) + "\n")
    elif kind == "opencode-json":
        data = _read_json(path) or {"$schema": "https://opencode.ai/config.json"}
        mcp = data.setdefault("mcp", {})
        mcp[SERVER_NAME] = {"type": "local", "command": command, "enabled": True}
        path.write_text(json.dumps(data, indent=2) + "\n")
    elif kind == "codex-toml":
        text = path.read_text() if path.exists() else ""
        text = _strip_toml_block(text)
        block = f"\n[mcp_servers.{SERVER_NAME}]\ncommand = {json.dumps(command[0])}\nargs = [{', '.join(json.dumps(a) for a in command[1:])}]\n"
        path.write_text(text.rstrip("\n") + "\n" + block if text.strip() else block.lstrip("\n"))
    else:
        raise ValueError(kind)


def _remove_mcp(kind: str, path: Path) -> bool:
    if not path.exists():
        return False
    if kind in ("json", "opencode-json"):
        data = _read_json(path) or {}
        key = "mcpServers" if kind == "json" else "mcp"
        servers = data.get(key, {})
        if SERVER_NAME not in servers:
            return False
        del servers[SERVER_NAME]
        path.write_text(json.dumps(data, indent=2) + "\n")
        return True
    text = path.read_text()
    new = _strip_toml_block(text)
    if new == text:
        return False
    path.write_text(new)
    return True


def _has_mcp(kind: str, path: Path) -> bool:
    if not path.exists():
        return False
    if kind in ("json", "opencode-json"):
        data = _read_json(path) or {}
        return SERVER_NAME in data.get("mcpServers" if kind == "json" else "mcp", {})
    return f"[mcp_servers.{SERVER_NAME}]" in path.read_text()


_TOML_BLOCK = re.compile(rf"^\[mcp_servers\.{SERVER_NAME}\]\s*$.*?(?=^\[|\Z)", re.M | re.S)


def _strip_toml_block(text: str) -> str:
    return _TOML_BLOCK.sub("", text)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    raw = path.read_text()
    # opencode uses JSONC; strip // and /* */ comments conservatively.
    raw = re.sub(r"(?m)^\s*//.*$", "", raw)
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    raw = raw.strip()
    return json.loads(raw) if raw else {}
