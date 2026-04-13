import { chromium } from 'playwright';

const BASE = 'https://web-production-ba45.up.railway.app';
const VIDEO_ID = 'erV_8yrGMA8';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });

  // Track every time a spinner becomes visible
  const spinnerEvents = [];

  console.log('=== Test: Hard refresh — open YouTube video with cached data ===\n');

  // Load page fresh (simulates hard refresh — no JS state)
  await page.goto(BASE + '/#news', { waitUntil: 'networkidle', timeout: 60000 });
  await page.waitForTimeout(2000);

  // Find the YouTube card
  const ytCard = await page.evaluate(() => {
    const cards = document.querySelectorAll('.news-reader-card[data-url]');
    for (const c of cards) {
      if ((c.dataset.url || '').includes('youtu')) return { url: c.dataset.url, title: c.dataset.title || '' };
    }
    return null;
  });

  if (!ytCard) { console.log('No YouTube card found'); await browser.close(); return; }
  console.log('Video:', ytCard.title.slice(0, 60));

  // Set up MutationObserver to track spinner visibility BEFORE opening reader
  await page.evaluate(() => {
    window._spinnerLog = [];
    window._spinnerObserver = new MutationObserver((mutations) => {
      for (const m of mutations) {
        if (m.type === 'attributes' && m.attributeName === 'class') {
          const el = m.target;
          if (el.classList.contains('yt-tab')) {
            const tab = el.dataset.tab;
            const isLoading = el.classList.contains('loading');
            const isReady = el.classList.contains('ready');
            const isFailed = el.classList.contains('failed');
            window._spinnerLog.push({
              time: performance.now().toFixed(0),
              tab,
              state: isLoading ? 'LOADING' : isReady ? 'ready' : isFailed ? 'failed' : 'none'
            });
          }
        }
      }
    });
  });

  // Open the reader
  const openTime = Date.now();
  await page.evaluate((d) => {
    // Start observing after a microtask to catch the initial state
    setTimeout(() => {
      document.querySelectorAll('.yt-tab').forEach(el => {
        window._spinnerObserver.observe(el, { attributes: true, attributeFilter: ['class'] });
      });
    }, 0);
    openReader(d.url, d.title, '');
  }, ytCard);

  // Log initial tab states right after open
  await page.waitForTimeout(100);
  const initialStates = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('.yt-tab')).map(el => ({
      tab: el.dataset.tab,
      classes: el.className,
      isLoading: el.classList.contains('loading'),
      isReady: el.classList.contains('ready'),
    }));
  });
  console.log('\nInitial tab states (100ms after open):');
  initialStates.forEach(s => {
    const icon = s.isLoading ? '⏳ SPINNER' : s.isReady ? '✅ ready' : '⚪ none';
    console.log(`  ${s.tab}: ${icon}`);
  });

  // Wait for data to load
  await page.waitForTimeout(5000);

  const after5s = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('.yt-tab')).map(el => ({
      tab: el.dataset.tab,
      isLoading: el.classList.contains('loading'),
      isReady: el.classList.contains('ready'),
      isFailed: el.classList.contains('failed'),
    }));
  });
  console.log('\nTab states after 5s:');
  after5s.forEach(s => {
    const icon = s.isLoading ? '⏳ SPINNER' : s.isReady ? '✅ ready' : s.isFailed ? '❌ failed' : '⚪ none';
    console.log(`  ${s.tab}: ${icon}`);
  });

  // Get the mutation log
  const log = await page.evaluate(() => window._spinnerLog);
  console.log('\nSpinner state transitions:');
  if (log.length === 0) {
    console.log('  (no transitions observed)');
  } else {
    log.forEach(e => {
      const icon = e.state === 'LOADING' ? '⏳' : e.state === 'ready' ? '✅' : e.state === 'failed' ? '❌' : '⚪';
      console.log(`  ${e.time}ms  ${e.tab}  →  ${icon} ${e.state}`);
    });
  }

  // Check if any spinner was visible at any point
  const hadSpinners = log.some(e => e.state === 'LOADING' && (e.tab === 'takeaways' || e.tab === 'dpoi'));
  console.log('\n' + (hadSpinners ? '❌ FAIL: Takeaways/DOPI spinners were shown!' : '✅ PASS: No spinners for takeaways/DOPI'));

  // Take screenshot
  await page.screenshot({ path: '/Users/dorikafri/GoldenGoose/evidence_no_spinners.png', fullPage: false });
  console.log('\nScreenshot saved: evidence_no_spinners.png');

  await browser.close();
})();
