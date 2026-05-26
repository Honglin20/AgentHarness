"use client";

import { useState } from "react";
import { X, Key, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { getApiKey, setApiKey, getCurrentUser } from "@/lib/api";

interface ApiKeySettingsProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export default function ApiKeySettings({ open, onOpenChange }: ApiKeySettingsProps) {
  const [apiKey, setApiKeyInput] = useState(getApiKey());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [userInfo, setUserInfo] = useState<{ user_id: string; name: string } | null>(null);

  const handleSave = async () => {
    setLoading(true);
    setError("");

    try {
      setApiKey(apiKey);

      // 验证 API Key
      const user = await getCurrentUser();
      if (user) {
        setUserInfo(user);
      } else {
        setError("API Key 无效，请检查");
      }
    } catch (e) {
      setError("验证失败: " + (e as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleClear = () => {
    setApiKeyInput("");
    setApiKey("");
    setUserInfo(null);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>API Key 设置</DialogTitle>
          <DialogDescription>
            设置您的 API Key 以访问私有 workflows 和隔离运行记录。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label htmlFor="apiKey">API Key</Label>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Key className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  id="apiKey"
                  type="password"
                  placeholder="输入您的 API Key"
                  value={apiKey}
                  onChange={(e) => setApiKeyInput(e.target.value)}
                  className="pl-9"
                />
              </div>
              <Button onClick={handleSave} disabled={loading} size="sm">
                {loading ? "验证中..." : "保存"}
              </Button>
            </div>
          </div>

          {userInfo && (
            <div className="flex items-center gap-2 rounded-lg bg-green-50 p-3 text-sm text-green-800 dark:bg-green-900/20 dark:text-green-400">
              <Check className="h-4 w-4" />
              <span>
                已验证: <strong>{userInfo.name}</strong> ({userInfo.user_id})
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleClear}
                className="ml-auto h-6 px-2"
              >
                清除
              </Button>
            </div>
          )}

          {error && (
            <div className="rounded-lg bg-red-50 p-3 text-sm text-red-800 dark:bg-red-900/20 dark:text-red-400">
              {error}
            </div>
          )}

          <div className="rounded-lg bg-muted/50 p-3 text-xs text-muted-foreground">
            <p className="font-medium">默认 API Keys:</p>
            <ul className="mt-1 space-y-1">
              <li>• dev_alice - 开发者 Alice</li>
              <li>• dev_bob - 开发者 Bob</li>
              <li>• admin - 管理员</li>
            </ul>
          </div>
        </div>

        <div className="flex justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}