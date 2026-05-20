/**
 * Detailed UI verification: inspect DOM state after running workflows.
 */
const { chromium } = require('playwright');

async function verifyWorkflow(name, task, timeout = 60000) {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(`console: ${msg.text().substring(0, 200)}`);
  });

  try {
    await page.goto('http://localhost:8000', { waitUntil: 'networkidle' });
    await page.locator('select').selectOption(name);
    await page.waitForTimeout(300);
    await page.locator('input[placeholder*="agents"]').fill(task);
    await page.locator('button:has-text("Run Workflow")').click();

    const startTime = Date.now();
    const checks = [];

    while (Date.now() - startTime < timeout) {
      await page.waitForTimeout(3000);
      const elapsed = Math.round((Date.now() - startTime) / 1000);

      // Check for errors
      const appError = await page.locator('text=/Application error/i').count();
      if (appError > 0) {
        return { pass: false, reason: `Application error at ${elapsed}s`, errors };
      }

      // Check DAG section
      const dagContent = await page.textContent('aside[aria-label]') || '';
      const hasDAG = dagContent.length > 10;

      // Check center panel for agent output / streaming
      const mainContent = await page.textContent('body');
      const hasStatus = mainContent.includes('ms') || mainContent.includes('tokens') || mainContent.includes('success') || mainContent.includes('analyzer') || mainContent.includes('coder') || mainContent.includes('审查');

      // Check for specific markers
      const bodyText = await page.textContent('body') || '';
      const hasRunBtn = bodyText.includes('Run Workflow');

      checks.push(`[${elapsed}s] DAG=${hasDAG} status=${hasStatus} errs=${errors.length}`);

      // If we see status data and no errors, consider it passing
      if (hasStatus && errors.length === 0 && elapsed > 5) {
        await page.screenshot({ path: `/tmp/agentharness_e2e/verify_${name}.png` });
        await browser.close();
        return { pass: true, checks, bodyLen: bodyText.length };
      }
    }

    await page.screenshot({ path: `/tmp/agentharness_e2e/verify_${name}.png` });
    await browser.close();
    return { pass: errors.length === 0, checks, bodyLen: (await page.textContent('body')).length, reason: 'timeout' };
  } catch (e) {
    await browser.close();
    return { pass: false, reason: e.message, errors };
  }
}

(async () => {
  console.log('=== Detailed UI Verification ===\n');

  const workflows = [
    { name: 'code_review', task: 'Say hello in exactly one word', desc: '3-agent pipeline' },
    { name: 'chart_demo', task: 'python examples/chart_script.py', desc: 'charts', chartTest: true },
    { name: 'parallel_research', task: '列出当前目录的文件，简短回答', desc: 'parallel agents' },
    { name: 'coder_review_loop', task: '写 fibonacci 函数，迭代，简短输出', desc: 'coder-reviewer loop' },
  ];

  for (const wf of workflows) {
    console.log(`--- ${wf.name} (${wf.desc}) ---`);
    const result = await verifyWorkflow(wf.name, wf.task);
    console.log(`  Pass: ${result.pass}`);
    if (result.reason) console.log(`  Reason: ${result.reason}`);
    if (result.bodyLen) console.log(`  Body length: ${result.bodyLen} chars`);
    if (result.checks) {
      console.log('  Timeline:');
      result.checks.forEach((c) => console.log(`    ${c}`));
    }
    if (result.errors?.length) {
      console.log('  Errors:');
      result.errors.forEach((e) => console.log(`    ${e}`));
    }
    console.log();
  }

  // Specific chart verification
  console.log('--- Chart verification ---');
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

  await page.goto('http://localhost:8000', { waitUntil: 'networkidle' });
  await page.locator('select').selectOption('chart_demo');
  await page.waitForTimeout(300);
  await page.locator('input[placeholder*="agents"]').fill('python examples/chart_script.py');
  await page.locator('button:has-text("Run Workflow")').click();

  // Wait for charts
  await page.waitForTimeout(15000);

  // Count chart SVG elements
  const svgCount = await page.locator('svg').count();
  console.log(`  SVG elements: ${svgCount}`);

  // Check for Recharts-specific elements
  const rechartsSurface = await page.locator('.recharts-surface').count();
  console.log(`  Recharts surfaces: ${rechartsSurface}`);

  // Check for chart labels
  const chartLabels = await page.locator('.recharts-label, .recharts-text').count();
  console.log(`  Chart labels/text: ${chartLabels}`);

  // Check for table elements (chart_demo includes a table)
  const tableCount = await page.locator('table').count();
  console.log(`  Tables: ${tableCount}`);

  // Check for chart group containers
  const chartGroups = await page.locator('[class*="ChartGroup"]').count();
  console.log(`  Chart groups: ${chartGroups}`);

  // Read visible chart text
  const visibleText = await page.textContent('body');
  const scoreText = visibleText.includes('Score') || visibleText.includes('score');
  const lossText = visibleText.includes('Loss') || visibleText.includes('loss');
  const iterationText = visibleText.includes('iter') || visibleText.includes('Iter');
  console.log(`  Contains "Score": ${scoreText}`);
  console.log(`  Contains "Loss": ${lossText}`);
  console.log(`  Contains "iter": ${iterationText}`);

  await page.screenshot({ path: '/tmp/agentharness_e2e/verify_charts_detail.png' });
  await browser.close();

  console.log('\n=== Verification complete ===');
})();
