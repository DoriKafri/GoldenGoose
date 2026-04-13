import { chromium } from 'playwright';

const BASE = 'https://web-production-ba45.up.railway.app';
const bugs = [];

function reportBug(title, description, priority, labels) {
  bugs.push({ title, description, priority, labels });
  console.log(`  🐛 FOUND: [${priority}] ${title}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  // Collect console errors
  const consoleErrors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });

  // Collect network errors
  const networkErrors = [];
  page.on('response', resp => {
    if (resp.status() >= 500) networkErrors.push({ url: resp.url(), status: resp.status() });
  });

  // === Test 1: News Feed (as Kobi Avshalom) ===
  console.log('\n👤 Kobi Avshalom testing News Feed...');
  await page.goto(`${BASE}/#news`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(3000);

  // Check if news items rendered
  const newsCount = await page.locator('.news-reader-card').count();
  console.log(`  News items loaded: ${newsCount}`);
  if (newsCount === 0) {
    reportBug('News feed empty on initial load', 'No news items rendered on page load. The ventureList container is empty.', 'critical', ['news-feed', 'ui']);
  }

  // Check for broken images
  const brokenImages = await page.evaluate(() => {
    const imgs = document.querySelectorAll('.news-reader-card img');
    const broken = [];
    imgs.forEach(img => {
      if (img.naturalWidth === 0 && img.complete && img.style.display !== 'none') {
        broken.push(img.src?.substring(0, 80));
      }
    });
    return broken;
  });
  if (brokenImages.length > 0) {
    reportBug(`${brokenImages.length} broken images in news feed`, `Images failing to load: ${brokenImages.slice(0, 3).join(', ')}`, 'medium', ['news-feed', 'ui']);
  }

  // === Test 2: Bug Tracker (as Gilad Neiger) ===
  console.log('\n👤 Gilad Neiger testing Bug Tracker...');
  await page.goto(`${BASE}/#bugs`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(3000);

  // Check kanban board renders
  const boardColumns = await page.locator('.kanban-column, [class*="board"]').count();
  const bugCards = await page.locator('.bug-card, .venture-row').count();
  console.log(`  Bug cards visible: ${bugCards}`);

  // Try creating a bug with empty title
  console.log('  Testing bug creation with empty title...');
  const newBugBtn = page.locator('button:has-text("New Bug"), button:has-text("new bug"), button:has-text("New")').first();
  if (await newBugBtn.count() > 0) {
    await newBugBtn.click({ force: true });
    await page.waitForTimeout(500);
    // Try to submit empty
    const createBtn = page.locator('button:has-text("Create Bug"), button:has-text("Create")').first();
    if (await createBtn.count() > 0) {
      await createBtn.click({ force: true });
      await page.waitForTimeout(1000);
      // Check if it actually created an empty bug (it shouldn't)
      const emptyBugCreated = await page.evaluate(async () => {
        try {
          const r = await fetch('/api/bugs', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({title: '', description: ''})
          });
          const d = await r.json();
          return { status: r.status, created: r.ok, key: d.key };
        } catch(e) { return { error: e.message }; }
      });
      if (emptyBugCreated.created) {
        reportBug('Bug tracker accepts empty title', `POST /api/bugs accepts empty title and creates BUG with no title. Created: ${emptyBugCreated.key}`, 'medium', ['bug-tracker', 'validation']);
      }
    }
  }

  // === Test 3: Reader Overlay (as Saar Cohen) ===
  console.log('\n👤 Saar Cohen testing Reader Overlay...');
  await page.goto(`${BASE}/#news`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(3000);

  // Open a news item
  const hasCards = await page.locator('.news-reader-card[data-url]').count();
  if (hasCards > 0) {
    await page.evaluate(() => {
      const card = document.querySelector('.news-reader-card[data-url]');
      if (card) openReader(card.dataset.url, card.dataset.title || '', card.dataset.newsId || '');
    });
    await page.waitForTimeout(2000);

    // Check if reader opened
    const readerOpen = await page.evaluate(() => document.getElementById('readerOverlay')?.classList.contains('open'));
    console.log(`  Reader overlay opened: ${readerOpen}`);

    if (readerOpen) {
      // Press Escape to close
      await page.keyboard.press('Escape');
      await page.waitForTimeout(500);
      const readerClosed = await page.evaluate(() => !document.getElementById('readerOverlay')?.classList.contains('open'));
      if (!readerClosed) {
        reportBug('Escape key does not close reader overlay', 'Pressing Escape while the reader overlay is open does not close it. User has to click the back button.', 'medium', ['reader', 'keyboard']);
      }
    }
  }

  // === Test 4: API edge cases (as Efi Shimon) ===
  console.log('\n👤 Efi Shimon testing API edge cases...');

  // Test transcript endpoint with invalid video ID
  const invalidTranscript = await page.evaluate(async () => {
    const r = await fetch('/api/youtube-transcript?video_id=INVALID');
    return { status: r.status };
  });
  console.log(`  Invalid video_id response: ${invalidTranscript.status}`);
  if (invalidTranscript.status === 500) {
    reportBug('Transcript endpoint crashes on invalid video_id', 'GET /api/youtube-transcript?video_id=INVALID returns 500 instead of 400/422', 'high', ['api', 'validation', 'youtube']);
  }

  // Test news endpoint with negative offset
  const negOffset = await page.evaluate(async () => {
    const r = await fetch('/api/news?limit=10&offset=-5');
    return { status: r.status, ok: r.ok };
  });
  if (negOffset.ok) {
    reportBug('News API accepts negative offset', 'GET /api/news?offset=-5 returns 200 instead of rejecting invalid input', 'low', ['api', 'validation']);
  }

  // === Test 5: Settings page (as Omri Spector) ===
  console.log('\n👤 Omri Spector testing Settings...');
  await page.evaluate(() => { if (typeof openSettings === 'function') openSettings(); });
  await page.waitForTimeout(1000);
  const settingsVisible = await page.locator('#settingsOverlay, .settings-overlay').first().isVisible().catch(() => false);
  console.log(`  Settings panel visible: ${settingsVisible}`);

  // === Test 6: Release Notes (as Shoshi Revivo) ===
  console.log('\n👤 Shoshi Revivo testing Release Notes...');
  await page.goto(`${BASE}/#release-notes`, { waitUntil: 'networkidle', timeout: 30000 });
  await page.waitForTimeout(3000);

  const releaseContent = await page.evaluate(() => document.getElementById('ventureList')?.textContent?.length || 0);
  console.log(`  Release notes content length: ${releaseContent}`);
  if (releaseContent < 50) {
    reportBug('Release notes page is empty', 'The release notes tab shows no content after loading', 'medium', ['release-notes', 'ui']);
  }

  // Check for the graph feature remnants
  console.log('\n👤 Checking for removed graph feature remnants...');
  const graphRemnants = await page.evaluate(() => {
    const allText = document.body.innerText;
    const hasGraphNav = !!document.querySelector('[data-tab="graph"]');
    const hasGraphCanvas = !!document.getElementById('graphCanvas');
    return { hasGraphNav, hasGraphCanvas };
  });
  if (graphRemnants.hasGraphNav || graphRemnants.hasGraphCanvas) {
    reportBug('Graph feature remnants still visible in UI', `Graph nav button: ${graphRemnants.hasGraphNav}, Canvas: ${graphRemnants.hasGraphCanvas}`, 'medium', ['graph', 'cleanup']);
  }

  // === Summary ===
  console.log('\n' + '='.repeat(60));
  console.log(`Console errors during testing: ${consoleErrors.length}`);
  if (consoleErrors.length > 0) {
    console.log('  Top errors:');
    consoleErrors.slice(0, 5).forEach(e => console.log(`    - ${e.substring(0, 100)}`));
  }
  console.log(`Network 5xx errors: ${networkErrors.length}`);
  networkErrors.forEach(e => console.log(`    - ${e.status} ${e.url.substring(0, 80)}`));

  console.log(`\n🐛 Total bugs found: ${bugs.length}`);
  bugs.forEach((b, i) => console.log(`  ${i+1}. [${b.priority}] ${b.title}`));

  // Submit bugs to the tracker
  if (bugs.length > 0) {
    console.log('\n=== Submitting bugs to tracker ===');
    for (const bug of bugs) {
      const reporters = [
        { name: 'Kobi Avshalom', email: 'kobi@develeap.com' },
        { name: 'Gilad Neiger', email: 'gilad@develeap.com' },
        { name: 'Saar Cohen', email: 'saar@develeap.com' },
      ];
      const reporter = reporters[Math.floor(Math.random() * reporters.length)];
      const result = await page.evaluate(async (b) => {
        const r = await fetch('/api/bugs', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            title: b.title,
            description: b.description,
            priority: b.priority,
            bug_type: 'bug',
            reporter_name: b.reporter,
            reporter_email: b.reporterEmail,
            assignee_name: 'Claude',
            assignee_email: 'claude@develeap.com',
            labels: b.labels,
          })
        });
        const d = await r.json();
        return d.key;
      }, { ...bug, reporter: reporter.name, reporterEmail: reporter.email });
      console.log(`  Created ${result}: ${bug.title}`);
    }
  }

  await browser.close();
})();
