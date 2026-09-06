"""Drive the real MCP server over stdio, the way a host does."""

import json
import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _out(res):
    return res.structured_content or json.loads(res.content[0].text)


@pytest.mark.asyncio
async def test_tools_over_stdio(tmp_path):
    env = {**os.environ, "MNEMOTH_DATA_DIR": str(tmp_path), "MNEMOTH_EMBEDDER": "hash", "MNEMOTH_PROJECT_DIR": str(tmp_path)}
    params = StdioServerParameters(command=sys.executable, args=["-m", "mnemoth.server", "serve"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.server_info.name == "mnemoth" and "never calls a model" in (init.instructions or "")
            tools = {t.name for t in (await session.list_tools()).tools}
            assert tools == {"describe_ontology", "add_entity_type", "remember", "recall", "forget", "list_datasets"}

            onto = await session.call_tool("describe_ontology", {})
            assert any(t["name"] == "Person" for t in _out(onto)["entity_types"])

            rem = await session.call_tool("remember", {
                "entities": [{"name": "Bao", "type": "Person", "description": "Engineer"}, {"name": "auth-service", "type": "System", "description": "Auth"}],
                "relations": [{"source": "Bao", "name": "owns", "target": "auth-service", "description": "Bao owns auth-service.", "evidence": "user said 2026-09-06"}],
            })
            assert not rem.is_error and _out(rem)["relations"][0]["new"] is True

            bad = await session.call_tool("remember", {"entities": [{"name": "X", "type": "Wizard", "description": ""}]})
            assert _out(bad)["error"] == "OntologyError" and "Person" in _out(bad)["message"]

            rec = await session.call_tool("recall", {"query": "who owns auth-service"})
            facts = _out(rec)["facts"]
            assert facts and facts[0]["fact"].startswith("Bao --owns--> auth-service")
