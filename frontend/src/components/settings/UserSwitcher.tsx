"use client";

import { useState, useEffect, useCallback } from "react";
import { Check, Plus, Trash2, Shield } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { getUserId, fetchWithAuth } from "@/lib/api";
import { useUserStore } from "@/stores/userStore";

interface UserInfo {
  user_id: string;
  name: string;
  role: string;
}

interface UserSwitcherProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Generate a stable color from user_id */
function avatarColor(id: string): string {
  const colors = [
    "bg-blue-500", "bg-emerald-500", "bg-violet-500", "bg-amber-500",
    "bg-rose-500", "bg-cyan-500", "bg-indigo-500", "bg-teal-500",
  ];
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = ((hash << 5) - hash + id.charCodeAt(i)) & hash;
  return colors[Math.abs(hash) % colors.length];
}

function UserAvatar({ name, userId }: { name: string; userId: string }) {
  const initials = name.charAt(0).toUpperCase();
  return (
    <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white ${avatarColor(userId)}`}>
      {initials}
    </div>
  );
}

export default function UserSwitcher({ open, onOpenChange }: UserSwitcherProps) {
  const [users, setUsers] = useState<UserInfo[]>([]);
  const currentUserId = useUserStore((s) => s.userId);
  const currentUserName = useUserStore((s) => s.name);
  const currentUserRole = useUserStore((s) => s.role);
  const [showAddForm, setShowAddForm] = useState(false);
  const [newUserId, setNewUserId] = useState("");
  const [newUserName, setNewUserName] = useState("");
  const [newUserRole, setUserRole] = useState("developer");
  const [error, setError] = useState("");

  const loadUsers = useCallback(async () => {
    try {
      const res = await fetchWithAuth("/api/users");
      if (res.ok) setUsers(await res.json());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    if (open) {
      loadUsers();
      setShowAddForm(false);
      setError("");
    }
  }, [open, loadUsers]);

  const handleSwitch = (user: UserInfo) => {
    useUserStore.getState().switchUser(user.user_id, user.name, user.role);
    onOpenChange(false);
  };

  const handleAdd = async () => {
    setError("");
    if (!newUserId.trim() || !newUserName.trim()) {
      setError("user_id 和 name 不能为空");
      return;
    }
    try {
      const res = await fetchWithAuth("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: newUserId, name: newUserName, role: newUserRole }),
      });
      if (res.ok) {
        setShowAddForm(false);
        setNewUserId("");
        setNewUserName("");
        setUserRole("developer");
        await loadUsers();
      } else {
        const data = await res.json();
        setError(data.detail || "添加失败");
      }
    } catch {
      setError("请求失败");
    }
  };

  const handleDelete = async (userId: string) => {
    try {
      const res = await fetchWithAuth(`/api/users/${userId}`, { method: "DELETE" });
      if (res.ok) {
        await loadUsers();
        if (currentUserId === userId) {
          useUserStore.getState().switchUser("default", "Default User", "developer");
        }
      }
    } catch { /* ignore */ }
  };

  const isAdmin = currentUserRole === "admin";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>切换用户</DialogTitle>
          <DialogDescription>
            选择一个用户身份来运行和管理工作流。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1 py-2 max-h-[360px] overflow-y-auto">
          {users.map((user) => {
            const isActive = currentUserId === user.user_id;
            return (
              <div
                key={user.user_id}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 cursor-pointer transition-colors ${
                  isActive
                    ? "bg-primary/10 ring-1 ring-primary/20"
                    : "hover:bg-muted/60"
                }`}
                onClick={() => handleSwitch(user)}
              >
                <UserAvatar name={user.name} userId={user.user_id} />
                <div className="flex-1 min-w-0">
                  <div className={`text-sm font-medium truncate ${isActive ? "text-primary" : ""}`}>
                    {user.name}
                  </div>
                  <div className="text-xs text-muted-foreground">{user.user_id}</div>
                </div>
                {user.role === "admin" && (
                  <span className="flex items-center gap-1 text-[10px] rounded-full bg-amber-100 px-2 py-0.5 font-medium text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
                    <Shield className="h-2.5 w-2.5" /> admin
                  </span>
                )}
                {isActive && (
                  <Check className="h-4 w-4 shrink-0 text-primary" />
                )}
                {isAdmin && !isActive && user.role !== "admin" && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive hover:opacity-100"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDelete(user.user_id);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            );
          })}
        </div>

        {isAdmin && (
          <div className="border-t pt-3 mt-1">
            {showAddForm ? (
              <div className="space-y-2">
                <div className="grid grid-cols-2 gap-2">
                  <Input
                    placeholder="user_id"
                    value={newUserId}
                    onChange={(e) => setNewUserId(e.target.value)}
                    className="h-8 text-xs"
                  />
                  <Input
                    placeholder="显示名称"
                    value={newUserName}
                    onChange={(e) => setNewUserName(e.target.value)}
                    className="h-8 text-xs"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <select
                    value={newUserRole}
                    onChange={(e) => setUserRole(e.target.value)}
                    className="h-8 rounded-md border bg-background px-2 text-xs"
                  >
                    <option value="developer">developer</option>
                    <option value="admin">admin</option>
                  </select>
                  <div className="flex-1" />
                  <Button size="sm" className="h-7 text-xs" onClick={handleAdd}>确认添加</Button>
                  <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => { setShowAddForm(false); setError(""); }}>取消</Button>
                </div>
                {error && <p className="text-xs text-destructive">{error}</p>}
              </div>
            ) : (
              <Button
                variant="outline"
                size="sm"
                className="h-8 w-full text-xs gap-1.5"
                onClick={() => setShowAddForm(true)}
              >
                <Plus className="h-3.5 w-3.5" /> 添加用户
              </Button>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
