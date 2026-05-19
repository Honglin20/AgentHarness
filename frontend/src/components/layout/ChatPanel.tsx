import { MessageSquare } from "lucide-react";

export function ChatPanel() {
  return (
    <aside className="flex w-[320px] flex-col border-l bg-app-bg-secondary">
      <div className="flex items-center gap-2 border-b px-3 py-2">
        <MessageSquare className="h-4 w-4 text-app-text-secondary" />
        <span className="text-sm font-medium text-app-text-primary">Chat</span>
      </div>
      <div className="flex flex-1 items-center justify-center">
        <p className="text-sm text-app-text-secondary">Human-in-the-loop chat</p>
      </div>
    </aside>
  );
}
