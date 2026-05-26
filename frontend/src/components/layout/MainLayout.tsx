import { type ReactNode } from "react";

interface MainLayoutProps {
  leftPanel: ReactNode;
  centerPanel: ReactNode;
  rightPanel: ReactNode;
}

export function MainLayout({ leftPanel, centerPanel, rightPanel }: MainLayoutProps) {
  return (
    <div className="flex flex-1 overflow-hidden">
      {leftPanel}
      {centerPanel}
      {rightPanel}
    </div>
  );
}
