const DEFAULT_AGENT_SERVICE_URL = "http://127.0.0.1:4310";

function runtimeValue(name: "AGENT_SERVICE_URL" | "SCRIBE_TOKEN") {
  const value = name === "AGENT_SERVICE_URL"
    ? process.env.AGENT_SERVICE_URL
    : process.env.SCRIBE_TOKEN;
  return value?.trim();
}

function serviceUrl(path: string) {
  const base = runtimeValue("AGENT_SERVICE_URL") || DEFAULT_AGENT_SERVICE_URL;
  return new URL(path, base.endsWith("/") ? base : `${base}/`);
}

export async function proxyAgent(request: Request, path: string) {
  const token = runtimeValue("SCRIBE_TOKEN");
  if (!token) {
    return Response.json({ error: "Agent 服务未启动" }, { status: 503 });
  }

  const incoming = new URL(request.url);
  const target = serviceUrl(path);
  target.search = incoming.search;

  const headers = new Headers(request.headers);
  headers.delete("connection");
  headers.delete("content-length");
  headers.delete("host");
  headers.delete("origin");
  headers.set("x-scribe-token", token);

  try {
    const body = request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer();
    const upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      signal: request.signal,
    });
    const responseHeaders = new Headers(upstream.headers);
    responseHeaders.delete("connection");
    responseHeaders.delete("content-length");
    if (responseHeaders.get("content-type")?.startsWith("text/event-stream")) {
      responseHeaders.set("cache-control", "no-cache, no-transform");
      responseHeaders.set("x-accel-buffering", "no");
    }
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error(error);
    return Response.json({ error: "Agent 服务不可用" }, { status: 503 });
  }
}
