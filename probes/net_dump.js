// 打开指定页面，抓取所有 jy-application* 接口请求/响应（含 body 片段），用于发现字幕/转写接口。
// 用法: node probes/net_dump.js "<url>" <等待秒数> <输出文件>
const path = require('path');
const fs = require('fs');
const PW = process.env.PLAYWRIGHT_CORE || 'playwright-core';
const { chromium } = require(PW);

async function main() {
  const [url, waitSec = '10', outArg] = process.argv.slice(2);
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const ctx = browser.contexts()[0];
  const page = ctx.pages().find((p) => p.url().includes('courses.ecnu.edu.cn')) || ctx.pages()[0];
  const rows = [];
  page.on('response', async (resp) => {
    const u = resp.url();
    if (!/jy-application/.test(u)) return;
    const ct = resp.headers()['content-type'] || '';
    const row = { status: resp.status(), url: u, ct, body: '' };
    try {
      if (/json/.test(ct)) row.body = (await resp.text()).slice(0, 2000);
      else if (/text|javascript/.test(ct)) row.body = (await resp.text()).slice(0, 400);
    } catch (e) { /* ignore */ }
    rows.push(row);
  });
  if (url === 'reload') {
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 90000 }).catch((e) => console.log('[reload]', e.message));
  } else {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 }).catch((e) => console.log('[goto]', e.message));
  }
  await page.waitForTimeout(parseInt(waitSec, 10) * 1000);
  const out = outArg || path.join(__dirname, '..', 'captures', 'net_dump.json');
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, JSON.stringify({ page: page.url(), rows }, null, 1), 'utf-8');
  console.log('[dump]', rows.length, '→', out);
  rows.forEach((r) => console.log(r.status, r.url.slice(0, 200)));
  await browser.close();
}
main().catch((e) => { console.error('ERR', e.message); process.exit(1); });
