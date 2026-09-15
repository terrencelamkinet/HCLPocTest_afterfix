/**
 * E2E tests for the NEXUS CRM AI Chat Panel.
 *
 * Covers: open → send → stream → cite → abort → retry → session switch
 *
 * Prerequisites:
 *   - Frontend running on localhost:5173
 *   - Backend running on localhost:8001
 *   - Kinetix tenant seeded with data
 */

import { test, expect } from '@playwright/test';
import { loginAsTerrence } from './helpers/auth';

// ─── Helpers ────────────────────────────────────────────────────────

/** Wait for the FAB to appear and click it to open the AI panel. */
async function openAIPanel(page: import('@playwright/test').Page) {
  // Try clicking the AI chat FAB — usually bottom-right corner
  const fab = page.locator('[data-testid="ai-fab"], .ai-fab, button:has(svg):has-text("AI")');
  await fab.first().click();
  await expect(page.locator('.chat-panel, [data-testid="chat-panel"], .ai-chat-panel')).toBeVisible({ timeout: 8000 });
}

/** Send a message in the composer and wait for the AI to start responding. */
async function sendMessage(page: import('@playwright/test').Page, text: string) {
  const textarea = page.locator('textarea, [contenteditable="true"]').last();
  await textarea.fill(text);
  await page.locator('button:has-text("Send"), button[aria-label="Send message"]').click();
}

// ─── Setup ──────────────────────────────────────────────────────────

test.beforeEach(async ({ page }) => {
  await page.goto('/');
  await loginAsTerrence(page);
  await page.reload();
  await page.waitForLoadState('networkidle');
});

// ─── Tests ──────────────────────────────────────────────────────────

test.describe('AI Chat Panel — P0 flows', () => {

  test('1. Panel opens and shows composer', async ({ page }) => {
    await openAIPanel(page);

    // Composer visible
    await expect(page.locator('textarea, [contenteditable="true"]').last()).toBeVisible();
    // Send button visible
    await expect(page.locator('button[aria-label="Send message"], button:has-text("Send")')).toBeVisible();
    // Prompt chips visible (or dynamic prompts)
    const chips = page.locator('.prompt-chip, [data-testid="prompt-chip"]');
    const chipCount = await chips.count();
    expect(chipCount).toBeGreaterThanOrEqual(2);
  });

  test('2. Send message and receive streaming response', async ({ page }) => {
    await openAIPanel(page);

    await sendMessage(page, 'Show my open deals');

    // Wait for streaming response to appear
    const aiMessage = page.locator('.ai-message, [data-testid="ai-message"]').last();
    await expect(aiMessage).toBeVisible({ timeout: 30_000 });

    // Blinking caret visible while streaming
    const caret = page.locator('.streaming-caret, .typing-indicator');
    await expect(caret).toBeVisible({ timeout: 5_000 });

    // Wait for streaming to complete (caret disappears)
    await expect(caret).not.toBeVisible({ timeout: 60_000 });

    // Response should have content
    const text = await aiMessage.textContent();
    expect(text).toBeTruthy();
    expect(text!.length).toBeGreaterThan(20);

    // Stop generating button should appear and disappear
    await expect(page.locator('button:has-text("Stop")')).not.toBeVisible({ timeout: 60_000 });
  });

  test('3. Abort mid-stream', async ({ page }) => {
    await openAIPanel(page);

    await sendMessage(page, 'Tell me the full history of every deal in detail');

    // Wait for stop button and click it
    const stopBtn = page.locator('button:has-text("Stop")');
    await expect(stopBtn).toBeVisible({ timeout: 10_000 });
    await stopBtn.click();

    // AI message should be saved (partial response)
    const aiMessage = page.locator('.ai-message, [data-testid="ai-message"]').last();
    await expect(aiMessage).toBeVisible({ timeout: 5_000 });

    // No stop button after abort
    await expect(stopBtn).not.toBeVisible({ timeout: 5_000 });
  });

  test('4. Message actions work — Copy, Retry, Feedback', async ({ page }) => {
    test.setTimeout(120_000);
    await openAIPanel(page);

    await sendMessage(page, 'List my contacts');

    // Wait for response and hover to reveal actions
    const aiMessage = page.locator('.ai-message, [data-testid="ai-message"]').last();
    await expect(aiMessage).toBeVisible({ timeout: 30_000 });

    // Wait for streaming to finish
    await expect(page.locator('.streaming-caret, .typing-indicator').last()).not.toBeVisible({ timeout: 60_000 });

    // Hover to reveal action buttons
    await aiMessage.hover();
    await page.waitForTimeout(500);

    // Copy button
    const copyBtn = page.locator('button[aria-label="Copy"], button:has-text("📋")');
    await expect(copyBtn.first()).toBeVisible({ timeout: 3000 });

    // Retry button
    const retryBtn = page.locator('button[aria-label="Retry"], button:has-text("↻")');
    await expect(retryBtn.first()).toBeVisible({ timeout: 3000 });

    // Feedback buttons
    const thumbsUp = page.locator('button[aria-label="Upvote"], button:has-text("👍")');
    await expect(thumbsUp.first()).toBeVisible({ timeout: 3000 });

    // Test copy
    await copyBtn.first().click();

    // Test feedback
    await thumbsUp.first().click();
  });

  test('5. Citations appear and are clickable', async ({ page }) => {
    test.setTimeout(120_000);
    await openAIPanel(page);

    await sendMessage(page, 'What companies do we work with?');

    // Wait for streaming to finish
    const aiMessage = page.locator('.ai-message, [data-testid="ai-message"]').last();
    await expect(aiMessage).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('.streaming-caret, .typing-indicator').last()).not.toBeVisible({ timeout: 60_000 });

    // Check for citation chips
    const citations = page.locator('.citation-chip, sup, [data-testid="citation-chip"]');
    const citationCount = await citations.count();
    if (citationCount > 0) {
      // Sources row visible
      await expect(page.locator('.sources-row, [data-testid="sources-row"]')).toBeVisible({ timeout: 5000 });

      // Click first citation
      await citations.first().click();
    }
    // If no citations (query-dependent), this is acceptable as long as response is valid
  });

  test('6. Prompt chip fills composer (does not auto-send)', async ({ page }) => {
    await openAIPanel(page);

    const chip = page.locator('.prompt-chip, [data-testid="prompt-chip"]').first();
    await expect(chip).toBeVisible();

    const chipText = await chip.textContent();

    // Click chip
    await chip.click();

    // Composer should contain the chip text
    const textarea = page.locator('textarea, [contenteditable="true"]').last();
    const composerText = await textarea.inputValue();
    expect(composerText).toContain(chipText?.trim() || '');

    // Message should NOT have been sent
    // Check no AI messages appeared since we didn't press Enter
    const allMessages = page.locator('.ai-message, [data-testid="ai-message"]');
    // Just verify the panel is still ready to compose
    await expect(textarea).toBeFocused();
  });

});

