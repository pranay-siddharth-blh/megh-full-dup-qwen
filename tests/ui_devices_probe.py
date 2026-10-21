"""Cross-device functional probe for /megh-chat (run after every UI change).

Usage: py -3 tests/ui_devices_probe.py [profile ...]   (needs: playwright install chromium webkit firefox)
The 1920px "msg-actions-visible" reading can flake: the fixed composer may
cover the last message where the pointer hovers.


Every profile: sign in, no sideways scroll, composer usable, slash menu, export
menu, language menu (all inside the viewport, close on outside tap/click),
Enter behaviour (keyboard: sends; touch-only: new line), IME Enter never sends,
drawer + history menu on small screens, shortcuts (Ctrl / Cmd per OS) on
keyboard profiles. Screenshots in ./shots.
"""
import json, os, sys, urllib.request
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8401'
OUT = os.environ.get('MEGH_PROBE_SHOTS') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui_device_shots')
os.makedirs(OUT, exist_ok=True)

# A JWT for any active user: export MEGH_JWT, or let this mint a 2-hour one
# with the app's own signer (run from the repo root with the .venv python).
TOKEN = os.environ.get('MEGH_JWT', '')
if not TOKEN:
    # Playwright lives in the system python, the app in .venv: mint through .venv.
    import subprocess
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    MINT = '''
import asyncio, sys
from app import appdb, security
async def m():
    r = await appdb.get_user_by_username(sys.argv[1])
    print(security.issue_token({'sub': str(r['user_id']), 'username': r['username'],
                                'tenant_id': r['tenant_id'], 'role': r['role']}, ttl_minutes=120))
asyncio.run(m())
'''
    venv_py = os.path.join(ROOT, '.venv', 'Scripts', 'python.exe')
    if not os.path.exists(venv_py):
        venv_py = os.path.join(ROOT, '.venv', 'bin', 'python')
    out = subprocess.run([venv_py, '-c', MINT, os.environ.get('MEGH_PROBE_USER', 'state-rd')],
                         cwd=ROOT, capture_output=True, text=True)
    TOKEN = (out.stdout.strip().splitlines() or [''])[-1]
assert TOKEN, 'login failed'

WIN = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36'
LINUX_FF = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0'
MAC_SAFARI = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15'

# (name, engine, playwright device or None, extra ctx options, keyboard OS: 'win'|'mac'|None for touch-only)
PROFILES = [
    ('android-small-320', 'chromium', None, dict(viewport={'width': 320, 'height': 640}, is_mobile=True, has_touch=True, device_scale_factor=2), None),
    ('iphone-se', 'webkit', 'iPhone SE', {}, None),
    ('iphone-15-pro-max', 'webkit', 'iPhone 15 Pro Max', {}, None),
    ('iphone-15-landscape', 'webkit', 'iPhone 15 landscape', {}, None),
    ('pixel-7', 'chromium', 'Pixel 7', {}, None),
    ('galaxy-s9', 'chromium', 'Galaxy S9+', {}, None),
    ('ipad-mini', 'webkit', 'iPad Mini', {}, None),
    ('ipad-pro-landscape', 'webkit', 'iPad Pro 11 landscape', {}, None),
    ('galaxy-tab-s4', 'chromium', 'Galaxy Tab S4', {}, None),
    ('windows-1024', 'chromium', None, dict(viewport={'width': 1024, 'height': 700}, user_agent=WIN), 'win'),
    ('windows-1366', 'chromium', None, dict(viewport={'width': 1366, 'height': 768}, user_agent=WIN), 'win'),
    ('windows-1920', 'chromium', None, dict(viewport={'width': 1920, 'height': 1080}, user_agent=WIN), 'win'),
    ('ubuntu-firefox-1280', 'firefox', None, dict(viewport={'width': 1280, 'height': 800}, user_agent=LINUX_FF), 'win'),
    ('ubuntu-firefox-820', 'firefox', None, dict(viewport={'width': 820, 'height': 1000}, user_agent=LINUX_FF), 'win'),
    ('mac-safari-1440', 'webkit', None, dict(viewport={'width': 1440, 'height': 900}, user_agent=MAC_SAFARI), 'mac'),
    ('mac-safari-1280', 'webkit', None, dict(viewport={'width': 1280, 'height': 800}, user_agent=MAC_SAFARI), 'mac'),
]
only = sys.argv[1:]

INSIDE = """(sel) => { const el = document.querySelector(sel); if (!el) return 'missing';
  const r = el.getBoundingClientRect(); const W = innerWidth, H = innerHeight;
  if (r.width === 0 || r.height === 0) return 'hidden';
  return (r.left >= -1 && r.right <= W + 1 && r.top >= -1 && r.bottom <= H + 1) ? 'ok'
    : `out ${Math.round(r.left)},${Math.round(r.top)},${Math.round(r.right)},${Math.round(r.bottom)} vs ${W}x${H}`; }"""
