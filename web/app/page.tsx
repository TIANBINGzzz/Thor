import type { Metadata } from "next";
import { ChatWorkspace } from "./components/ChatWorkspace";
import { BRAND } from "./lib/brand";

export const metadata: Metadata = {
  title: `${BRAND.displayName} — ${BRAND.tagline}`,
  description: BRAND.description,
};

export default function Home() {
  return <ChatWorkspace />;
}
