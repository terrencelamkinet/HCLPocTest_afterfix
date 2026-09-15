/**
 * Auth helper for Playwright E2E tests.
 *
 * 2026-09-15 SAST（AppScan「Validation Required — Local Storage Insecure」）：
 * session 已經由 localStorage JWT 改成 httpOnly cookie（見 src/lib/api.ts）。
 * 所以呢個 helper 唔再偷 token 塞落 localStorage — 改為**真 login**，等 server
 * 種 cookie，之後 Playwright 個 context 會自動帶住。
 *
 * 舊版順手修埋兩個 bug（本身就係壞嘅）：
 *   1. `POST ${BACKEND}/auth/login` 漏咗 `/api/v1` → 永遠 404，靜靜咁跌落 fallback；
 *   2. fallback 打 `/api/v1/auth/test-token`（根本冇呢個 endpoint）+ 硬編碼兩個 UUID。
 *
 * 密碼唔入 repo：要喺環境變數 E2E_PASSWORD 提供。
 */

import { Page, expect } from '@playwright/test';

const TEST_EMAIL = 'terrence_lam@kinetix.com.hk';

export async function loginAsTerrence(page: Page): Promise<void> {
  const password = process.env.E2E_PASSWORD ?? '';
  if (!password) throw new Error('E2E_PASSWORD 未設定 — 唔准將密碼寫入 repo（見 SECURITY-FIXES.md）');

  await page.goto('/sign-in');
  await page.fill('input[type="email"]', TEST_EMAIL);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  await expect(page).toHaveURL(/dashboard/, { timeout: 15000 });

  // 回歸測試：session cookie 一定要係 httpOnly（localStorage 唔准有 token）
  const cookies = await page.context().cookies();
  const at = cookies.find((c) => c.name === 'nexus_at');
  expect(at, 'nexus_at cookie 應該已經種咗').toBeTruthy();
  expect(at?.httpOnly, 'nexus_at 一定要 HttpOnly').toBe(true);
  const leaked = await page.evaluate(() => JSON.stringify(localStorage));
  expect(leaked.includes('eyJ'), 'localStorage 唔准有 JWT').toBe(false);
}

/** 登出：清 cookie（唔再靠清 localStorage） */
export async function logout(page: Page): Promise<void> {
  await page.context().clearCookies();
  await page.evaluate(() => localStorage.clear());
}
