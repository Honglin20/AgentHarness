import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

// ============ 原始版本 ============
function cn_original(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

// ============ 优化版本 1：短路优化（推荐）============
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

// ============ 测试用例生成 ============
function generateTestCases(count: number): ClassValue[][] {
  const cases: ClassValue[][] = [];
  // 简单字符串 - 30%（最常见场景：单个类名字符串）
  for (let i = 0; i < count * 0.3; i++) {
    cases.push([`px-${i % 8 + 1} py-${i % 4 + 1} bg-blue-500`]);
  }
  // 条件类名 - 40%（典型 shadcn/ui 使用模式）
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
const TEST_CASES = 500;
const ITERATIONS = 100;

console.log("=".repeat(80));
console.log("  cn() 函数性能基准测试");
console.log("=".repeat(80));
console.log(`测试配置: ${TEST_CASES} 个测试用例, ${ITERATIONS} 轮迭代`);
console.log(`总计调用次数: ${TEST_CASES * ITERATIONS}\n`);

const testCases = shuffleArray(generateTestCases(TEST_CASES));

// 测试原始版本
const timeOriginal = runBenchmark("原始版本", cn_original, testCases, ITERATIONS);
console.log(`🔴 原始版本 (cn_original):       ${timeOriginal.toFixed(2)}ms`);

// 测试优化版本1
const timeV1 = runBenchmark("优化版本1", cn_optimized_v1, testCases, ITERATIONS);
const improvement1 = ((timeOriginal / timeV1 - 1) * 100).toFixed(1);
console.log(`🟢 优化版本1 (短路优化):         ${timeV1.toFixed(2)}ms (快 ${improvement1}%)`);

// 测试优化版本2 (清除缓存)
cnCache.clear();
const timeV2 = runBenchmark("优化版本2", cn_optimized_v2, testCases, ITERATIONS);
const diff2 = ((timeV2 / timeOriginal - 1) * 100).toFixed(1);
console.log(`🟡 优化版本2 (LRU缓存+短路):     ${timeV2.toFixed(2)}ms (${diff2}% vs 原始)`);

console.log("\n" + "-".repeat(80));

// ============ 缓存命中场景测试 ============
console.log("\n📊 场景二：高缓存命中率 (重复渲染相同组件)");
cnCache.clear();
const repeatCases: ClassValue[][] = [];
const uniqueCases = 50;
for (let i = 0; i < uniqueCases; i++) {
  repeatCases.push([`px-${i % 4 + 1} py-${i % 2 + 1}`, i % 2 === 0 ? 'bg-blue-500' : 'bg-red-500']);
}

// 模拟 React 组件重复渲染
const RENDER_COUNT = 1000;

// 原始版本
let start = performance.now();
for (let i = 0; i < RENDER_COUNT; i++) {
  for (const args of repeatCases) {
    cn_original(...args);
  }
}
const repeatTimeOriginal = performance.now() - start;

// 优化版本1
start = performance.now();
for (let i = 0; i < RENDER_COUNT; i++) {
  for (const args of repeatCases) {
    cn_optimized_v1(...args);
  }
}
const repeatTimeV1 = performance.now() - start;

// 优化版本2 (有缓存)
cnCache.clear();
start = performance.now();
for (let i = 0; i < RENDER_COUNT; i++) {
  for (const args of repeatCases) {
    cn_optimized_v2(...args);
  }
}
const repeatTimeV2 = performance.now() - start;

console.log(`原始版本:     ${repeatTimeOriginal.toFixed(2)}ms`);
console.log(`短路优化:     ${repeatTimeV1.toFixed(2)}ms (${((repeatTimeOriginal / repeatTimeV1 - 1) * 100).toFixed(1)}% 更快)`);
console.log(`LRU缓存优化:  ${repeatTimeV2.toFixed(2)}ms (${((repeatTimeOriginal / repeatTimeV2 - 1) * 100).toFixed(1)}% 更快)`);

// ============ 正确性测试 ============
console.log("\n" + "-".repeat(80));
console.log("\n✅ 正确性测试");

interface TestCase {
  input: ClassValue[];
  expected: string;
  description: string;
}

const testCases_correctness: TestCase[] = [
  { input: ['px-4 py-2', 'px-6'], expected: 'py-2 px-6', description: 'twMerge 冲突消除' },
  { input: ['text-red-500', 'text-blue-500'], expected: 'text-blue-500', description: '颜色冲突' },
  { input: ['bg-black', 'bg-white'], expected: 'bg-white', description: '背景冲突' },
  { input: ['px-4'], expected: 'px-4', description: '单个字符串' },
  { input: [], expected: '', description: '空参数' },
  { input: [null, undefined, 'px-4'], expected: 'px-4', description: '过滤 null/undefined' },
  { input: [false && 'hidden', 'block'], expected: 'block', description: '条件 false' },
  { input: [true && 'flex', 'items-center'], expected: 'flex items-center', description: '条件 true' },
  { input: ['px-4', ['py-2']], expected: 'px-4 py-2', description: '数组参数 (clsx)' },
  { input: [['px-4', 'py-2'], { 'bg-blue-500': true }], expected: 'bg-blue-500 px-4 py-2', description: '混合参数 (clsx)' },
];

let allPass = true;
for (const { input, expected, description } of testCases_correctness) {
  const result1 = cn_original(...input);
  const result2 = cn_optimized_v1(...input);
  const result3 = cn_optimized_v2(...input);
  
  // Normalize: sort both for comparison since twMerge may reorder
  const normalize = (s: string) => s.trim().split(/\s+/).sort().join(' ');
  const normExpected = normalize(expected);
  const normR1 = normalize(result1);
  const normR2 = normalize(result2);
  const normR3 = normalize(result3);
  
  const ok = normR1 === normExpected && normR2 === normExpected && normR3 === normExpected;
  
  if (!ok) {
    console.log(`❌ ${description}: cn(${JSON.stringify(input)})`);
    console.log(`   期望: "${expected}"`);
    console.log(`   原始: "${result1}"`);
    console.log(`   v1:   "${result2}"`);
    console.log(`   v2:   "${result3}"`);
    allPass = false;
  } else {
    console.log(`✅ ${description}: "${result1}"`);
  }
}

if (allPass) console.log("\n🎉 所有正确性测试通过!");

console.log("\n" + "=".repeat(80));
console.log("测试完成!");
