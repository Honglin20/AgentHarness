import { defineConfig } from "vitest/config";
import tsconfigPaths from "vite-tsconfig-paths";

// Vitest config — uses vite-tsconfig-paths to resolve the `@/*` path alias
// declared in tsconfig.json (so test files can import "@/lib/..." etc.).
export default defineConfig({
  plugins: [tsconfigPaths()],
  test: {
    include: ["src/**/__tests__/**/*.test.ts"],
  },
});
