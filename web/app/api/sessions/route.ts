import { proxyAgent } from "@/app/lib/agent-api";

export function GET(request: Request) {
  return proxyAgent(request, "/api/sessions");
}

export function POST(request: Request) {
  return proxyAgent(request, "/api/sessions");
}
