// 无头生成扫码登录二维码，并在后台等待扫码完成。
// 用法：node pipeline\qr_login.js <二维码输出路径> [等待秒数] [CDP 端口]
// 输出：QR_SAVED {...} / LOGIN_OK <url> / QR_EXPIRED / QR_TIMEOUT / QR_FAIL <原因>
//
// 注意（2026-11 修复）：
//   * 新版 SSO 的二维码不是固定 `img[src*=qrlogin]`，src 形如
//     https://sso.ecnu.edu.cn/api/public/qrlog... 或 blob:，且 tab 文案变成「扫码Scan」。
//     旧选择器直接 waitFor 会静默卡住，调用方（run.py login）因此表现为“生成二维码后不返回”。
//     现在改为：先按 src 关键词找，找不到就按“尺寸接近正方形的大图”兜底。
//   * 全流程加了硬超时与显式退出码，任何异常都打印 QR_FAIL 并退出，不再挂死。
const PW = process.env.PLAYWRIGHT_CORE || 'playwright-core';
const { chromium } = require(PW);

const out = process.argv[2] || 'captures/qr.png';
const timeoutSec = parseInt(process.argv[3] || '180', 10);
const port = process.argv[4] || process.env.CDP_PORT || '9222';

const ROOT = 'https://courses.ecnu.edu.cn';   // 走这里才会被 CAS 拦到 SSO 登录页
const LOGIN_ROUTE = /#\/login/;                // 应用自己的登录路由：也算未登录

function onSso(u) { return /sso\.ecnu\.edu\.cn/.test(u); }
function loggedIn(u) { return !onSso(u) && !LOGIN_ROUTE.test(u); }

function fail(msg) {
  console.log('QR_FAIL ' + String(msg).slice(0, 200));
  process.exit(2);
}

// 页面顶层的硬超时：无论卡在哪一步，都不要让调用方一直等
const hardDeadline = Date.now() + (timeoutSec + 90) * 1000;

async function pickQr(p) {
  // 1) 明确指向二维码接口/二维码样式的图（不同版本 SSO 的 src 前缀不一）
  for (const sel of ['img[src*="qrlog"]', 'img[src*="qrcode"]', 'img[src*="qrlogin"]']) {
    const loc = p.locator(sel).first();
    const n = await loc.count().catch(() => 0);
    if (n) return loc;
  }
  // 2) 兜底：取“宽高都 ≥ 110 且接近正方形”的最大图（实测二维码是 160×160）
  const idx = await p.evaluate(() => {
    const arr = Array.from(document.images).map((im, i) => {
      const r = im.getBoundingClientRect();
      const ratio = r.height ? r.width / r.height : 0;
      return { i, area: r.width * r.height, ok: r.width >= 110 && Math.abs(ratio - 1) <= 0.25 };
    }).filter(x => x.ok).sort((a, b) => b.area - a.area);
    return arr.length ? arr[0].i : -1;
  }).catch(() => -1);
  return idx >= 0 ? p.locator('img').nth(idx) : null;
}

