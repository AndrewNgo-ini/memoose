import json

from memoose.cli import integrations


def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(integrations.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(integrations, "plugin_install", lambda: None)  # no plugin on this fake machine


def test_install_puts_skills_everywhere_and_hooks_plus_agent_into_claude(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"theme": "dark", "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo other"}]}]}}))
    (tmp_path / ".claude.json").write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))

    for host in integrations.HOSTS:
        res = integrations.install(host)
        assert (tmp_path / integrations.HOSTS[host].user_skill_dir / "SKILL.md").exists(), host
        assert "mcp_config" not in res, "no server unless asked"
        assert integrations.status()[host]["mcp"] is False, host

    st = integrations.status()["claude"]
    assert st["hooks"] and st["agent"]
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert settings["theme"] == "dark"
    commands = [h["command"] for groups in settings["hooks"].values() for g in groups for h in g["hooks"]]
    assert "echo other" in commands, "someone else's hook survives"
    ours = [c for c in commands if integrations.HOOK_MARK in c]
    assert len(ours) == 9 and all("${CLAUDE_PLUGIN_ROOT}" not in c for c in ours)
    assert (tmp_path / ".claude" / "memoose" / "hooks" / "recommend.py").exists()
    agent = (tmp_path / ".claude" / "agents" / "memory-keeper.md").read_text()
    assert "\ntools: Bash\n" in agent, "without the server the keeper works through the CLI"
    assert set(json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]) == {"other"}

    # a second install does not double-register
    integrations.install("claude")
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert sum(integrations.HOOK_MARK in h["command"] for groups in settings["hooks"].values() for g in groups for h in g["hooks"]) == 9

    for host in integrations.HOSTS:
        res = integrations.uninstall(host)
        assert res["skill_removed"], host
    assert integrations.uninstall("claude")["hooks_removed"] is False, "already gone"
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert settings["hooks"] == {"SessionStart": [{"hooks": [{"type": "command", "command": "echo other"}]}]}
    assert not (tmp_path / ".claude" / "agents" / "memory-keeper.md").exists()
    assert integrations.status()["claude"] == {"skill": False, "mcp": False, "mcp_config": str(tmp_path / ".claude.json"), "hooks": False, "agent": False}


def test_mcp_is_opt_in_and_written_in_each_hosts_dialect(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text('model = "gpt-5"\n\n[mcp_servers.other]\ncommand = "x"\nargs = []\n')
    (tmp_path / ".claude.json").write_text(json.dumps({"theme": "dark", "mcpServers": {"other": {"command": "x"}}}))

    for host in integrations.HOSTS:
        res = integrations.install(host, command=["uvx", "memoose", "serve"], mcp=True)
        assert integrations.status()[host]["mcp"] is True and res["mcp_config"], host
    toml = (tmp_path / ".codex" / "config.toml").read_text()
    assert 'model = "gpt-5"' in toml and "[mcp_servers.other]" in toml and "[mcp_servers.memoose]" in toml
    claude = json.loads((tmp_path / ".claude.json").read_text())
    assert claude["theme"] == "dark" and set(claude["mcpServers"]) == {"other", "memoose"}
    oc = json.loads((tmp_path / ".config/opencode/opencode.jsonc").read_text())
    assert oc["mcp"]["memoose"] == {"type": "local", "command": ["uvx", "memoose", "serve"], "enabled": True}
    agent = (tmp_path / ".claude" / "agents" / "memory-keeper.md").read_text()
    assert "\ntools: Bash, mcp__memoose__describe_ontology" in agent

    for host in integrations.HOSTS:
        assert integrations.uninstall(host)["mcp_removed"], host
    toml = (tmp_path / ".codex" / "config.toml").read_text()
    assert "[mcp_servers.other]" in toml and "memoose" not in toml
    assert set(json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]) == {"other"}


def test_install_skips_hooks_and_agent_when_the_plugin_is_installed(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    monkeypatch.setattr(integrations, "plugin_install", lambda: {"id": "memoose@memoose", "version": "0.4.0"})
    res = integrations.install("claude")
    assert "not registered twice" in res["note"]
    assert not (tmp_path / ".claude" / "settings.json").exists()
    assert not (tmp_path / ".claude" / "agents").exists()
    assert (tmp_path / ".claude" / "skills" / "memoose" / "SKILL.md").exists()
