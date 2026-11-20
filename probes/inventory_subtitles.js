(async () => {
  // 统计每节课官方字幕：条数、字符数、时间跨度、前几条样例
  const base = '/jy-application-resourcemanage';
  const cids = window.__CIDS__ || [];
  const out = {};
  for (const cid of cids) {
    try {
      const r = await fetch(`${base}/v1/course_vod_subtitle?courseId=${cid}`,
        { credentials: 'include', headers: { Accept: 'application/json' } });
      const j = await r.json();
      const rows = j.data || [];
      const chars = rows.reduce((a, x) => a + String(x.res || '').length, 0);
      const lastEd = rows.length ? Math.max(...rows.map((x) => x.ed || 0)) : 0;
      out[cid] = {
        n: rows.length, chars,
        lastEdMs: lastEd,
        first: rows.slice(0, 3).map((x) => ({ bg: x.bg, ed: x.ed, res: x.res })),
        last: rows.slice(-2).map((x) => ({ bg: x.bg, ed: x.ed, res: x.res })),
      };
    } catch (e) { out[cid] = { error: e.message }; }
  }
  return JSON.stringify(out);
})()
