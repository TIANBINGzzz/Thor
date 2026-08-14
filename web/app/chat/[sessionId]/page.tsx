import { ChatWorkspace } from "../../components/ChatWorkspace";

export default async function SessionPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = await params;
  return <ChatWorkspace initialSessionId={sessionId} />;
}
