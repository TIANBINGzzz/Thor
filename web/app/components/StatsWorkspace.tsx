"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeftIcon, StatsIcon } from "./icons";
import { ThemeToggle } from "./ThemeToggle";

type Stats = {
  totals: { sessions: number; responses: number; tokens: number; actualCost: number };
  models: Array<{ modelId: string; sessions: number; responses: number; tokens: number; actualCost: number }>;
};

function getClientId() {
  const key = "luma-client-id";
  let value = localStorage.getItem(key);
  if (!value) {
    value = crypto.randomUUID().replaceAll("-", "");
    localStorage.setItem(key, value);
  }
  return value;
}

function number(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function StatsWorkspace() {
  const router = useRouter();
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/stats", {
      headers: { "x-luma-client-id": getClientId() },
      signal: controller.signal,
    })
      .then(async (response) => {
        const data = await response.json() as Stats & { error?: string };
        if (!response.ok) throw new Error(data.error || "无法读取统计");
        setStats(data);
      })
      .catch((caught) => {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setError(caught instanceof Error ? caught.message : "无法读取统计");
      });
    return () => controller.abort();
  }, []);

  return (
    <main className="stats-shell">
      <header className="stats-topbar">
        <button onClick={() => router.push("/")} aria-label="返回对话"><ArrowLeftIcon /></button>
        <div><span className="model-orb"><StatsIcon /></span><span>用量统计</span></div>
      </header>
      <ThemeToggle />
      <section className="stats-content">
        {error ? <div className="stats-error" role="alert">{error}</div> : !stats ? <div className="stats-loading" aria-label="正在读取统计"><i /><i /><i /></div> : <>
          <section className="usage-scorecard" aria-label="累计用量">
            <div className="cost-total"><span>累计实际费用</span><strong><small>$</small>{stats.totals.actualCost.toFixed(4)}</strong></div>
            <div className="usage-metric"><span>实际 tokens</span><strong>{number(stats.totals.tokens)}</strong></div>
            <div className="usage-metric"><span>模型回复</span><strong>{number(stats.totals.responses)}</strong></div>
            <div className="usage-metric"><span>历史会话</span><strong>{number(stats.totals.sessions)}</strong></div>
          </section>

          <section className="model-usage">
            <header><div><h2>按模型</h2><p>每个会话使用的具体模型 ID</p></div><span>{stats.models.length} MODELS</span></header>
            <div className="model-usage-head"><span>模型</span><span>会话</span><span>回复</span><span>tokens</span><span>实际费用</span></div>
            {stats.models.length === 0 ? <p className="stats-empty">开始一段对话后，这里会显示真实用量。</p> : stats.models.map((model) => <div className="model-usage-row" key={model.modelId}><strong>{model.modelId}</strong><span>{number(model.sessions)}</span><span>{number(model.responses)}</span><span>{number(model.tokens)}</span><span>${model.actualCost.toFixed(4)}</span></div>)}
          </section>
        </>}
      </section>
    </main>
  );
}
