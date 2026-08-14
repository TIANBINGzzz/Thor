import { fileURLToPath } from "node:url";

const TRUE_VALUES = new Set(["1", "true", "yes"]);

function definedEnvironment() {
  return Object.fromEntries(
    Object.entries(process.env).filter((entry) => entry[1] !== undefined),
  );
}

export function createDatabaseMcpServer() {
  const demo = TRUE_VALUES.has((process.env.DB_DEMO || "").toLowerCase());
  const databaseUrl = process.env.DATABASE_URL?.trim();

  if (!demo && !databaseUrl) {
    return null;
  }

  const dbhubEntrypoint = fileURLToPath(import.meta.resolve("@bytebase/dbhub"));
  const env = definedEnvironment();

  if (databaseUrl) {
    env.DSN = databaseUrl;
  }

  return {
    type: "stdio",
    command: process.execPath,
    args: [
      dbhubEntrypoint,
      "--transport",
      "stdio",
      ...(demo ? ["--demo"] : []),
    ],
    env,
  };
}
