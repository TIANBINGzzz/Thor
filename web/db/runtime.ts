import { env } from "cloudflare:workers";

export type SessionRow = {
  id: string;
  owner_id: string;
  title: string;
  model_id: string;
  created_at: number;
  updated_at: number;
};

export type MessageRow = {
  id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  token_count: number | null;
  cost: number | null;
  created_at: number;
};

export type FileRow = {
  id: string;
  session_id: string;
  name: string;
  content_type: string;
  size: number;
  storage_key: string;
  created_at: number;
};

export function database() {
  if (!env.DB) throw new Error("D1 binding DB is unavailable");
  return env.DB;
}

export function fileBucket() {
  if (!env.FILES) throw new Error("R2 binding FILES is unavailable");
  return env.FILES;
}

let schemaReady: Promise<void> | null = null;

export function ensureSchema() {
  if (schemaReady) return schemaReady;
  const db = database();
  schemaReady = db.batch([
    db.prepare(`CREATE TABLE IF NOT EXISTS sessions (
      id TEXT PRIMARY KEY NOT NULL,
      owner_id TEXT NOT NULL,
      title TEXT NOT NULL DEFAULT '新对话',
      model_id TEXT NOT NULL DEFAULT 'deepseek-v4-flash',
      created_at INTEGER NOT NULL,
      updated_at INTEGER NOT NULL
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_sessions_owner_updated ON sessions(owner_id, updated_at)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS messages (
      id TEXT PRIMARY KEY NOT NULL,
      session_id TEXT NOT NULL,
      owner_id TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('user','assistant')),
      content TEXT NOT NULL,
      token_count INTEGER,
      cost REAL,
      created_at INTEGER NOT NULL,
      FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_messages_session_created ON messages(session_id, created_at)"),
    db.prepare(`CREATE TABLE IF NOT EXISTS files (
      id TEXT PRIMARY KEY NOT NULL,
      session_id TEXT NOT NULL,
      owner_id TEXT NOT NULL,
      name TEXT NOT NULL,
      content_type TEXT NOT NULL,
      size INTEGER NOT NULL,
      storage_key TEXT NOT NULL UNIQUE,
      created_at INTEGER NOT NULL,
      FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
    )`),
    db.prepare("CREATE INDEX IF NOT EXISTS idx_files_session_created ON files(session_id, created_at)"),
    db.prepare("UPDATE sessions SET model_id = 'deepseek-v4-flash' WHERE model_id IN ('qwen-plus', 'deepseek-v4')"),
    db.prepare("UPDATE sessions SET model_id = 'qwen3.8-max' WHERE model_id = 'qwen-max'"),
    db.prepare("UPDATE messages SET token_count = NULL, cost = NULL WHERE role = 'assistant' AND content LIKE '%Agent SDK 后%'"),
  ]).then(() => undefined).catch((error) => {
    schemaReady = null;
    throw error;
  });
  return schemaReady;
}

export function ownerId(request: Request) {
  const authenticated = request.headers.get("oai-authenticated-user-id")?.trim();
  if (authenticated) return `user:${authenticated}`;
  const device = request.headers.get("x-luma-client-id")?.trim();
  if (!device || !/^[a-zA-Z0-9_-]{12,80}$/.test(device)) return null;
  return `device:${device}`;
}

export function publicSession(row: SessionRow) {
  return { id: row.id, title: row.title, modelId: row.model_id, createdAt: row.created_at, updatedAt: row.updated_at };
}

export function publicMessage(row: MessageRow) {
  return { id: row.id, role: row.role, content: row.content, tokens: row.token_count, cost: row.cost, createdAt: row.created_at };
}

export function publicFile(row: FileRow) {
  return { id: row.id, sessionId: row.session_id, name: row.name, contentType: row.content_type, size: row.size, createdAt: row.created_at, url: `/api/files/${row.id}` };
}

export function apiError(error: unknown) {
  console.error(error);
  return Response.json({ error: "服务暂时不可用" }, { status: 500 });
}
