import { createServer } from "node:http";
import { randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join, normalize } from "node:path";
import { query } from "@anthropic-ai/claude-agent-sdk";
import { buildAgentOptions, missingEnvironment } from "./agent-options.mjs";
import { createTranslator } from "./sse-events.mjs";
import { createReadStream } from "node:fs";
import {
  createSession,
  appendSessionTurn,
  getSession,
  listSessionFiles,
  parseUpload,
  resolveSessionFile,
  sessionDirectory,
  sessionPromptContext,
  updateSessionModel,
} from "./session-files.mjs";
import {
  isSource,
  listSources,
  referencePromptContext,
  searchSource,
} from "./references.mjs";

const HOST = "127.0.0.1";
const PORT = Number(process.env.SCRIBE_PORT || 4310);
const MAX_TURNS = Number(process.env.SCRIBE_MAX_TURNS || 30);
const MAX_PROMPT_BYTES = 32 * 1024;
const MODELS = [...new Set(
  (process.env.SCRIBE_MODELS || process.env.ANTHROPIC_MODEL || "")
    .split(",")
    .map((model) => model.trim())
    .filter(Boolean),
)];

// 未显式配置时每次启动随机生成，避免出现固定的默认口令。
const TOKEN = process.env.SCRIBE_TOKEN || randomBytes(24).toString("hex");

const PUBLIC_DIR = join(dirname(fileURLToPath(import.meta.url)), "public");
const ALLOWED_ORIGINS = new Set([
  `http://${HOST}:${PORT}`,
  `http://localhost:${PORT}`,
]);

const STATIC_FILES = {
  "/": { file: "index.html", type: "text/html; charset=utf-8", inject: true },
  "/app.css": { file: "app.css", type: "text/css; charset=utf-8" },
  "/app.js": { file: "app.js", type: "text/javascript; charset=utf-8" },
};

const VENDOR_FILES = {
  "/vendor/marked.js": "marked",
  "/vendor/purify.js": "dompurify",
};

const invalidVariables = missingEnvironment();

if (invalidVariables.length > 0) {
  console.error(
    `请先在项目根目录的 .env 中配置：${invalidVariables.join(", ")}`,
  );
  process.exit(1);
}

/** 只接受指向本机的 Host，阻断 DNS rebinding。 */
function hostAllowed(request) {
  const host = request.headers.host;
  return host === `${HOST}:${PORT}` || host === `localhost:${PORT}`;
}

/**
 * 浏览器发起跨站请求时一定会带 Origin。缺失 Origin 的情况只可能来自
 * 同源导航或非浏览器客户端，此时由 token 兜底。
 */
function originAllowed(request) {
  const origin = request.headers.origin;
  return !origin || ALLOWED_ORIGINS.has(origin);
}

function tokenValid(request) {
  return request.headers["x-scribe-token"] === TOKEN;
}

function send(response, status, body, type = "text/plain; charset=utf-8") {
  response.writeHead(status, {
    "content-type": type,
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  response.end(body);
}

function sendJson(response, status, value) {
  send(response, status, JSON.stringify(value), "application/json; charset=utf-8");
}

async function readBody(request) {
  const chunks = [];
  let size = 0;

  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_PROMPT_BYTES) {
      throw new Error("请求体过大");
    }
    chunks.push(chunk);
  }

  return Buffer.concat(chunks).toString("utf8");
}

async function serveStatic(response, entry) {
  const path = normalize(join(PUBLIC_DIR, entry.file));

  if (!path.startsWith(PUBLIC_DIR)) {
    send(response, 403, "禁止访问");
    return;
  }

  let body = await readFile(path, "utf8");

  if (entry.inject) {
    // token 只注入到同源页面，不出现在任何静态构建产物里。
    body = body.replace("__SCRIBE_TOKEN__", TOKEN);
  }

  send(response, 200, body, entry.type);
}

async function serveVendor(response, specifier) {
  const path = fileURLToPath(import.meta.resolve(specifier));
  const body = await readFile(path, "utf8");
  send(response, 200, body, "text/javascript; charset=utf-8");
}

