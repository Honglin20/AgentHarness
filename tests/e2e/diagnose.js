/**
 * Diagnostic test: capture browser console errors to find root cause.
 */
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  // Capture ALL console messages
  const logs = [];
  page.on('console', (msg) => {
    logs.push(`[${msg.type()}] ${msg.text()}`);
  });
  page.on('pageerror', (err) => {
    logs.push(`[PAGE ERROR] ${err.message}`);
  });

  await page.goto('http://localhost:8000', { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);

  console.log('=== Console messages ===');
  logs.forEach((l) => console.log(l));

  // Check if error overlay is visible
  const bodyText = await page.textContent('body');
  console.log('\n=== Body contains ===');
  if (bodyText.includes('Application error')) {
    console.log('Found "Application error" in body');
    // Try to get more details from the error overlay
    const errorDetails = await page.textContent('[class*="error"]');
    console.log('Error details:', errorDetails);
    const nextError = await page.textContent('nextjs-portal');
    console.log('Next.js portal:', nextError);
  }

  // Get the full HTML
  const html = await page.content();
  // Find error sections
  const errorMatch = html.match(/Application error:.*?(?=<)/s);
  if (errorMatch) {
    console.log('\nFull error message:', errorMatch[0]);
  }

  await page.screenshot({ path: '/tmp/agentharness_e2e/diagnostic.png' });
  console.log('\nScreenshot saved to /tmp/agentharness_e2e/diagnostic.png');

  await browser.close();
})();
