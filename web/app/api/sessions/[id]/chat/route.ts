import { proxyAgent } from "@/app/lib/agent-api";

type Context = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Context) {
  const { id } = await params;
  return proxyAgent(request, `/api/sessions/${encodeURIComponent(id)}/chat`);
}