(async () => {
  const b = await chromium.connectOverCDP('http://127.0.0.1:' + port).catch(
    e => fail('连不上浏览器调试端口 ' + port + '：' + e.message));
  const ctx = b.contexts()[0];
  const p = ctx.pages()[0] || await ctx.newPage();

  await p.goto(ROOT, { waitUntil: 'domcontentloaded' }).catch(() => {});
  await p.waitForTimeout(2500);

  // 页面可能在跳转（root → 应用 → OAuth），URL 会短暂落在“既不是 SSO 也不是业务页”的中间态，
  // 所以要轮询到稳定状态再判断，不能看一眼就下结论。
  async function settle(ms) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const u = p.url();
      if (onSso(u) || loggedIn(u)) return u;
      await p.waitForTimeout(800);
    }
    return p.url();
  }

  await settle(15000);
  if (loggedIn(p.url())) {
    console.log('LOGIN_OK already ' + p.url().slice(0, 80));
    process.exit(0);
  }
  if (!onSso(p.url())) {
    // 停在应用自己的 #/login（或中间态）：再走一次根域名，让 CAS 把页面带到 SSO
    await p.goto(ROOT, { waitUntil: 'domcontentloaded' }).catch(() => {});
    await settle(15000);
    if (!onSso(p.url())) {
      if (loggedIn(p.url())) {
        console.log('LOGIN_OK already ' + p.url().slice(0, 80));
        process.exit(0);
      }
      fail('既不在 SSO 也没登录（当前 ' + p.url().slice(0, 60) + '），无法生成二维码');
    }
  }

  // 切到「扫码」标签（文案可能是 扫码 / 扫码Scan）
  const qrTab = p.locator('.ant-tabs-tab', { hasText: '扫码' }).first();
  await qrTab.click({ timeout: 12000 }).catch(e => console.log('TAB_SKIP ' + e.message.slice(0, 60)));
  await p.waitForTimeout(2500);

  // 二维码过期时先点刷新再截
  const refresh = p.locator('text=/点击刷新|已失效|已过期/').first();
  if (await refresh.count().catch(() => 0)) {
    await refresh.click({ timeout: 5000 }).catch(() => {});
    await p.waitForTimeout(2500);
  }

  const img = await pickQr(p);
  if (!img) fail('页面里没找到二维码图片（可能还停在账号密码页，或 SSO 又改版了）');
  await img.waitFor({ state: 'visible', timeout: 15000 }).catch(
    e => fail('二维码图片不可见：' + e.message));

  // 首选：把二维码图片本身（data: URL 或接口直链）原样取下来存盘——
  // 截图会把压在二维码下缘的“请使用微信扫描”提示文字一起截进去，扫码识别率会变差。
  let saved = false;
  try {
    const b64 = await p.evaluate(async () => {
      const im = Array.from(document.images).find((x) => {
        const r = x.getBoundingClientRect();
        return r.width >= 110 && Math.abs(r.width / (r.height || 1) - 1) <= 0.25;
      });
      if (!im) return null;
      const src = im.currentSrc || im.src;
      if (/^data:/.test(src)) return src.split(',')[1] || null;
      const r = await fetch(src, { credentials: 'include' });
      const buf = new Uint8Array(await r.arrayBuffer());
      let s = '';
      for (let i = 0; i < buf.length; i++) s += String.fromCharCode(buf[i]);
      return btoa(s);
    });
    if (b64) {
      const fs = require('fs');
      fs.writeFileSync(out, Buffer.from(b64, 'base64'));
      saved = true;
    }
  } catch (_) {}

  if (!saved) {
    let shot = img;
    try {
      const parent = img.locator('xpath=..');
      const ib = await img.boundingBox();
      const pb = await parent.boundingBox();
      if (ib && pb && pb.width <= ib.width * 1.8 && pb.height <= ib.height * 1.8) shot = parent;
    } catch (_) {}
    await shot.screenshot({ path: out }).catch(e => fail('截图失败：' + e.message));
  }

  const hint = await p.evaluate(
    () => (document.body.innerText.match(/请使用[^。]{0,30}/) || [''])[0],
  ).catch(() => '');
  console.log('QR_SAVED ' + JSON.stringify({ path: out, hint }));

  const deadline = Date.now() + timeoutSec * 1000;
  while (Date.now() < Math.min(deadline, hardDeadline)) {
    await p.waitForTimeout(2500);
    if (loggedIn(p.url())) {
      console.log('LOGIN_OK ' + p.url().slice(0, 100));
      process.exit(0);
    }
    const expired = await p.evaluate(
      () => /已失效|已过期|点击刷新/.test(document.body.innerText),
    ).catch(() => false);
    if (expired) { console.log('QR_EXPIRED'); process.exit(0); }
  }
  console.log('QR_TIMEOUT');
  process.exit(0);
})().catch(e => fail(e && e.message));
