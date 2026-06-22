import { defineConfig } from "vitest/config";
import tsconfigPaths from "vite-tsconfig-paths";

// Vitest config — uses vite-tsconfig-paths to resolve the `@/*` path alias
// declared in tsconfig.json (so test files can import "@/lib/..." etc.).
//
// environment=happy-dom so @testing-library/react's renderHook can mount
// React components in tests. Pure-TS unit tests (deriveOutlineItems,
// outlineStore) also run cleanly under happy-dom.
//
// Limitation: vitest 4's oxc parser inherits tsconfig's `jsx:"preserve"`
// (set for Next.js SWC). This blocks component-level render tests on .tsx
// files containing JSX — vite's import-analysis can't parse raw JSX.
// Workaround is to extract pure logic from components and test that, OR
// configure oxc jsx override (TODO: revisit when vitest oxc API stabilizes).
export default defineConfig({
  plugins: [tsconfigPaths()],
  test: {
    include: ["src/**/__tests__/**/*.test.ts", "src/**/__tests__/**/*.test.tsx"],
    environment: "happy-dom",
  },
});
