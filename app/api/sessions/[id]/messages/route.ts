import { apiError, database, ensureSchema, ownerId, publicMessage, type MessageRow } from "@/db/runtime";

type Context = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Context) {
  try {
    const owner = ownerId(request);
    if (!owner) return Response.json({ error: "缺少客户端标识" }, { status: 401 });
    const { id: sessionId } = await params;
    const payload = await request.json() as { role?: "user" | "assistant"; content?: string };
    const content = payload.content?.trim();
    if (!content || !["user", "assistant"].includes(payload.role || "")) return Response.json({ error: "消息格式无效" }, { status: 400 });
    await ensureSchema();
    const db = database();
    const session = await db.prepare("SELECT id FROM sessions WHERE id = ? AND owner_id = ?").bind(sessionId, owner).first();
    if (!session) return Response.json({ error: "会话不存在" }, { status: 404 });
    const id = crypto.randomUUID();
    const now = Date.now();
    await db.batch([
      db.prepare("INSERT INTO messages (id, session_id, owner_id, role, content, token_count, cost, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)").bind(id, sessionId, owner, payload.role, content, null, null, now),
      db.prepare("UPDATE sessions SET updated_at = ? WHERE id = ? AND owner_id = ?").bind(now, sessionId, owner),
    ]);
    const row: MessageRow = { id, session_id: sessionId, role: payload.role!, content, token_count: null, cost: null, created_at: now };
    return Response.json({ message: publicMessage(row) }, { status: 201 });
  } catch (error) { return apiError(error); }
}
