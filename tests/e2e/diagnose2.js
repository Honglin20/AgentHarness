/**
 * Diagnostic test 2: trigger workflow run and capture errors.
 */
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  // Capture ALL console messages and errors
  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      console.log(`[CONSOLE ERROR] ${msg.text()}`);
    }
  });
  page.on('pageerror', (err) => {
    console.log(`[PAGE ERROR] ${err.message}`);
    console.log(`  Stack: ${err.stack?.substring(0, 500)}`);
  });

  // Capture network errors
  page.on('requestfailed', (req) => {
    console.log(`[NET FAIL] ${req.method()} ${req.url()} — ${req.failure()?.errorText}`);
  });

  await page.goto('http://localhost:8000', { waitUntil: 'networkidle' });
  console.log('1. Page loaded');

  // Select workflow
  await page.locator('select').selectOption('code_review');
  console.log('2. Selected code_review');

  await page.waitForTimeout(500);

  // Enter task
  await page.locator('input[placeholder*="agents"]').fill('Say hi');
  console.log('3. Entered task');

  // Click Run
  await page.locator('button:has-text("Run Workflow")').click();
  console.log('4. Clicked Run');

  // Wait for things to happen
  await page.waitForTimeout(8000);

  // Check what happened
  const bodyText = await page.textContent('body');
  console.log(`\n5. Body length: ${bodyText.length} chars`);
  console.log(`   Has "Application error": ${bodyText.includes('Application error')}`);
  console.log(`   Has "success": ${bodyText.includes('success')}`);

  // Get any visible error text
  const allText = await page.locator('body').innerText();
  const lines = allText.split('\n').filter((l) => l.trim());
  console.log('\n6. Visible text (first 30 lines):');
  lines.slice(0, 30).forEach((l, i) => console.log(`   ${i}: ${l.substring(0, 150)}`));

  await page.screenshot({ path: '/tmp/agentharness_e2e/diagnose2.png' });
  console.log('\nScreenshot: /tmp/agentharness_e2e/diagnose2.png');

  await browser.close();
})();
