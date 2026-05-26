import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// ============ 原始版本 ============
function cn_original(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ============ 优化版本 1：短路优化 ============
function cn_optimized_v1(...inputs: ClassValue[]) {
  if (inputs.length === 1 && typeof inputs[0] === 'string') {
    return twMerge(inputs[0]);
  }
  return twMerge(clsx(inputs));
}

// ============ 优化版本 2：带 LRU 缓存 ============
class LRUCache<K, V> {
  private capacity: number;
  private cache: Map<K, V>;

  constructor(capacity: number) {
    this.capacity = capacity;
    this.cache = new Map();
  }

  get(key: K): V | undefined {
    if (!this.cache.has(key)) return undefined;
    const value = this.cache.get(key)!;
    this.cache.delete(key);
    this.cache.set(key, value);
    return value;
  }

  set(key: K, value: V): void {
    if (this.cache.has(key)) {
      this.cache.delete(key);
    } else if (this.cache.size >= this.capacity) {
      const oldest = this.cache.keys().next().value;
      if (oldest !== undefined) this.cache.delete(oldest);
    }
    this.cache.set(key, value);
  }

  clear(): void {
    this.cache.clear();
  }
}

const cnCache = new LRUCache<string, string>(500);

function cn_optimized_v2(...inputs: ClassValue[]): string {
  const key = JSON.stringify(inputs);
  const cached = cnCache.get(key);
  if (cached !== undefined) return cached;

  let result: string;
  if (inputs.length === 1 && typeof inputs[0] === 'string') {
    result = twMerge(inputs[0]);
  } else {
    result = twMerge(clsx(inputs));
  }
  
  cnCache.set(key, result);
  return result;
}

// ============ 测试用例 ============
function generateTestCases(count: number): ClassValue[][] {
  const cases: ClassValue[][] = [];
  // 简单字符串 - 30%
  for (let i = 0; i < count * 0.3; i++) {
    cases.push([`px-${i % 8 + 1} py-${i % 4 + 1} bg-blue-500`]);
  }
  // 条件类名 - 40%
  for (let i = 0; i < count * 0.4; i++) {
    cases.push([
      'px-4 py-2',
      i % 2 === 0 ? 'bg-blue-500' : 'bg-red-500',
      i % 3 === 0 && 'text-white',
    ]);
  }
  // 复杂组合 - 30%
  for (let i = 0; i < count * 0.3; i++) {
    cases.push([
      'px-4 py-2 rounded-lg',
      i % 2 === 0 ? 'bg-blue-500 hover:bg-blue-600' : 'bg-gray-100',
      i % 3 === 0 ? 'text-white' : 'text-gray-900',
      i % 5 === 0 ? 'shadow-md' : 'shadow-sm',
      'transition-all duration-200',
    ]);
  }
  return cases;
}

function shuffleArray<T>(arr: T[]): T[] {
  const shuffled = [...arr];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
}

function runBenchmark(
  name: string, 
  fn: (...args: ClassValue[]) => string, 
  testCases: ClassValue[][], 
  iterations: number
): number {
  // Warmup
  for (let i = 0; i < 100; i++) {
    fn(...testCases[i % testCases.length]);
  }

  const start = performance.now();
  for (let iter = 0; iter < iterations; iter++) {
    for (const args of testCases) {
      fn(...args);
    }
  }
  const end = performance.now();
  return end - start;
}

// ============ 主测试 ============
const TEST_CASES = 200;
const ITERATIONS = 50;
const testCases = shuffleArray(generateTestCases(TEST_CASES));

console.log(`测试配置: ${TEST_CASES} 个测试用例, ${ITERATIONS} 轮迭代`);
console.log(`总计调用次数: ${TEST_CASES * ITERATIONS}\n`);
console.log("=".repeat(80));

// 测试原始版本
const timeOriginal = runBenchmark("原始版本", cn_original, testCases, ITERATIONS);
console.log(`原始版本 (cn_original):   ${timeOriginal.toFixed(2)}ms`);

// 测试优化版本1
const timeV1 = runBenchmark("优化版本1", cn_optimized_v1, testCases, ITERATIONS);
console.log(`优化版本1 (短路优化):     ${timeV1.toFixed(2)}ms (${((timeV1 / timeOriginal - 1) * 100).toFixed(1)}% vs 原始)`);

// 测试优化版本2 (清除缓存)
cnCache.clear();
const timeV2 = runBenchmark("优化版本2", cn_optimized_v2, testCases, ITERATIONS);
console.log(`优化版本2 (LRU缓存+短路): ${timeV2.toFixed(2)}ms (${((timeV2 / timeOriginal - 1) * 100).toFixed(1)}% vs 原始)`);

console.log("=".repeat(80));
console.log("\n性能对比:");
if (timeV1 < timeOriginal) console.log(`✅ 优化版本1 (短路优化) 比原始版本快 ${((timeOriginal / timeV1 - 1) * 100).toFixed(1)}%`);
else console.log(`❌ 优化版本1 (短路优化) 比原始版本慢 ${((timeV1 / timeOriginal - 1) * 100).toFixed(1)}%`);

if (timeV2 < timeOriginal) console.log(`✅ 优化版本2 (LRU缓存+短路) 比原始版本快 ${((timeOriginal / timeV2 - 1) * 100).toFixed(1)}%`);
else console.log(`❌ 优化版本2 (LRU缓存+短路) 比原始版本慢 ${((timeV2 / timeOriginal - 1) * 100).toFixed(1)}%`);

// 缓存命中率测试
console.log("\n--- 缓存重复命中率测试 ---");
cnCache.clear();
const cacheTestCases = testCases.slice(0, 20);
let hits = 0;
let misses = 0;

// First pass (misses)
for (const args of cacheTestCases) {
  cn_optimized_v2(...args);
  misses++;
}

// Subsequent passes (hits)
for (let round = 1; round < 5; round++) {
  for (const args of cacheTestCases) {
    cn_optimized_v2(...args);
    hits++;
  }
}
console.log(`缓存命中: ${hits}, 未命中: ${misses}, 命中率: ${(hits / (hits + misses) * 100).toFixed(1)}%`);

// 正确性测试
console.log("\n--- 正确性测试 ---");
const testCases_correctness: { input: ClassValue[]; expected: string }[] = [
  { input: ['px-4 py-2', 'px-6'], expected: 'px-6 py-2' },
  { input: ['text-red-500', 'text-blue-500'], expected: 'text-blue-500' },
  { input: ['bg-black', 'bg-white'], expected: 'bg-white' },
  { input: ['px-4'], expected: 'px-4' },
  { input: [], expected: '' },
];

let allPass = true;
for (const { input, expected } of testCases_correctness) {
  const result1 = cn_original(...input);
  const result2 = cn_optimized_v1(...input);
  const result3 = cn_optimized_v2(...input);
  
  const ok1 = result1 === expected;
  const ok2 = result2 === expected;
  const ok3 = result3 === expected;
  
  if (!ok1 || !ok2 || !ok3) {
    console.log(`❌ 失败: cn(${JSON.stringify(input)})`);
    console.log(`   期望: "${expected}"`);
    console.log(`   原始: "${result1}" ${ok1 ? '✅' : '❌'}`);
    console.log(`   v1:   "${result2}" ${ok2 ? '✅' : '❌'}`);
    console.log(`   v2:   "${result3}" ${ok3 ? '✅' : '❌'}`);
    allPass = false;
  }
}
if (allPass) console.log("✅ 所有正确性测试通过!");

console.log("\n" + "=".repeat(80));
console.log("测试完成!");
