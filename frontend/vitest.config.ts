import { defineConfig } from "vitest/config";
import tsconfigPaths from "vite-tsconfig-paths";

// Vitest config — uses vite-tsconfig-paths to resolve the `@/*` path alias
// declared in tsconfig.json (so test files can import "@/lib/..." etc.).
//
// environment=happy-dom so @testing-library/react's renderHook can mount
// React components in tests. Pure-TS unit tests (deriveOutlineItems,
// outlineStore) also run cleanly under happy-dom.
export default defineConfig({
  plugins: [tsconfigPaths()],
  test: {
    include: ["src/**/__tests__/**/*.test.ts", "src/**/__tests__/**/*.test.tsx"],
    environment: "happy-dom",
  },
});
