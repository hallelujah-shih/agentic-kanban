// Playwright e2e 配置（plan T3 契约形态）。选择器登记见 tests/e2e/smoke.spec.js 头注释。
// 端口/DB 走 env 覆盖（E2E_PORT / AK_E2E_DB，默认 CI 值）：本地撞端口或 /tmp quota 时
// `E2E_PORT=18799 AK_E2E_DB=/home/shih/.tmp-ak-m16/.../ak-e2e.db npx playwright test`，
// 零 config 改动、零 CI 漂移。
const E2E_PORT = process.env.E2E_PORT || 18765;
const AK_E2E_DB = process.env.AK_E2E_DB || '/tmp/ak-e2e.db';

module.exports = require('@playwright/test').defineConfig({
  testDir: './tests/e2e',
  workers: 1,                    // 共享单服务+单 DB，串行防串扰（冒烟规模，串行成本可忽略）
  timeout: 30000,
  expect: { timeout: 15000 },    // SSE 2s 轮询刷新留足窗（flaky 对策：expect.poll，禁固定 sleep）
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: `http://127.0.0.1:${E2E_PORT}` },
  webServer: {
    // 服务段自携带 PYTHONPATH=src：.venv 是主仓 editable 安装，worktree 下裸
    // `python -m agent_kanban.api` 会影子主仓 src（T0 影子修正，2026-10-27）。
    command: `rm -f ${AK_E2E_DB}* && .venv/bin/python tests/e2e/seed.py ${AK_E2E_DB} && PYTHONPATH=\${PYTHONPATH:+$PYTHONPATH:}src AGENT_KANBAN_DB=${AK_E2E_DB} AGENT_KANBAN_PORT=${E2E_PORT} .venv/bin/python -m agent_kanban.api`,
    url: `http://127.0.0.1:${E2E_PORT}/healthz`,
    reuseExistingServer: false,
    timeout: 60000,
  },
});
