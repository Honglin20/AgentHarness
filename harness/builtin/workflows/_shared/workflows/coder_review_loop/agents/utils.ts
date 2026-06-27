/**
 * 基于 LRU 缓存的 tailwind-merge 工具函数
 *
 * 优化说明：
 * - 引入 LRU 缓存（上限 500 条），避免相同类名组合重复调用 twMerge
 * - 缓存键以 clsx 标准化后的字符串为准，确保相同语义的输入命中同一缓存
 * - 使用 Map 的插入顺序特性实现 LRU 淘汰：每次访问将键移到末尾，超出上限时删除首项
 */

import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** LRU 缓存实例，仅限模块内部使用 */
const cache = new Map<string, string>();

/** 缓存最大条目数 */
const MAX_CACHE_SIZE = 500;

/**
 * 合并 Tailwind CSS 类名，带 LRU 缓存优化。
 *
 * 在组件频繁重渲染场景下，相同类名组合会命中缓存，
 * 避免重复调用 twMerge 的开销。
 *
 * @param inputs 变长参数，支持 ClassValue 数组
 * @returns 合并后的类名字符串
 */
export function cn(...inputs: ClassValue[]): string {
  // 1. 先通过 clsx 标准化输入，得到统一的 key
  const key = clsx(inputs);

  // 2. 空字符串直接返回，无需缓存
  if (key === "") {
    return "";
  }

  // 3. LRU 缓存查找
  const cached = cache.get(key);
  if (cached !== undefined) {
    // 将该键移到末尾（更新访问顺序），保持 LRU 特性
    cache.delete(key);
    cache.set(key, cached);
    return cached;
  }

  // 4. 缓存未命中，执行 twMerge
  const result = twMerge(key);

  // 5. 写入缓存（上限检查 + LRU 淘汰）
  if (cache.size >= MAX_CACHE_SIZE) {
    // 删除最久未访问的条目（Map 的首项）
    const oldestKey = cache.keys().next().value;
    if (oldestKey !== undefined) {
      cache.delete(oldestKey);
    }
  }
  cache.set(key, result);

  return result;
}

/**
 * 清除 cn 函数的内部 LRU 缓存。
 * 适用于测试场景或需要强制刷新缓存的场合。
 */
export function clearCnCache(): void {
  cache.clear();
}