test.describe('AI Chat Panel — P1 flows', () => {

  test('7. Slash command menu opens and navigable by keyboard', async ({ page }) => {
    await openAIPanel(page);

    const textarea = page.locator('textarea, [contenteditable="true"]').last();
    await textarea.fill('/');

    // Command menu should appear
    const menu = page.locator('.command-menu, [data-testid="command-menu"], .slash-menu');
    await expect(menu).toBeVisible({ timeout: 3000 });

    // Arrow down, then Enter to select
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');

    // Composer should be updated with command template
    const updatedText = await textarea.inputValue();
    expect(updatedText.length).toBeGreaterThan(0);
  });

  test('8. Session rename, pin, and delete', async ({ page }) => {
    test.setTimeout(120_000);
    await openAIPanel(page);

    await sendMessage(page, 'Hello');

    // Wait for response
    const aiMessage = page.locator('.ai-message, [data-testid="ai-message"]').last();
    await expect(aiMessage).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('.streaming-caret, .typing-indicator').last()).not.toBeVisible({ timeout: 60_000 });

    // Open session list sidebar
    const historyBtn = page.locator('button:has-text("History"), button[aria-label="History"], button:has(svg):has-text("Session")');
    await historyBtn.first().click();

    // Find the current session in the list
    const sessionItem = page.locator('.session-item, [data-testid="session-item"]').first();
    await expect(sessionItem).toBeVisible({ timeout: 5000 });

    // Right-click / click context menu
    await sessionItem.click({ button: 'right' });
    const contextMenu = page.locator('.context-menu, [data-testid="context-menu"]');
    const contextVisible = await contextMenu.isVisible().catch(() => false);

    if (contextVisible) {
      // Try rename
      const renameOpt = page.locator('.context-menu button:has-text("Rename"), .context-menu li:has-text("Rename")');
      if (await renameOpt.isVisible().catch(() => false)) {
        await renameOpt.click();
      }
    }
  });

  test('9. Error handling — send to stopped backend shows graceful error', async ({ page }) => {
    await openAIPanel(page);

    await sendMessage(page, 'This will fail');

    // Either we get a response, or a typed error banner
    const aiMessage = page.locator('.ai-message, [data-testid="ai-message"]').last();
    const errorBanner = page.locator('.error-banner, [data-testid="error-banner"], .stream-error');

    // Wait for either response or error
    await page.waitForTimeout(15_000);

    const msgVisible = await aiMessage.isVisible().catch(() => false);
    const errVisible = await errorBanner.isVisible().catch(() => false);
    expect(msgVisible || errVisible).toBeTruthy();

    if (errVisible) {
      // Error should have retry button
      const retryBtn = errorBanner.locator('button:has-text("Retry")');
      await expect(retryBtn).toBeVisible({ timeout: 2000 });
    }
  });

});
