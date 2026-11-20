// 优雅关闭由本工作区启动的 Edge。
// 注意：Playwright 的 browser.close() 对 connectOverCDP 只断开连接，不会真的关掉浏览器
// （所以以前“优雅关闭”其实每次都落到强杀，会话 cookie 因此白丢）。
// 这里改为显式发送 CDP 的 Browser.close，Edge 才会正常退出并落盘登录态。
const PW = process.env.PLAYWRIGHT_CORE || 'playwright-core';
const { chromium } = require(PW);

const port = process.argv[2] || process.env.CDP_PORT || '9222';

(async () => {
  const b = await chromium.connectOverCDP('http://127.0.0.1:' + port);
  try {
    const s = await b.newBrowserCDPSession();
    await s.send('Browser.close');
    console.log('GRACEFUL_OK');
  } catch (e) {
    console.log('GRACEFUL_FAIL ' + String(e.message).slice(0, 100));
  }
  process.exit(0);
})().catch((e) => {
  console.log('SKIP ' + String(e.message).slice(0, 100));
  process.exit(1);
});
