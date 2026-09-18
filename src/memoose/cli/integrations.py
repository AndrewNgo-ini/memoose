"""`memoose install <host>`: wire the MCP server and the skill into a host.

Modelled on OpenWiki's integration installer. Each host gets exactly two things,
both in its own conventions: an MCP server entry and a copy of skills/memoose.
User scope by default so one install works from every repository.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

SERVER_NAME = "memoose"
LEGACY_SERVER_NAME = "mnemoth"  # pre-rename installs, cleared on the next install
SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"


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
    "claude": HostTarget("claude", "Claude Code", ".claude/skills/memoose", ".claude.json", "json", ".claude/skills/memoose", ".mcp.json", "json"),
    "codex": HostTarget("codex", "Codex", ".agents/skills/memoose", ".codex/config.toml", "codex-toml", ".agents/skills/memoose", ".codex/config.toml", "codex-toml"),
    "opencode": HostTarget("opencode", "OpenCode", ".config/opencode/skills/memoose", ".config/opencode/opencode.jsonc", "opencode-json", ".opencode/skills/memoose", "opencode.jsonc", "opencode-json"),
    "cursor": HostTarget("cursor", "Cursor", ".cursor/skills/memoose", ".cursor/mcp.json", "json", ".cursor/skills/memoose", ".cursor/mcp.json", "json"),
}


def default_command() -> list[str]:
    """`uvx memoose serve` once published; from a source checkout, point uvx at the checkout."""
    root = Path(__file__).resolve().parents[2]
    if (root / "pyproject.toml").exists() and (root / "src" / "memoose").exists():
        return ["uvx", "--from", str(root), "memoose", "serve"]
    return ["uvx", "memoose", "serve"]


def cli_command() -> str:
    """How to invoke the CLI on this machine: the installed binary if it is on PATH, else uvx."""
    found = shutil.which("memoose")
    if found:
        return "memoose"
    return " ".join(default_command()[:-1])  # the server command without `serve`


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
    installed = []
    for skill_src in sorted(p for p in SKILLS_ROOT.iterdir() if (p / "SKILL.md").exists()):
        dst_dir = skill_dir.parent / skill_src.name
        dst_dir.mkdir(parents=True, exist_ok=True)
        for src in skill_src.rglob("*"):
            if src.is_file():
                dst = dst_dir / src.relative_to(skill_src)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        installed.append(str(dst_dir))
    _clear_legacy(kind, mcp_path, skill_dir.parent)
    _write_mcp(kind, mcp_path, command)
    return {"host": t.display, "scope": "project" if project else "user", "skills": installed, "mcp_config": str(mcp_path), "command": command, "cli": cli_command()}


def _clear_legacy(kind: str, mcp_path: Path, skills_parent: Path) -> None:
    """Drop a pre-rename install so the host does not end up running two memory servers.

    Only the host's own config entry and its copy of the skills go; stored memory is never
    touched, and `datasets.data_dir` keeps reading it where it already lives.
    """
    _remove_mcp(kind, mcp_path, LEGACY_SERVER_NAME)
    for legacy in skills_parent.glob(f"{LEGACY_SERVER_NAME}*"):
        shutil.rmtree(legacy, ignore_errors=True)


def uninstall(host: str, project: str | None = None) -> dict:
    t, skill_dir, mcp_path, kind = _paths(host, project)
    removed_skill = skill_dir.exists()
    for skill_src in SKILLS_ROOT.iterdir():
        if (skill_src / "SKILL.md").exists():
            shutil.rmtree(skill_dir.parent / skill_src.name, ignore_errors=True)
    _clear_legacy(kind, mcp_path, skill_dir.parent)
    removed_mcp = _remove_mcp(kind, mcp_path)
    return {"host": t.display, "skill_removed": removed_skill, "mcp_removed": removed_mcp}


def plugin_install() -> dict | None:
    """The Claude Code plugin install of memoose, if there is one; it supplies skills, MCP and hooks."""
    rec = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(rec.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    plugins = data.get("plugins", data) if isinstance(data, dict) else {}
    for key, entries in plugins.items():
        if key.startswith("memoose@") and entries:
            e = entries[0] if isinstance(entries, list) else entries
            return {"id": key, "version": e.get("version"), "path": e.get("installPath"), "scope": e.get("scope")}
    return None


def status(project: str | None = None) -> dict:
    out: dict = {"cli": cli_command(), "claude_plugin": plugin_install()}
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


def _remove_mcp(kind: str, path: Path, name: str = SERVER_NAME) -> bool:
    if not path.exists():
        return False
    if kind in ("json", "opencode-json"):
        data = _read_json(path) or {}
        key = "mcpServers" if kind == "json" else "mcp"
        servers = data.get(key, {})
        if name not in servers:
            return False
        del servers[name]
        path.write_text(json.dumps(data, indent=2) + "\n")
        return True
    text = path.read_text()
    new = _strip_toml_block(text, name)
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


def _strip_toml_block(text: str, name: str = SERVER_NAME) -> str:
    return re.sub(rf"^\[mcp_servers\.{re.escape(name)}\]\s*$.*?(?=^\[|\Z)", "", text, flags=re.M | re.S)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    raw = path.read_text()
    # opencode uses JSONC; strip // and /* */ comments conservatively.
    raw = re.sub(r"(?m)^\s*//.*$", "", raw)
    raw = re.sub(r"/\*.*?\*/", "", raw, flags=re.S)
    raw = raw.strip()
    return json.loads(raw) if raw else {}
