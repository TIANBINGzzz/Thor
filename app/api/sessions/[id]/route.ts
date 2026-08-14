import { apiError, database, ensureSchema, fileBucket, ownerId, publicFile, publicMessage, publicSession, type FileRow, type MessageRow, type SessionRow } from "@/db/runtime";
import { isModelId } from "@/app/lib/models";

type Context = { params: Promise<{ id: string }> };

export async function GET(request: Request, { params }: Context) {
  try {
    const owner = ownerId(request);
    if (!owner) return Response.json({ error: "缺少客户端标识" }, { status: 401 });
    const { id } = await params;
    await ensureSchema();
    const db = database();
    const session = await db.prepare("SELECT * FROM sessions WHERE id = ? AND owner_id = ?").bind(id, owner).first<SessionRow>();
    if (!session) return Response.json({ error: "会话不存在" }, { status: 404 });
    const [messages, files] = await Promise.all([
      db.prepare("SELECT * FROM messages WHERE session_id = ? AND owner_id = ? ORDER BY created_at ASC").bind(id, owner).all<MessageRow>(),
      db.prepare("SELECT * FROM files WHERE session_id = ? AND owner_id = ? ORDER BY created_at ASC").bind(id, owner).all<FileRow>(),
    ]);
    return Response.json({ session: publicSession(session), messages: messages.results.map(publicMessage), files: files.results.map(publicFile) });
  } catch (error) { return apiError(error); }
}

export async function PATCH(request: Request, { params }: Context) {
  try {
    const owner = ownerId(request);
    if (!owner) return Response.json({ error: "缺少客户端标识" }, { status: 401 });
    const { id } = await params;
    const payload = await request.json() as { title?: string; modelId?: string };
    const title = payload.title?.trim().slice(0, 80);
    const modelId = payload.modelId?.trim().slice(0, 40);
    if (!title && !modelId) return Response.json({ error: "没有可更新字段" }, { status: 400 });
    if (modelId && !isModelId(modelId)) return Response.json({ error: "模型未配置" }, { status: 400 });
    await ensureSchema();
    const result = title
      ? await database().prepare("UPDATE sessions SET title = ?, updated_at = ? WHERE id = ? AND owner_id = ?").bind(title, Date.now(), id, owner).run()
      : await database().prepare("UPDATE sessions SET model_id = ?, updated_at = ? WHERE id = ? AND owner_id = ?").bind(modelId, Date.now(), id, owner).run();
    if (!result.meta.changes) return Response.json({ error: "会话不存在" }, { status: 404 });
    return Response.json({ ok: true });
  } catch (error) { return apiError(error); }
}

export async function DELETE(request: Request, { params }: Context) {
  try {
    const owner = ownerId(request);
    if (!owner) return Response.json({ error: "缺少客户端标识" }, { status: 401 });
    const { id } = await params;
    await ensureSchema();
    const db = database();
    const files = await db.prepare("SELECT * FROM files WHERE session_id = ? AND owner_id = ?").bind(id, owner).all<FileRow>();
    const result = await db.prepare("DELETE FROM sessions WHERE id = ? AND owner_id = ?").bind(id, owner).run();
    if (!result.meta.changes) return Response.json({ error: "会话不存在" }, { status: 404 });
    await Promise.all(files.results.map((file) => fileBucket().delete(file.storage_key)));
    return Response.json({ ok: true });
  } catch (error) { return apiError(error); }
}
