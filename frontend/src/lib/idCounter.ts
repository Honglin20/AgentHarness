/**
 * ID Counter — generates unique sequential IDs for scoped store instances.
 *
 * Extracted from workflowStores.ts to eliminate duplication between
 * message counter and tool-call counter.
 */

export interface IdCounter {
  current: number;
  next(): string;
}

export function createIdCounter(prefix: string): IdCounter {
  let current = 0;
  return {
    get current() {
      return current;
    },
    next: () => `${prefix}${++current}`,
  };
}
