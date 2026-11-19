// Minimal vitest config for pure lib unit tests (lib/*.test.js). There is no
// Vue-component/DOM test harness in this project; this config intentionally
// stays narrow (Node environment, src/lib only) rather than pulling in
// vue-test-utils/jsdom, which the codebase does not otherwise use.
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.js'],
  },
});
