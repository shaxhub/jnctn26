const routes = new Set([
  "/mcp",
  "/.well-known/oauth-protected-resource/mcp",
  "/.well-known/oauth-authorization-server",
  "/authorize",
  "/oauth/connect",
  "/token",
]);

export default {
  async fetch(request) {
    const incoming = new URL(request.url);
    if (incoming.hostname !== "agent-dairy-mcp.kienlebox.stream" || !routes.has(incoming.pathname)) {
      return new Response("Not found", { status: 404 });
    }
    const upstream = new URL("https://kienlebox.tail80aa1e.ts.net");
    upstream.pathname = "/agent-dairy" + incoming.pathname;
    upstream.search = incoming.search;
    const headers = new Headers(request.headers);
    headers.delete("Host");
    headers.delete("Cookie");
    return fetch(new Request(upstream, request), { headers, redirect: "manual", cache: "no-store" });
  },
};
