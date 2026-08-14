import { apiError, database, ensureSchema, ownerId, publicSession, type SessionRow } from "@/db/runtime";
import { DEFAULT_MODEL_ID, isModelId } from "@/app/lib/models";

export async function GET(request: Request) {
  try {
    const owner = ownerId(request);
    if (!owner) return Response.json({ error: "缺少客户端标识" }, { status: 401 });
    await ensureSchema();
    const result = await database().prepare("SELECT * FROM sessions WHERE owner_id = ? ORDER BY updated_at DESC LIMIT 80").bind(owner).all<SessionRow>();
    return Response.json({ sessions: result.results.map(publicSession) });
  } catch (error) { return apiError(error); }
}

export async function POST(request: Request) {
  try {
    const owner = ownerId(request);
    if (!owner) return Response.json({ error: "缺少客户端标识" }, { status: 401 });
    const payload = await request.json().catch(() => ({})) as { modelId?: string };
    const id = crypto.randomUUID();
    const now = Date.now();
    const requestedModel = payload.modelId?.slice(0, 40) || "";
    const modelId = isModelId(requestedModel) ? requestedModel : DEFAULT_MODEL_ID;
    await ensureSchema();
    await database().prepare("INSERT INTO sessions (id, owner_id, title, model_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)").bind(id, owner, "新对话", modelId, now, now).run();
    return Response.json({ session: { id, title: "新对话", modelId, createdAt: now, updatedAt: now } }, { status: 201 });
  } catch (error) { return apiError(error); }
}
