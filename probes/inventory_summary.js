(async () => {
  // 统计每节课官方 AI 总结（summary/search）与字幕的可用情况
  const base = '/jy-application-resourcemanage';
  const cids = window.__CIDS__ || [];
  const out = {};
  for (const cid of cids) {
    const rec = {};
    try {
      const r = await fetch(`${base}/v1/course/ai/summary/search/${cid}`,
        { credentials: 'include', headers: { Accept: 'application/json' } });
      const j = await r.json();
      const d = j.data || {};
      rec.summaryChars = (d.fullOverview || '').length;
      rec.skims = (d.documentSkims || []).length;
      rec.keyPoints = (d.keyPoints || []).length;
      rec.hasSummary = !!(d.fullOverview || (d.documentSkims || []).length);
      rec.sample = (d.fullOverview || '').slice(0, 80);
    } catch (e) { rec.summaryError = e.message; }
    try {
      const r2 = await fetch(`${base}/v1/course_vod_subtitle?courseId=${cid}`,
        { credentials: 'include', headers: { Accept: 'application/json' } });
      const j2 = await r2.json();
      rec.captions = (j2.data || []).length;
    } catch (e) { rec.captionError = e.message; }
    out[cid] = rec;
  }
  return JSON.stringify(out);
})()
