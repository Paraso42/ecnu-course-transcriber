(async () => {
  // 抓当前 SPA 所有已加载 bundle：路由路径 + transcript/字幕相关接口字符串
  const urls = [...new Set(performance.getEntriesByType('resource').map((e) => e.name))]
    .filter((u) => /static\/js\/.*\.js/.test(u));
  const out = { bundles: urls.length, routes: [], tr: [], apis: [] };
  const trRx = /["'`]([^"'`\s]{0,140}(?:transcript|transcribe|caption|subtitle|asr)[^"'`\s]{0,140})["'`]/gi;
  const apiRx = /["'`](\/v\d+\/[A-Za-z0-9_\/\-{}\$\.]+)["'`]/g;
  const routeRx = /path:\s*"(\/[^"]*)"/g;
  for (const u of urls) {
    let txt = '';
    try {
      const r = await fetch(u, { credentials: 'include' });
      txt = await r.text();
    } catch (e) { continue; }
    let m;
    trRx.lastIndex = 0;
    while ((m = trRx.exec(txt))) out.tr.push(m[1]);
    apiRx.lastIndex = 0;
    while ((m = apiRx.exec(txt))) out.apis.push(m[1]);
    routeRx.lastIndex = 0;
    while ((m = routeRx.exec(txt))) out.routes.push(m[1]);
  }
  out.tr = [...new Set(out.tr)].slice(0, 120);
  out.apis = [...new Set(out.apis)].slice(0, 200);
  out.routes = [...new Set(out.routes)].slice(0, 200);
  return JSON.stringify(out);
})()
