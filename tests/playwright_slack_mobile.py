"""Playwright test: Slack mobile sidebar — validates workspace renders on body."""
from playwright.sync_api import sync_playwright
import sys, re

MOBILE_VP = {"width": 390, "height": 844}
CHROME_PATH = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"


def extract_css():
    with open("venture_engine/dashboard/templates/index.html") as f:
        return "\n".join(re.findall(r'<style[^>]*>(.*?)</style>', f.read(), re.DOTALL))


def build_html(css):
    return f"""<!DOCTYPE html><html class="dark"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<style>
:root{{--sidebar-w:240px;--card:#1e1e2e;--bg:#0f0f17;--bg2:#1a1a2e;--border:rgba(255,255,255,0.08);--text:#e5e5e5;--text2:#a0a0a0;--text3:#666;--accent:#FFB100;--sidebar-bg:#1a1a2e;--sidebar-text:#e5e5e5;--sidebar-border:rgba(255,255,255,0.1);--radius:8px;--shadow:none;--radius-pill:20px;}}
body{{margin:0;font-family:sans-serif;background:var(--bg);color:var(--text);}}
.mobile-menu-btn,.mobile-drawer,.mobile-drawer-overlay,.mobile-topbar-actions{{display:none;}}
{css}
</style></head><body>
<div class="app">
<nav class="sidebar"><div class="sidebar-logo"><span>develeap</span></div></nav>
<main class="main"><div class="main-inner"><div id="ventureList">Loading...</div></div></main>
</div>
<script>
function esc(s) {{ return s; }}
function switchTab() {{}}

function loadSlack() {{
  const el = document.getElementById('ventureList');
  const _isMobile = window.innerWidth <= 768;
  const _wsContainer = _isMobile ? document.body : el;
  const _oldWs = document.querySelector('.sl-workspace');
  if (_oldWs) _oldWs.remove();
  const _wsDiv = document.createElement('div');
  _wsDiv.innerHTML = `<div class="sl-workspace">
    <div class="sl-sidebar-overlay" onclick="_slToggleMobileSidebar()"></div>
    <div class="sl-sidebar">
      <div class="sl-sidebar-header">
        <button onclick="document.querySelector('.sl-workspace').remove();" style="background:none;border:none;color:rgba(255,255,255,.6);font-size:16px;cursor:pointer;">&#8592;</button>
        <span class="sl-sidebar-workspace">develeap</span>
      </div>
      <div class="sl-sidebar-section">
        <div class="sl-ch-item sl-ch-active" onclick="_slackSelectChannel('1')" data-chid="1">
          <span class="sl-ch-item-hash">#</span><span class="sl-ch-item-name">general</span>
        </div>
        <div class="sl-ch-item" onclick="_slackSelectChannel('2')" data-chid="2">
          <span class="sl-ch-item-hash">#</span><span class="sl-ch-item-name">ai-and-ml</span>
        </div>
      </div>
    </div>
    <div class="sl-main">
      <div class="sl-channel-header">
        <button class="sl-mobile-back" onclick="document.querySelector('.sl-workspace').remove();">&#8592;</button>
        <span class="sl-channel-name" id="slChName"># general</span>
        <span class="sl-channel-desc"></span>
        <button class="sl-mobile-hamburger" onclick="_slToggleMobileSidebar()">&#9776;</button>
      </div>
      <div class="sl-content-split"><div class="sl-message-list">
        <div class="sl-msg-wrap"><div class="sl-msg"><div class="sl-body"><span class="sl-author">Viktor</span><div class="sl-text">Hello team</div></div></div></div>
      </div></div>
      <div class="sl-composer"><div class="sl-composer-box">
        <div class="sl-composer-input" contenteditable="true" data-placeholder="Message #general"></div>
        <div class="sl-composer-toolbar"><button class="sl-composer-essential">+</button><button class="sl-composer-send">&#10148;</button></div>
      </div></div>
    </div>
  </div>`;
  _wsContainer.appendChild(_wsDiv.firstElementChild);
  if (!_isMobile) el.innerHTML = '';
}}

function _slToggleMobileSidebar() {{
  const sb = document.querySelector('.sl-sidebar');
  const ov = document.querySelector('.sl-sidebar-overlay');
  if (sb) sb.classList.toggle('sl-sidebar-open');
  if (ov) ov.classList.toggle('open');
}}

function _slackSelectChannel(id) {{
  _slToggleMobileSidebar();
  document.querySelectorAll('.sl-ch-item').forEach(el => el.classList.toggle('sl-ch-active', el.dataset.chid === id));
  const names = {{'1':'general','2':'ai-and-ml'}};
  document.getElementById('slChName').textContent = '# ' + (names[id] || id);
}}

loadSlack();
</script></body></html>"""