async function handleChat(request, response) {
  const raw = await readBody(request);
  let payload;

  try {
    payload = JSON.parse(raw);
  } catch {
    send(response, 400, "请求体不是合法 JSON");
    return;
  }

  const prompt = typeof payload.prompt === "string" ? payload.prompt.trim() : "";
  const appSessionId =
    typeof payload.appSessionId === "string" ? payload.appSessionId : "";

  if (!prompt) {
    send(response, 400, "prompt 不能为空");
    return;
  }
  if (!appSessionId) {
    send(response, 400, "appSessionId 不能为空");
    return;
  }

  let filesContext;
  let uploadDirectory;
  let savedSession;
  try {
    filesContext = await sessionPromptContext(appSessionId);
    uploadDirectory = sessionDirectory(appSessionId);
    savedSession = await getSession(appSessionId);
  } catch (error) {
    send(response, 404, error instanceof Error ? error.message : String(error));
    return;
  }

  const requestedModel = typeof payload.model === "string" ? payload.model.trim() : "";
  const model = requestedModel || savedSession.model || MODELS[0];
  if (!model || !MODELS.includes(model)) {
    send(response, 400, "model 不在允许列表中");
    return;
  }
  if (requestedModel && requestedModel !== savedSession.model) {
    await updateSessionModel(appSessionId, requestedModel);
  }

  const resume = savedSession.agentSessionId || undefined;

  response.writeHead(200, {
    "content-type": "text/event-stream; charset=utf-8",
    "cache-control": "no-store",
    connection: "keep-alive",
    "x-accel-buffering": "no",
  });

  // 客户端断开（关闭页面或点停止）时中止 query，避免继续烧 token。
  const abortController = new AbortController();
  request.on("close", () => abortController.abort());

  // 引用一律在服务端重新解析：前端传来的标签不可信，模型只该看到核对过的对象。
  const referencesContext = await referencePromptContext(prompt);

  const options = buildAgentOptions({
    maxTurns: MAX_TURNS,
    resume,
    model,
    includePartialMessages: true,
    abortController,
    additionalDirectories: [uploadDirectory],
  });

  const translate = createTranslator();
  const events = [];
  let agentSessionId = savedSession.agentSessionId;
  const emit = (event) => {
    events.push(event);
    if (event.type === "result" && event.sessionId) {
      agentSessionId = event.sessionId;
    }
    if (!response.writableEnded) {
      response.write(`data: ${JSON.stringify(event)}\n\n`);
    }
  };

  try {
    const fullPrompt = [
      filesContext,
      referencesContext,
      `用户请求：\n${prompt}`,
    ]
      .filter(Boolean)
      .join("\n\n");
    for await (const message of query({ prompt: fullPrompt, options })) {
      for (const event of translate(message)) {
        emit(event);
      }
    }
  } catch (error) {
    if (!abortController.signal.aborted) {
      emit({
        type: "error",
        message: error instanceof Error ? error.message : String(error),
      });
    }
  } finally {
    await appendSessionTurn(appSessionId, {
      prompt,
      events,
      agentSessionId,
      model,
    });
    if (!response.writableEnded) {
      response.write(`data: ${JSON.stringify({ type: "done" })}\n\n`);
      response.end();
    }
  }
}

async function handleCreateSession(request, response) {
  if (request.headers["content-length"] && Number(request.headers["content-length"]) > 1024) {
    send(response, 413, "请求体过大");
    return;
  }
  sendJson(response, 201, await createSession());
}

async function handleUpload(request, response, appSessionId) {
  try {
    sendJson(response, 201, await parseUpload(request, appSessionId));
  } catch (error) {
    send(response, 400, error instanceof Error ? error.message : String(error));
  }
}

async function handleSession(request, response, appSessionId) {
  try {
    sendJson(response, 200, await getSession(appSessionId));
  } catch (error) {
    send(response, 404, error instanceof Error ? error.message : String(error));
  }
}

async function handleDownload(request, response, appSessionId, name) {
  let file;
  try {
    file = await resolveSessionFile(appSessionId, decodeURIComponent(name));
  } catch (error) {
    send(response, 404, error instanceof Error ? error.message : String(error));
    return;
  }

  // 会话文件是不可信内容。统一按附件下发并禁掉嗅探，避免同源页面里
  // 直接执行上传来的 HTML/SVG；前端要预览就自己按 blob 渲染。
  response.writeHead(200, {
    "content-type": file.mimeType,
    "content-length": file.bytes,
    "content-disposition": `attachment; filename*=UTF-8''${encodeURIComponent(
      file.downloadName,
    )}`,
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "content-security-policy": "sandbox",
  });

  createReadStream(file.path).pipe(response);
}

