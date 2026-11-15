# Verify the local MCP connection

Start the [local gateway](../README.md#run-locally), then configure your AI client using the [MCP setup guide](mcp-connection.md). The default endpoint is `http://127.0.0.1:8000/mcp` over Streamable HTTP.

## Read-only smoke test

1. In **Settings and Tools → Agent integration**, create a read-only key and configure your client to send it as a Bearer token. In the offline demo with `REQUIRE_PORTAL_LOGIN=0`, you can also use the sample `demo-hotel-lookup-key`.
2. Check that the client discovers the `get_my_mandate` and `search_products` tools. Ask it to run `get_my_mandate` and confirm the returned buyer ID matches your workspace. The Hotel kitchen sample key returns `hotel`.
3. Ask the client to search for milk with `search_products`. The offline synthetic catalog includes milk, so a broad search for `maito` should return results.

## Automated coverage

The [MCP transport tests](../app/tests/test_mcp_transport.py) exercise authentication, buyer-scoped credentials, tool discovery, lookup-only permissions, and invalid input. The gateway rejects non-finite and excessive quantities, protects signed quotes from invalid JSON, and validates delivery dates and addresses at the relevant steps. Run `uv run --locked pytest -q` from `app/` to check the full suite.

The shared order service consumes a quote once, rechecks availability, applies buying limits, and records an audit trail. Review cases and address validation are covered by the [portal tests](../app/tests/test_portals.py) and [approval tests](../app/tests/test_aimo_approval.py).