def run_test():
    errors = []
    html = build_html(extract_css())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=CHROME_PATH,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        ctx = browser.new_context(viewport=MOBILE_VP, is_mobile=True, has_touch=True, device_scale_factor=2)
        page = ctx.new_page()
        page.set_content(html, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

        vp = page.evaluate("window.innerWidth")
        print(f"Viewport: {{vp}}px")

        # 1. Workspace visible and full-screen
        print("1. Workspace...")
        ws = page.evaluate("""(() => {
            const el = document.querySelector('.sl-workspace');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return {x:r.x, y:r.y, w:r.width, h:r.height, parent:el.parentElement.tagName, zIndex:s.zIndex, pos:s.position};
        })()""")
        if not ws:
            errors.append("FAIL: workspace not in DOM")
            browser.close(); return errors
        print(f"   parent={ws['parent']} pos={ws['pos']} z={ws['zIndex']} x={ws['x']:.0f} y={ws['y']:.0f} w={ws['w']:.0f} h={ws['h']:.0f}")
        if ws['parent'] != 'BODY':
            errors.append(f"FAIL: workspace parent is {ws['parent']}, expected BODY")
        if ws['w'] < 380: errors.append(f"FAIL: workspace too narrow ({ws['w']:.0f})")
        if ws['x'] > 2: errors.append(f"FAIL: workspace x={ws['x']:.0f}")

        page.screenshot(path="/tmp/slack_test_1.png")

        # 2. Sidebar hidden
        print("2. Sidebar hidden...")
        sb = page.evaluate("""(() => {
            const el = document.querySelector('.sl-sidebar');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {x:r.x, w:r.width};
        })()""")
        if sb and sb['x'] >= 0 and sb['w'] > 50:
            errors.append(f"FAIL: sidebar visible (x={sb['x']:.0f})")
        else:
            print(f"   Hidden at x={sb['x']:.0f}: OK")

        # 3-5. Header elements
        for name, sel in [("Back", ".sl-mobile-back"), ("Hamburger", ".sl-mobile-hamburger"), ("Channel name", ".sl-channel-name")]:
            info = page.evaluate(f"""(() => {{
                const el = document.querySelector('{sel}');
                if (!el) return null;
                const s = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return {{display:s.display, w:r.width, h:r.height, x:r.x, y:r.y, text:el.textContent}};
            }})()""")
            if info and info['display'] != 'none' and info['w'] > 0:
                print(f"3-5. {name}: '{info.get('text','')}' at x={info['x']:.0f}: OK")
            else:
                errors.append(f"FAIL: {name} not visible ({info})")

        # 6. Open drawer
        print("6. Open drawer...")
        page.evaluate("_slToggleMobileSidebar()")
        page.wait_for_timeout(400)
        sb_open = page.evaluate("""(() => {
            const el = document.querySelector('.sl-sidebar');
            const r = el.getBoundingClientRect();
            return {hasOpen: el.className.includes('sl-sidebar-open'), x:r.x, w:r.width};
        })()""")
        if sb_open['hasOpen'] and sb_open['x'] >= 0:
            print(f"   Drawer open at x={sb_open['x']:.0f} w={sb_open['w']:.0f}: OK")
        else:
            errors.append(f"FAIL: drawer not open ({sb_open})")
        page.screenshot(path="/tmp/slack_test_2_drawer.png")

        # 7. Click channel
        print("7. Switch channel...")
        page.evaluate("_slackSelectChannel('2')")
        page.wait_for_timeout(400)
        closed = page.evaluate("!document.querySelector('.sl-sidebar').className.includes('sl-sidebar-open')")
        ch = page.evaluate("document.getElementById('slChName').textContent")
        if closed and 'ai-and-ml' in ch:
            print(f"   Channel='{ch}', drawer closed: OK")
        else:
            errors.append(f"FAIL: channel switch (closed={closed}, ch='{ch}')")
        page.screenshot(path="/tmp/slack_test_3_switched.png")

        # 8. No sidebar-nav leak
        print("8. No leaks...")
        leaked = page.evaluate("""(() => {
            for (const el of document.querySelectorAll('.sidebar-nav-item,.sidebar-nav,.sidebar-btn')) {
                const s = getComputedStyle(el);
                if (s.display !== 'none') { const r = el.getBoundingClientRect(); if (r.width > 0 && r.x >= 0) return el.textContent.trim(); }
            }
            return null;
        })()""")
        if leaked:
            errors.append(f"FAIL: sidebar element leaked: '{leaked}'")
        else:
            print("   No leaks: OK")

        browser.close()
    return errors


if __name__ == "__main__":
    print("=" * 60)
    print("SLACK MOBILE TEST")
    print("=" * 60)
    errors = run_test()
    print("\n" + "=" * 60)
    if errors:
        print(f"FAILED — {len(errors)} error(s):")
        for e in errors: print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print("ALL TESTS PASSED")
        sys.exit(0)
