import { proxyAgent } from "@/app/lib/agent-api";

type Context = { params: Promise<{ id: string }> };

async function path(context: Context) {
  return `/api/sessions/${encodeURIComponent((await context.params).id)}`;
}

export async function GET(request: Request, context: Context) {
  return proxyAgent(request, await path(context));
}

export async function PATCH(request: Request, context: Context) {
  return proxyAgent(request, await path(context));
}

export async function DELETE(request: Request, context: Context) {
  return proxyAgent(request, await path(context));
}
