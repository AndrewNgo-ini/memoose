import json

from memoose import integrations


def test_install_and_uninstall_every_host(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(integrations.Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text('model = "gpt-5"\n\n[mcp_servers.other]\ncommand = "x"\nargs = []\n')
    (tmp_path / ".claude.json").write_text(json.dumps({"theme": "dark", "mcpServers": {"other": {"command": "x"}}}))

    for host in integrations.HOSTS:
        res = integrations.install(host, command=["uvx", "memoose", "serve"])
        assert (tmp_path / integrations.HOSTS[host].user_skill_dir / "SKILL.md").exists(), host
        assert integrations.status()[host] == {"skill": True, "mcp": True, "mcp_config": res["mcp_config"]}

    toml = (tmp_path / ".codex" / "config.toml").read_text()
    assert 'model = "gpt-5"' in toml and "[mcp_servers.other]" in toml and "[mcp_servers.memoose]" in toml
    claude = json.loads((tmp_path / ".claude.json").read_text())
    assert claude["theme"] == "dark" and set(claude["mcpServers"]) == {"other", "memoose"}
    oc = json.loads((tmp_path / ".config/opencode/opencode.jsonc").read_text())
    assert oc["mcp"]["memoose"] == {"type": "local", "command": ["uvx", "memoose", "serve"], "enabled": True}

    for host in integrations.HOSTS:
        res = integrations.uninstall(host)
        assert res["skill_removed"] and res["mcp_removed"], host
        assert integrations.status()[host]["mcp"] is False
    toml = (tmp_path / ".codex" / "config.toml").read_text()
    assert "[mcp_servers.other]" in toml and "memoose" not in toml
    assert set(json.loads((tmp_path / ".claude.json").read_text())["mcpServers"]) == {"other"}


def test_install_clears_a_pre_rename_install(tmp_path, monkeypatch):
    """Upgrading must not leave the old mnemoth server wired in beside memoose."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(integrations.Path, "home", classmethod(lambda cls: tmp_path))
    claude = tmp_path / ".claude.json"
    claude.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}, "mnemoth": {"command": "uvx"}}}))
    old_skill = tmp_path / ".claude/skills/mnemoth-onboard"
    old_skill.mkdir(parents=True)
    (old_skill / "SKILL.md").write_text("old")

    integrations.install("claude", command=["uvx", "memoose", "serve"])
    assert set(json.loads(claude.read_text())["mcpServers"]) == {"other", "memoose"}
    assert not old_skill.exists()
    assert (tmp_path / ".claude/skills/memoose-onboard/SKILL.md").exists()
