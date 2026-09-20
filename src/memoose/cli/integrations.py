"""`memoose install <host>`: put the skills, the hooks and the memory-keeper agent into a host.

The CLI is the surface the skills teach, so an install wires no MCP server unless asked
(`--mcp`, for hosts whose agent has no shell). Every host gets a copy of harness/skills; Claude Code
also gets the hooks (registered in its settings) and the memory-keeper agent, which are the two
things only a plugin used to supply. User scope by default so one install works from every
repository. When the memoose plugin is installed, hooks and agent are skipped: the plugin already
provides them, and two registrations would inject every hint twice.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

SERVER_NAME = "memoose"
_PACKAGE = Path(__file__).resolve().parents[1]  # the memoose package directory
# The wheel carries a copy of harness/ (skills, hooks, agents) inside the package; a source checkout has it at the repo root.
HARNESS_ROOT = _PACKAGE / "harness" if (_PACKAGE / "harness").exists() else _PACKAGE.parents[1] / "harness"
SKILLS_ROOT, HOOKS_ROOT, AGENTS_ROOT = HARNESS_ROOT / "skills", HARNESS_ROOT / "hooks", HARNESS_ROOT / "agents"
HOOK_MARK = "/memoose/hooks/"  # every hook command we register contains this; uninstall matches on it


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
    root = Path(__file__).resolve().parents[3]
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


def _copy_tree(src_dir: Path, dst_dir: Path) -> None:
    for src in src_dir.rglob("*"):
        if src.is_file() and "__pycache__" not in src.parts:
            dst = dst_dir / src.relative_to(src_dir)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def _claude_dir(project: str | None) -> Path:
    return (Path.home() if project is None else Path(project).resolve()) / ".claude"


def install(host: str, project: str | None = None, command: list[str] | None = None, mcp: bool = False) -> dict:
    t, skill_dir, mcp_path, kind = _paths(host, project)
    installed = []
    for skill_src in sorted(p for p in SKILLS_ROOT.iterdir() if (p / "SKILL.md").exists()):
        dst_dir = skill_dir.parent / skill_src.name
        _copy_tree(skill_src, dst_dir)
        installed.append(str(dst_dir))
    out: dict = {"host": t.display, "scope": "project" if project else "user", "skills": installed, "cli": cli_command()}
    if mcp:
        command = command or default_command()
        _write_mcp(kind, mcp_path, command)
        out.update({"mcp_config": str(mcp_path), "command": command})
    else:
        _remove_mcp(kind, mcp_path)
    if host == "claude":
        if plugin_install():
            out["note"] = "the memoose plugin is installed and already supplies the hooks and the memory-keeper agent; not registered twice"
        else:
            out.update(_install_claude_hooks_and_agent(_claude_dir(project), with_mcp=mcp))
    else:
        out["note"] = f"{t.display} has no hook or subagent surface memoose can wire; the skills teach the CLI"
    return out


def _install_claude_hooks_and_agent(claude_dir: Path, with_mcp: bool) -> dict:
    """Copy harness/hooks beside the settings, register them there, and drop the agent in agents/."""
    hooks_dir = claude_dir / "memoose" / "hooks"
    _copy_tree(HOOKS_ROOT, hooks_dir)
    spec = json.loads((HOOKS_ROOT / "hooks.json").read_text())["hooks"]
    settings_path = claude_dir / "settings.json"
    settings = _read_json(settings_path) or {}
    hooks = settings.setdefault("hooks", {})
    for event, groups in spec.items():
        existing = hooks.setdefault(event, [])
        existing[:] = [g for g in existing if not _is_ours(g)]
        for g in groups:
            for h in g.get("hooks", []):
                h["command"] = h["command"].replace("${CLAUDE_PLUGIN_ROOT}/harness/hooks", str(hooks_dir))
            existing.append(g)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    agents_dir = claude_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agents = []
    for src in AGENTS_ROOT.glob("*.md"):
        text = src.read_text()
        # Without the server the keeper works through the CLI, so it needs a shell and nothing else.
        text = re.sub(r"^tools: .*$", lambda m: m.group(0).replace("tools: ", "tools: Bash, ") if with_mcp else "tools: Bash", text, count=1, flags=re.M)
        (agents_dir / src.name).write_text(text)
        agents.append(str(agents_dir / src.name))
    return {"hooks": str(hooks_dir), "settings": str(settings_path), "agents": agents}


def _is_ours(group: dict) -> bool:
    return any(HOOK_MARK in h.get("command", "") for h in group.get("hooks", []))


def _remove_claude_hooks_and_agent(claude_dir: Path) -> bool:
    removed = False
    settings_path = claude_dir / "settings.json"
    settings = _read_json(settings_path)
    if settings and "hooks" in settings:
        for event, groups in list(settings["hooks"].items()):
            kept = [g for g in groups if not _is_ours(g)]
            removed |= len(kept) != len(groups)
            if kept:
                settings["hooks"][event] = kept
            else:
                del settings["hooks"][event]
        if not settings["hooks"]:
            del settings["hooks"]
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    hooks_dir = claude_dir / "memoose"
    if hooks_dir.exists():
        shutil.rmtree(hooks_dir, ignore_errors=True)
        removed = True
    for src in AGENTS_ROOT.glob("*.md"):
        agent = claude_dir / "agents" / src.name
        if agent.exists():
            agent.unlink()
            removed = True
    return removed


def uninstall(host: str, project: str | None = None) -> dict:
    t, skill_dir, mcp_path, kind = _paths(host, project)
    removed_skill = skill_dir.exists()
    for skill_src in SKILLS_ROOT.iterdir():
        if (skill_src / "SKILL.md").exists():
            shutil.rmtree(skill_dir.parent / skill_src.name, ignore_errors=True)
    removed_mcp = _remove_mcp(kind, mcp_path)
    out = {"host": t.display, "skill_removed": removed_skill, "mcp_removed": removed_mcp}
    if host == "claude":
        out["hooks_removed"] = _remove_claude_hooks_and_agent(_claude_dir(project))
    return out


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
        if host == "claude":
            claude_dir = _claude_dir(project)
            settings = _read_json(claude_dir / "settings.json") or {}
            out[host]["hooks"] = any(_is_ours(g) for groups in settings.get("hooks", {}).values() for g in groups)
            out[host]["agent"] = any((claude_dir / "agents" / a.name).exists() for a in AGENTS_ROOT.glob("*.md"))
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
