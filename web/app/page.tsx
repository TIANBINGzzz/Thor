import type { Metadata } from "next";
import { ChatWorkspace } from "./components/ChatWorkspace";

export const metadata: Metadata = {
  title: "Luma — 清晰地对话",
  description: "一个专注、透明的 AI 对话界面。",
};

export default function Home() {
  return <ChatWorkspace />;
}
