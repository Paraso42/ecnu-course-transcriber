(async () => {
  // 在 bundle 里找官方「AI 总结 / 摘要」接口的调用方式
  const urls = [...new Set(performance.getEntriesByType('resource').map((e) => e.name))]
    .filter((u) => /static\/js\/.*\.js/.test(u));
  const out = [];
  for (const u of urls) {
    let txt = '';
    try { txt = await (await fetch(u, { credentials: 'include' })).text(); } catch (e) { continue; }
    const rx = /["'`]([^"'`]*(?:summary|summarize|abstract|ai\/[a-z]+)[^"'`]*)["'`]/gi;
    let m;
    rx.lastIndex = 0;
    while ((m = rx.exec(txt))) {
      const s = m[1];
      if (s.length > 120) continue;
      out.push({ bundle: u.split('/').pop(), s });
    }
  }
  const uniq = [...new Set(out.map((x) => x.s))];
  return JSON.stringify({ n: uniq.length, items: uniq.slice(0, 200) });
})()
