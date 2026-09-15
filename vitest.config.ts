import { defineConfig } from 'vitest/config';

/**
 * 2026-09-13 mobile-notes：frontend unit tests。
 * 刻意唔放入 vite.config.ts，避免影響 `npm run build`（tsc -b）嘅 project references。
 */
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    reporters: ['default'],
  },
});
