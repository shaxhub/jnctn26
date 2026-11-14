"""MCP smoke test against a running server: initialize, tools/list, one tool call.

    uv run uvicorn gateway.api:app --port 8000 &
    uv run python scripts/mcp_smoke.py [--url http://127.0.0.1:8000/mcp] [--key demo-hotel-key]
"""
from __future__ import annotations

import argparse
import asyncio
import json

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def main(url: str, key: str) -> None:
    async with httpx2.AsyncClient(headers={"X-API-Key": key}, timeout=60) as http:
        # mode="legacy" forces the classic initialize handshake
        async with Client(streamable_http_client(url, http_client=http), mode="legacy") as client:
            print("initialize: OK, server =", client.session.server_info if hasattr(client, "session") else "?")
            tools = await client.list_tools()
            print(f"tools/list: {len(tools.tools)} tools")
            for t in tools.tools:
                print(f"  - {t.name}: {(t.description or '').splitlines()[0]}")
            me_res = await client.call_tool("get_my_mandate", {})
            if me_res.is_error:
                msg = me_res.content[0].text if me_res.content else "unknown tool error"
                raise SystemExit(f"MCP tool error (get_my_mandate): {msg}")
            me_data = me_res.structured_content or json.loads(me_res.content[0].text)
            print("tools/call get_my_mandate:", me_data["buyer_id"], me_data["mandate"]["mandate_id"])
            res = await client.call_tool("search_products", {"text": "maito", "free_from": ["FREE_FROM_LACTOSE"],
                                                             "category": "10400", "limit": 3})
            if res.is_error:
                msg = res.content[0].text if res.content else "unknown tool error"
                raise SystemExit(f"MCP tool error (search_products): {msg}")
            data = res.structured_content or json.loads(res.content[0].text)
            print("tools/call search_products:", data["total_matches"], "matches; first:",
                  [f"{r['id']} {r['name_fi']}" for r in data["results"]])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    ap.add_argument("--key", default="demo-hotel-key")
    a = ap.parse_args()
    asyncio.run(main(a.url, a.key))
