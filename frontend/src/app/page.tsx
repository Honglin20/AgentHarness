import { HeaderBar } from "@/components/layout/HeaderBar";
import { MainLayout } from "@/components/layout/MainLayout";
import { DAGPanel } from "@/components/layout/DAGPanel";
import { CenterPanel } from "@/components/layout/CenterPanel";
import { ChatPanel } from "@/components/layout/ChatPanel";

export default function Home() {
  return (
    <div className="flex h-screen flex-col">
      <HeaderBar />
      <MainLayout
        leftPanel={<DAGPanel />}
        centerPanel={<CenterPanel />}
        rightPanel={<ChatPanel />}
      />
    </div>
  );
}
