import { apiError, database, ensureSchema, ownerId } from "@/db/runtime";

type SessionCountRow = { session_count: number };
type UsageRow = {
  response_count: number;
  token_count: number;
  actual_cost: number;
  billed_response_count: number;
};
type ModelUsageRow = {
  model_id: string;
  session_count: number;
  response_count: number;
  token_count: number;
  actual_cost: number;
};

export async function GET(request: Request) {
  try {
    const owner = ownerId(request);
    if (!owner) return Response.json({ error: "缺少客户端标识" }, { status: 401 });
    await ensureSchema();
    const db = database();
    const [sessionResult, usageResult, modelResult] = await Promise.all([
      db.prepare("SELECT COUNT(*) AS session_count FROM sessions WHERE owner_id = ?").bind(owner).first<SessionCountRow>(),
      db.prepare(`SELECT
        COUNT(*) AS response_count,
        COALESCE(SUM(token_count), 0) AS token_count,
        COALESCE(SUM(cost), 0) AS actual_cost,
        COUNT(cost) AS billed_response_count
        FROM messages
        WHERE owner_id = ? AND role = 'assistant'`).bind(owner).first<UsageRow>(),
      db.prepare(`SELECT
        s.model_id,
        COUNT(DISTINCT s.id) AS session_count,
        COUNT(m.id) AS response_count,
        COALESCE(SUM(m.token_count), 0) AS token_count,
        COALESCE(SUM(m.cost), 0) AS actual_cost
        FROM sessions s
        LEFT JOIN messages m ON m.session_id = s.id AND m.role = 'assistant'
        WHERE s.owner_id = ?
        GROUP BY s.model_id
        ORDER BY actual_cost DESC, response_count DESC`).bind(owner).all<ModelUsageRow>(),
    ]);

    return Response.json({
      totals: {
        sessions: Number(sessionResult?.session_count || 0),
        responses: Number(usageResult?.response_count || 0),
        tokens: Number(usageResult?.token_count || 0),
        actualCost: Number(usageResult?.actual_cost || 0),
        billedResponses: Number(usageResult?.billed_response_count || 0),
      },
      models: modelResult.results.map((row) => ({
        modelId: row.model_id,
        sessions: Number(row.session_count || 0),
        responses: Number(row.response_count || 0),
        tokens: Number(row.token_count || 0),
        actualCost: Number(row.actual_cost || 0),
      })),
    });
  } catch (error) {
    return apiError(error);
  }
}
