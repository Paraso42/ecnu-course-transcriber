// 登录态快照：把浏览器里的 cookie 存到文件 / 从文件灌回浏览器。
// 用途：Edge 被强杀（profile 未优雅关闭）时会话 cookie 直接丢失，登录态就没了；
//      有了快照，下次启动浏览器可以先把还在有效期内的 cookie 灌回去，省一次扫码。
//
// 用法：node cookies.js sync <port> <snapshot.json> [restore|dump]
//       restore（默认）= 先灌回旧快照，再把当前 cookie 写回文件
//       dump           = 只把当前 cookie 写回文件（关闭浏览器前用）
const fs = require('fs');
const PW = process.env.PLAYWRIGHT_CORE || 'playwright-core';
const { chromium } = require(PW);

const [, , mode, port, file, action] = process.argv;
const act = (action || 'restore').toLowerCase();

// 只关心学校域名：别的站点的 cookie 与我们无关，还可能带敏感信息
function ours(c) {
  const d = String(c.domain || '').replace(/^\./, '');
  return /(^|\.)ecnu\.edu\.cn$/.test(d) || /(^|\.)ecnu\.cn$/.test(d);
}

(async () => {
  const b = await chromium.connectOverCDP('http://127.0.0.1:' + port);
  const ctx = b.contexts()[0];
  let restored = 0, skipped = 0;

  if (act === 'restore' && fs.existsSync(file)) {
    let arr = [];
    try {
      arr = JSON.parse(fs.readFileSync(file, 'utf8')) || [];
    } catch (e) {
      console.log('SNAPSHOT_BAD ' + e.message.slice(0, 80));
    }
    if (arr.length) {
      try {
        await ctx.addCookies(arr);
        restored = arr.length;
      } catch (e) {                       // 单条不合法就逐条来，别整批失败
        for (const c of arr) {
          try { await ctx.addCookies([c]); restored += 1; } catch (_) { skipped += 1; }
        }
        console.log('ADDCOOKIE_FALLBACK ' + e.message.slice(0, 80));
      }
    }
  }

  let cookies = [];
  try {
    cookies = (await ctx.cookies()).filter(ours);
  } catch (e) {
    console.log('COOKIES_FAIL ' + e.message.slice(0, 80));
    process.exit(1);
  }
  try {
    fs.writeFileSync(file, JSON.stringify(cookies, null, 1), 'utf8');
  } catch (e) {
    console.log('COOKIES_WRITE_FAIL ' + e.message.slice(0, 80));
    process.exit(1);
  }
  const names = cookies.map((c) => c.name).join(',');
  console.log('COOKIES saved=' + cookies.length + ' restored=' + restored
    + (skipped ? ' skipped=' + skipped : '') + ' names=' + names.slice(0, 200));
  process.exit(0);
})().catch((e) => {
  console.log('COOKIES_FAIL ' + e.message.slice(0, 120));
  process.exit(1);
});