const server = createServer(async (request, response) => {
  try {
    if (!hostAllowed(request)) {
      send(response, 421, "Host 不被允许");
      return;
    }

    const url = new URL(request.url, `http://${request.headers.host}`);

    if (request.method === "GET") {
      const entry = STATIC_FILES[url.pathname];

      if (entry) {
        await serveStatic(response, entry);
        return;
      }

      const vendor = VENDOR_FILES[url.pathname];

      if (vendor) {
        await serveVendor(response, vendor);
        return;
      }
    }

    if (request.method === "GET" && url.pathname === "/api/models") {
      if (!originAllowed(request) || !tokenValid(request)) {
        send(response, 403, "校验失败");
        return;
      }
      sendJson(response, 200, { models: MODELS });
      return;
    }

    if (request.method === "GET" && url.pathname === "/api/sources") {
      if (!originAllowed(request) || !tokenValid(request)) {
        send(response, 403, "校验失败");
        return;
      }
      sendJson(response, 200, { sources: listSources() });
      return;
    }

    // 候选集只在这里分页返回，绝不进模型 context——这是引用方案的关键。
    if (request.method === "GET" && url.pathname === "/api/options") {
      if (!originAllowed(request) || !tokenValid(request)) {
        send(response, 403, "校验失败");
        return;
      }

      const type = url.searchParams.get("source") || "";

      if (!isSource(type)) {
        send(response, 400, "source 不在允许列表中");
        return;
      }

      const page = await searchSource(type, url.searchParams.get("q") || "", {
        limit: url.searchParams.get("limit"),
        offset: url.searchParams.get("offset"),
      });
      sendJson(response, 200, page);
      return;
    }

    if (request.method === "POST" && url.pathname === "/api/session") {
      if (!originAllowed(request) || !tokenValid(request)) {
        send(response, 403, "校验失败");
        return;
      }

      await handleCreateSession(request, response);
      return;
    }

    const uploadMatch = url.pathname.match(/^\/api\/session\/([a-f0-9]{48})\/files$/);
    if (request.method === "POST" && uploadMatch) {
      if (!originAllowed(request) || !tokenValid(request)) {
        send(response, 403, "校验失败");
        return;
      }

      await handleUpload(request, response, uploadMatch[1]);
      return;
    }

    const sessionMatch = url.pathname.match(/^\/api\/session\/([a-f0-9]{48})$/);
    if (request.method === "GET" && sessionMatch) {
      if (!originAllowed(request) || !tokenValid(request)) {
        send(response, 403, "校验失败");
        return;
      }

      await handleSession(request, response, sessionMatch[1]);
      return;
    }

    const downloadMatch = url.pathname.match(
      /^\/api\/session\/([a-f0-9]{48})\/files\/([^/]+)$/,
    );
    if (request.method === "GET" && downloadMatch) {
      if (!originAllowed(request) || !tokenValid(request)) {
        send(response, 403, "校验失败");
        return;
      }

      await handleDownload(request, response, downloadMatch[1], downloadMatch[2]);
      return;
    }

    if (request.method === "POST" && url.pathname === "/api/chat") {
      // 自定义头强制触发预检；不回 CORS 头，跨站请求无法读取响应。
      if (!originAllowed(request) || !tokenValid(request)) {
        send(response, 403, "校验失败");
        return;
      }

      await handleChat(request, response);
      return;
    }

    send(response, 404, "未找到");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);

    if (!response.headersSent) {
      send(response, 500, message);
    } else if (!response.writableEnded) {
      response.end();
    }
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Scribe UI: http://${HOST}:${PORT}/`);
  console.log(`模型: ${process.env.ANTHROPIC_MODEL}`);

  if (!process.env.SCRIBE_TOKEN) {
    console.log("本次会话随机 token 已注入页面；如需固定请设置 SCRIBE_TOKEN。");
  }
});