OVERFLOW = """() => { const d = document.documentElement; const W = d.clientWidth; const bad = [];
  if (d.scrollWidth > W + 1) bad.push('doc ' + d.scrollWidth + '>' + W);
  for (const el of document.querySelectorAll('.app *')) {
    const r = el.getBoundingClientRect(); if (!r.width) continue;
    let p = el.parentElement, clipped = false;
    while (p && p !== document.body) { const o = getComputedStyle(p).overflowX; if (o !== 'visible') { clipped = true; break; } p = p.parentElement; }
    if (!clipped && r.right > W + 1 && getComputedStyle(el).position !== 'fixed') bad.push((el.className || el.tagName).toString().slice(0, 40) + ' ' + Math.round(r.right));
    if (bad.length > 5) break; }
  return bad; }"""


def run(p, name, engine, device, extra, kb):
    res = {}
    b = getattr(p, engine).launch()
    opts = dict(p.devices[device]) if device else {}
    if engine == 'firefox':
        opts.pop('is_mobile', None)
    opts.update(extra)
    ctx = b.new_context(bypass_csp=True, **opts)
    ctx.add_init_script(f"try{{localStorage.setItem('megh_jwt',{json.dumps(TOKEN)})}}catch(e){{}}")
    pg = ctx.new_page()
    errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)[:120]))
    pg.goto(BASE + '/megh-chat', wait_until='networkidle')
    pg.wait_for_selector('.composer-input', timeout=15000)
    pg.wait_for_timeout(600)
    touch = kb is None
    W = pg.viewport_size['width']

    def tap(sel):
        if touch:
            pg.tap(sel)
        else:
            pg.click(sel)

    def outside():
        x, y = 5, pg.viewport_size['height'] // 2 if W > 880 else 200
        if touch:
            pg.touchscreen.tap(W // 2, 300)
        else:
            pg.mouse.click(W // 2, 300)
        pg.wait_for_timeout(250)

    res['overflow'] = pg.evaluate(OVERFLOW) or 'ok'
    res['composer'] = pg.evaluate(INSIDE, '.composer')
    res['send'] = pg.evaluate(INSIDE, '.send-btn')
    pg.screenshot(path=os.path.join(OUT, f'{name}_home.png'))

    # Slash menu
    pg.fill('.composer-input', '/')
    pg.wait_for_timeout(250)
    res['slash'] = pg.evaluate(INSIDE, '.slash-menu')
    pg.fill('.composer-input', '')

    # IME: Enter while composing must not send.
    before = pg.evaluate("document.querySelectorAll('.msg.user').length")
    pg.focus('.composer-input'); pg.fill('.composer-input', 'नमस्ते')
    pg.evaluate("""() => { const t = document.querySelector('.composer-input');
      t.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', keyCode: 229, isComposing: true, bubbles: true})); }""")
    pg.wait_for_timeout(300)
    res['ime-enter'] = 'ok' if pg.evaluate("document.querySelectorAll('.msg.user').length") == before and pg.input_value('.composer-input') else 'SENT'

    # Enter: touch-only -> new line; keyboard -> send.
    pg.fill('.composer-input', 'hi')
    pg.press('.composer-input', 'Enter')
    pg.wait_for_timeout(500)
    after = pg.evaluate("document.querySelectorAll('.msg.user').length")
    if touch:
        res['enter'] = 'newline' if after == before and '\n' in pg.input_value('.composer-input') else f'unexpected sent={after - before}'
        tap('.send-btn')
        pg.wait_for_timeout(500)
        after = pg.evaluate("document.querySelectorAll('.msg.user').length")
        res['send-tap'] = 'ok' if after > before else 'NOT SENT ' + json.dumps(pg.evaluate("(() => { const b = document.querySelector('.send-btn'); return {disabled: b && b.disabled, cls: b && b.className, val: document.querySelector('.composer-input').value, banner: !!document.querySelector('.conn-banner'), users: document.querySelectorAll('.msg.user').length}; })()"))
    else:
        res['enter'] = 'sends' if after > before else 'NOT SENT ' + json.dumps(pg.evaluate("(() => { const b = document.querySelector('.send-btn'); return {disabled: b && b.disabled, cls: b && b.className, val: document.querySelector('.composer-input').value, banner: !!document.querySelector('.conn-banner'), users: document.querySelectorAll('.msg.user').length}; })()"))
    try:
        pg.wait_for_function("!document.querySelector('.send-btn.stop')", timeout=60000)
    except Exception:
        res['answer'] = 'still streaming after 60s'
    pg.wait_for_timeout(500)
    res['overflow-after-answer'] = pg.evaluate(OVERFLOW) or 'ok'
    pg.screenshot(path=os.path.join(OUT, f'{name}_answer.png'))

    # Export and language menus open inside the viewport and close on an outside tap.
    if W <= 880 and pg.evaluate("!!document.querySelector('.app.nav-open')"):
        outside()
    for btn, menu, key in [('.chat-export-btn', '.dl-menu', 'export'), ('.lang-switch-btn', '.lang-menu', 'lang')]:
        if pg.evaluate(f"!document.querySelector('{btn}') || !document.querySelector('{btn}').offsetWidth"):
            res[key] = 'button-hidden'; continue
        if pg.evaluate(f"document.querySelector('{btn}').disabled"):
            res[key] = 'disabled (no chat yet)'; continue
        tap(btn); pg.wait_for_timeout(300)
        inside = pg.evaluate(INSIDE, menu)
        pg.screenshot(path=os.path.join(OUT, f'{name}_{key}.png'))
        outside()
        closed = pg.evaluate(f"!document.querySelector('{menu}') || !document.querySelector('{menu}').offsetWidth")
        res[key] = f'{inside}, closes-outside={closed}'
        pg.keyboard.press('Escape') if not closed else None

    # Message actions visible on touch (no hover).
    if not touch:
        pg.hover('.msg.user >> nth=-1'); pg.wait_for_timeout(400)
    res['msg-actions-visible'] = pg.evaluate("(() => { const all = document.querySelectorAll('.msg.user'); const a = all.length && all[all.length - 1].querySelector('.msg-actions'); return a ? getComputedStyle(a).opacity : 'none'; })()")

    # Sidebar: drawer on <=880, history "⋯" menu reachable.
    if W <= 880:
        tap('.menu-btn'); pg.wait_for_timeout(900)
        res['drawer'] = pg.evaluate(INSIDE, '.sidebar')
    if not touch and pg.evaluate("!!document.querySelector('.hist-item')"):
        pg.hover('.hist-item'); pg.wait_for_timeout(300)
    op = pg.evaluate("(() => { const m = document.querySelector('.hist-item .hist-menu'); return m ? getComputedStyle(m).opacity : 'none'; })()")
    res['hist-menu-opacity'] = op
    if op != 'none':
        if touch:
            pg.tap('.hist-item .hist-menu')
        else:
            pg.hover('.hist-item'); pg.click('.hist-item .hist-menu')
        pg.wait_for_timeout(300)
        res['hist-pop'] = pg.evaluate(INSIDE, '.hist-pop')
        pg.screenshot(path=os.path.join(OUT, f'{name}_histmenu.png'))
        outside()
        res['hist-pop-closes'] = pg.evaluate("!document.querySelector('.hist-pop')")
    if W <= 880 and pg.evaluate("!!document.querySelector('.app.nav-open')"):
        pg.keyboard.press('Escape'); pg.wait_for_timeout(300)

    # Keyboard shortcuts with the OS's modifier.
    if kb:
        mod = 'Meta' if kb == 'mac' else 'Control'
        pg.mouse.click(W // 2, 120)
        pg.keyboard.press(f'{mod}+/'); pg.wait_for_timeout(300)
        res['help'] = pg.evaluate(INSIDE, '.modal-card')
        res['help-shows-os-keys'] = pg.evaluate("document.querySelector('.kbd-list') ? document.querySelector('.kbd-list').innerText.includes(%s) : false" % json.dumps('⌘' if kb == 'mac' else 'Ctrl'))
        res['mic-label'] = pg.evaluate("(() => { const r = [...document.querySelectorAll('.kbd-row')].find(x => x.innerText.includes('voice')); return r ? r.querySelector('.kbd-keys').innerText.replaceAll('\\n','') : 'none'; })()")
        pg.screenshot(path=os.path.join(OUT, f'{name}_help.png'))
        pg.keyboard.press('Escape'); pg.wait_for_timeout(200)
        pg.keyboard.press(f'{mod}+k'); pg.wait_for_timeout(300)
        res['search-shortcut'] = pg.evaluate("document.activeElement && document.activeElement.tagName === 'INPUT' ? 'ok' : (document.activeElement||{}).className")
        pg.keyboard.press('Escape')
        if W > 880:
            pg.mouse.click(W // 2, 120)
            res['focus-before-ctrl-b'] = pg.evaluate("(document.activeElement||{}).tagName + '.' + (document.activeElement||{}).className")
            r0 = pg.evaluate("document.querySelector('.app').classList.contains('rail')")
            pg.keyboard.press(f'{mod}+b'); pg.wait_for_timeout(350)
            r1 = pg.evaluate("document.querySelector('.app').classList.contains('rail')")
            res['sidebar-shortcut'] = 'ok' if r0 != r1 else 'no change'
            res['overflow-rail'] = pg.evaluate(OVERFLOW) or 'ok'
            pg.keyboard.press(f'{mod}+b'); pg.wait_for_timeout(350)
    res['page-errors'] = errs or 'none'
    b.close()
    return res


OPAQUE = ('msg-actions-visible', 'hist-menu-opacity')
BAD = ('out ', 'missing', 'NOT', 'SENT', 'unexpected', 'no change', 'False', 'hidden')
fails = 0
with sync_playwright() as p:
    for name, engine, device, extra, kb in PROFILES:
        if only and name not in only:
            continue
        try:
            r = run(p, name, engine, device, extra, kb)
        except Exception as e:
            r = {'CRASH': str(e)[:300]}
        bad = {k: v for k, v in r.items() if any(t in str(v) for t in BAD) or (isinstance(v, list) and v) or k == 'CRASH' or (k in OPAQUE and str(v) not in ('1', 'none'))}
        fails += bool(bad)
        print(f"{'PASS' if not bad else 'FAIL'}  {name:22s} {engine:8s} " + json.dumps(r, ensure_ascii=False))
print('failing profiles:', fails)
