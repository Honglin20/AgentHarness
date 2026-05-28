"use client";

interface ConnectionStatusBarProps {
  isConnected: boolean;
}

export function ConnectionStatusBar({ isConnected }: ConnectionStatusBarProps) {
  if (isConnected) return null;

  return (
    <div className="flex h-6 items-center justify-center bg-amber-100 text-xs font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-300">
      Disconnected — real-time updates paused
    </div>
  );
}
