import type { Metadata } from "next";
import { StatsWorkspace } from "../components/StatsWorkspace";
import { BRAND } from "../lib/brand";

export const metadata: Metadata = {
  title: `用量统计 · ${BRAND.displayName}`,
  description: "查看已经产生的模型用量与实际费用。",
};

export default function StatsPage() {
  return <StatsWorkspace />;
}
