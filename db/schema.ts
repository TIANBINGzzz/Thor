import { index, integer, real, sqliteTable, text } from "drizzle-orm/sqlite-core";

export const sessions = sqliteTable("sessions", {
  id: text("id").primaryKey(),
  ownerId: text("owner_id").notNull(),
  title: text("title").notNull().default("New chat"),
  modelId: text("model_id").notNull().default("deepseek-v4-flash"),
  createdAt: integer("created_at").notNull(),
  updatedAt: integer("updated_at").notNull(),
}, (table) => [index("idx_sessions_owner_updated").on(table.ownerId, table.updatedAt)]);

export const messages = sqliteTable("messages", {
  id: text("id").primaryKey(),
  sessionId: text("session_id").notNull().references(() => sessions.id, { onDelete: "cascade" }),
  ownerId: text("owner_id").notNull(),
  role: text("role", { enum: ["user", "assistant"] }).notNull(),
  content: text("content").notNull(),
  tokenCount: integer("token_count"),
  cost: real("cost"),
  createdAt: integer("created_at").notNull(),
}, (table) => [index("idx_messages_session_created").on(table.sessionId, table.createdAt)]);

export const files = sqliteTable("files", {
  id: text("id").primaryKey(),
  sessionId: text("session_id").notNull().references(() => sessions.id, { onDelete: "cascade" }),
  ownerId: text("owner_id").notNull(),
  name: text("name").notNull(),
  contentType: text("content_type").notNull(),
  size: integer("size").notNull(),
  storageKey: text("storage_key").notNull().unique(),
  createdAt: integer("created_at").notNull(),
}, (table) => [index("idx_files_session_created").on(table.sessionId, table.createdAt)]);
