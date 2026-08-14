import { apiError, database, ensureSchema, fileBucket, ownerId, publicFile, type FileRow } from "@/db/runtime";

const MAX_FILE_SIZE = 10 * 1024 * 1024;
type Context = { params: Promise<{ id: string }> };

export async function POST(request: Request, { params }: Context) {
  try {
    const owner = ownerId(request);
    if (!owner) return Response.json({ error: "缺少客户端标识" }, { status: 401 });
    const { id: sessionId } = await params;
    await ensureSchema();
    const db = database();
    const session = await db.prepare("SELECT id FROM sessions WHERE id = ? AND owner_id = ?").bind(sessionId, owner).first();
    if (!session) return Response.json({ error: "会话不存在" }, { status: 404 });
    const form = await request.formData();
    const upload = form.get("file");
    if (!(upload instanceof File)) return Response.json({ error: "请选择文件" }, { status: 400 });
    if (upload.size > MAX_FILE_SIZE) return Response.json({ error: "单个文件不能超过 10 MB" }, { status: 413 });
    const id = crypto.randomUUID();
    const now = Date.now();
    const storageKey = `${owner.replace(/[^a-zA-Z0-9_-]/g, "_")}/${sessionId}/${id}`;
    const contentType = upload.type || "application/octet-stream";
    await fileBucket().put(storageKey, upload.stream(), { httpMetadata: { contentType }, customMetadata: { originalName: upload.name } });
    await db.batch([
      db.prepare("INSERT INTO files (id, session_id, owner_id, name, content_type, size, storage_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)").bind(id, sessionId, owner, upload.name.slice(0, 240), contentType, upload.size, storageKey, now),
      db.prepare("UPDATE sessions SET updated_at = ? WHERE id = ? AND owner_id = ?").bind(now, sessionId, owner),
    ]);
    const row: FileRow = { id, session_id: sessionId, name: upload.name, content_type: contentType, size: upload.size, storage_key: storageKey, created_at: now };
    return Response.json({ file: publicFile(row) }, { status: 201 });
  } catch (error) { return apiError(error); }
}
