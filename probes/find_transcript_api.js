(async () => {
  // 在课程平台页面里搜前端 bundle 中的 transcript 相关接口
  const scripts = Array.from(document.querySelectorAll('script[src]')).map((s) => s.src);
  const out = { scripts: scripts.slice(0, 40), hits: [], apiPrefix: null };
  const seen = new Set();
  const rx = /["'`]([^"'`\s]{0,120}transcript[^"'`\s]{0,160})["'`]/gi;
  for (const src of scripts) {
    if (seen.has(src)) continue;
    seen.add(src);
    try {
      const r = await fetch(src, { credentials: 'include' });
      const txt = await r.text();
      let m;
      rx.lastIndex = 0;
      while ((m = rx.exec(txt))) {
        const s = m[1];
        if (out.hits.length < 200) out.hits.push(s);
      }
    } catch (e) { /* ignore */ }
  }
  out.hits = [...new Set(out.hits)];
  return JSON.stringify(out);
})()
