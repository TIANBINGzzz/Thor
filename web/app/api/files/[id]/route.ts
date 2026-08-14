import { apiError, database, ensureSchema, fileBucket, ownerId, type FileRow } from "@/db/runtime";

type Context = { params: Promise<{ id: string }> };

export async function GET(request: Request, { params }: Context) {
  try {
    const owner = ownerId(request);
    if (!owner) return Response.json({ error: "缺少客户端标识" }, { status: 401 });
    const { id } = await params;
    await ensureSchema();
    const file = await database().prepare("SELECT * FROM files WHERE id = ? AND owner_id = ?").bind(id, owner).first<FileRow>();
    if (!file) return Response.json({ error: "文件不存在" }, { status: 404 });
    const object = await fileBucket().get(file.storage_key);
    if (!object) return Response.json({ error: "文件内容不存在" }, { status: 404 });
    const headers = new Headers();
    object.writeHttpMetadata(headers);
    headers.set("Content-Type", file.content_type);
    headers.set("Content-Length", String(file.size));
    headers.set("Content-Disposition", `inline; filename*=UTF-8''${encodeURIComponent(file.name)}`);
    headers.set("Cache-Control", "private, max-age=300");
    headers.set("X-Content-Type-Options", "nosniff");
    return new Response(object.body, { headers });
  } catch (error) { return apiError(error); }
}
