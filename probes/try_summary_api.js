(async () => {
  // 探测官方 AI 总结接口：textSummary / summary/search
  const base = '/jy-application-resourcemanage';
  const cid = window.__CID__;
  const cands = [
    { method: 'GET', url: `${base}/v1/course/ai/textSummary/${cid}` },
    { method: 'GET', url: `${base}/v1/course/ai/summary/search/${cid}` },
    { method: 'POST', url: `${base}/v1/course/ai/summary/search/${cid}`, body: {} },
    { method: 'GET', url: `${base}/v1/course/ai/textSummary/${cid}?useOriginal=true` },
  ];
  const out = [];
  for (const c of cands) {
    const rec = { url: c.url, method: c.method };
    try {
      const r = await fetch(c.url, {
        method: c.method,
        credentials: 'include',
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: c.method === 'POST' ? JSON.stringify(c.body) : undefined,
      });
      rec.status = r.status;
      const t = await r.text();
      rec.len = t.length;
      rec.body = t.slice(0, 1500);
    } catch (e) { rec.error = e.message; }
    out.push(rec);
  }
  return JSON.stringify(out);
})()
