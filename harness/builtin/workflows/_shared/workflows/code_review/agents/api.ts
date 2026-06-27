/** API 客户端封装：自动添加认证 header */

const API_BASE = "";

/** 从 localStorage 获取当前 user_id */
export function getUserId(): string {
  return (typeof window !== "undefined" && localStorage.getItem("userId")) || "";
}

/** 保存 user_id 到 localStorage */
export function setUserId(userId: string): void {
  if (typeof window !== "undefined") {
    if (userId) {
      localStorage.setItem("userId", userId);
    } else {
      localStorage.removeItem("userId");
    }
  }
}

/** 从 localStorage 获取 API Key（向后兼容） */
export function getApiKey(): string {
  return (typeof window !== "undefined" && localStorage.getItem("apiKey")) || "";
}

/** 从 API Key 生成 user_id (用于 WebSocket 隔离) */
export function getUserFromApiKey(apiKey: string): string {
  // Simple hash of the API key to use as user_id
  let hash = 0;
  for (let i = 0; i < apiKey.length; i++) {
    const char = apiKey.charCodeAt(i);
    hash = ((hash << 5) - hash) + char;
    hash = hash & hash;
  }
  return `u-${Math.abs(hash).toString(16)}`;
}

/** 保存 API Key 到 localStorage（向后兼容） */
export function setApiKey(apiKey: string): void {
  if (typeof window !== "undefined") {
    if (apiKey) {
      localStorage.setItem("apiKey", apiKey);
    } else {
      localStorage.removeItem("apiKey");
    }
  }
}

/** 获取当前用户信息 */
export interface UserInfo {
  user_id: string;
  name: string;
  role: string;
}

export async function getCurrentUser(): Promise<UserInfo | null> {
  try {
    const res = await fetchWithAuth(`${API_BASE}/api/me`);
    if (res.ok) {
      return await res.json();
    }
    return null;
  } catch {
    return null;
  }
}

/** 带认证的 fetch：优先 X-User-Id，fallback 到 X-API-Key */
export function fetchWithAuth(
  url: string,
  options: RequestInit = {}
): Promise<Response> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> | undefined),
  };

  const userId = getUserId();
  if (userId) {
    headers["X-User-Id"] = userId;
  } else {
    const apiKey = getApiKey();
    if (apiKey) {
      headers["X-API-Key"] = apiKey;
    }
  }

  return fetch(url, {
    ...options,
    headers,
  });
}

/** GET 请求 */
export async function get<T>(url: string): Promise<T> {
  const res = await fetchWithAuth(url);
  if (!res.ok) {
    throw new Error(`GET ${url} failed: ${res.statusText}`);
  }
  return res.json();
}

/** POST 请求 */
export async function post<T>(url: string, body: unknown): Promise<T> {
  const res = await fetchWithAuth(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`POST ${url} failed: ${res.statusText}`);
  }
  return res.json();
}

/** DELETE 请求 */
export async function del<T>(url: string): Promise<T> {
  const res = await fetchWithAuth(url, {
    method: "DELETE",
  });
  if (!res.ok) {
    throw new Error(`DELETE ${url} failed: ${res.statusText}`);
  }
  return res.json();
}

/** PATCH 请求 */
export async function patch<T>(url: string, body: unknown): Promise<T> {
  const res = await fetchWithAuth(url, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error(`PATCH ${url} failed: ${res.statusText}`);
  }
  return res.json();
}