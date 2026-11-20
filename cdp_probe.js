// 通过 CDP 连接到已启动的 Edge（--remote-debugging-port=9222），
// 监听页面所有请求/响应，抓取平台 API 与媒体流地址。
// 用法：
//   node cdp_probe.js list
//   node cdp_probe.js probe <url关键字> <目标URL或-> <等待秒数>
const path = require('path');
const fs = require('fs');
// playwright-core 路径可用环境变量覆盖：$env:PLAYWRIGHT_CORE = "..."
const PW = process.env.PLAYWRIGHT_CORE || 'playwright-core';
const { chromium } = require(PW);

const LOG_DIR = path.join(__dirname, 'captures');   // 采集输出统一放本目录
const INTEREST = /jy-application|media|m3u8|\.ts(\?|$)|\.mp4|\.m4s|\.key(\?|$)|vod|video|play|subtitle|vtt|onlyoffice|resource/i;

async function main() {
  const [action, ...rest] = process.argv.slice(2);
  const browser = await chromium.connectOverCDP('http://127.0.0.1:9222');
  const ctx = browser.contexts()[0];
  const pages = ctx.pages();

  if (action === 'list') {
    for (const [i, p] of pages.entries()) {
      console.log(i, JSON.stringify({ url: p.url(), title: await p.title().catch(() => '') }));
    }
    await browser.close();
    return;
  }

  if (action === 'info') {
    for (const [i, p] of pages.entries()) {
      console.log(i, JSON.stringify({ url: p.url(), title: await p.title().catch(() => '') }));
    }
    await browser.close();
    return;
  }

  if (action === 'evalfile') {
    const urlKey = rest[0];
    const file = rest[1];
    const outArg = rest[2];                     // 可选：指定结果输出文件（流水线用）
    const code = fs.readFileSync(file, 'utf-8');
    const p = pages.find((x) => x.url().includes(urlKey)) || pages[0];
    const out = await p.evaluate(code);
    const text = typeof out === 'string' ? out : JSON.stringify(out, null, 1);
    fs.mkdirSync(LOG_DIR, { recursive: true });
    const outFile = outArg ? path.resolve(outArg) : path.join(LOG_DIR, 'eval_out.txt');
    fs.mkdirSync(path.dirname(outFile), { recursive: true });
    fs.writeFileSync(outFile, text, 'utf-8');
    console.log(`[长度 ${text.length}] → ${outFile}`);
    if (!outArg) console.log(text.slice(0, 3000));
    await browser.close();
    return;
  }

  if (action === 'waitlogin') {
    const maxSec = parseInt(rest[0] || '300', 10);
    const p = pages.find((x) => x.url().includes('courses.ecnu.edu.cn') || x.url().includes('sso.ecnu.edu.cn')) || pages[0];
    const t0 = Date.now();
    let last = '';
    while ((Date.now() - t0) / 1000 < maxSec) {
      const u = p.url();
      if (u !== last) {
        console.log(`[${Math.round((Date.now() - t0) / 1000)}s]`, u.slice(0, 160));
        last = u;
      }
      if (!/sso\.ecnu\.edu\.cn/.test(u)) {
        console.log('[登录完成]', u);
        console.log('[标题]', await p.title().catch(() => ''));
        break;
      }
      await p.waitForTimeout(3000);
    }
    await browser.close();
    return;
  }

  if (action === 'goto') {
    const target = rest[0];
    const p = pages.find((x) => x.url().includes(rest[1] || 'courses.ecnu.edu.cn')) || pages[0];
    await p.goto(target, { waitUntil: 'domcontentloaded', timeout: 90000 }).catch((e) => console.log('[goto]', e.message));
    await p.waitForTimeout(4000);
    console.log('[现在]', p.url());
    console.log('[标题]', await p.title().catch(() => ''));
    await browser.close();
    return;
  }

  const urlKey = rest[0] || 'courses.ecnu.edu.cn';
  const target = rest[1] || '-';
  const waitSec = parseInt(rest[2] || '25', 10);

  let page = pages.find((p) => p.url().includes(urlKey)) || pages[0];
  if (!page) { console.error('没有可用页面'); process.exit(1); }
  console.log('[页面]', page.url());

  const rows = [];
  page.on('request', (r) => {
    const u = r.url();
    if (INTEREST.test(u)) rows.push({ t: 'req', m: r.method(), u, ct: r.resourceType() });
  });
  page.on('response', async (resp) => {
    const u = resp.url();
    if (!INTEREST.test(u)) return;
    const ct = resp.headers()['content-type'] || '';
    const row = { t: 'res', s: resp.status(), u, ct };
    if (/json|javascript/.test(ct) && /jy-application/.test(u)) {
      try { row.body = (await resp.text()).slice(0, 800); } catch (_) {}
    }
    rows.push(row);
  });

  if (target === 'reload') {
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 60000 }).catch((e) => console.log('[reload]', e.message));
  } else if (target !== '-') {
    await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch((e) => console.log('[goto]', e.message));
  }
  await page.waitForTimeout(waitSec * 1000);

  fs.mkdirSync(LOG_DIR, { recursive: true });
  const out = path.join(LOG_DIR, 'cdp_capture.json');
  fs.writeFileSync(out, JSON.stringify(rows, null, 1), 'utf-8');

  const media = rows.filter((r) => /m3u8|\.ts(\?|$)|\.mp4|\.m4s|\.key(\?|$)/.test(r.u));
  console.log(`[采集] 共 ${rows.length} 条，其中媒体 ${media.length} 条 → ${out}`);
  media.slice(0, 25).forEach((r) => console.log('  MEDIA', r.m || r.s, r.u.slice(0, 220)));
  const apis = [...new Set(rows.filter((r) => /jy-application/.test(r.u)).map((r) => r.u))];
  apis.slice(0, 20).forEach((u) => console.log('  API', u.slice(0, 220)));
  await browser.close();
}

main().catch((e) => { console.error('ERR', e.message); process.exit(1); });
