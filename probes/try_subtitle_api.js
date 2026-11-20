(async () => {
  // 探测官方字幕/转写接口：对给定 courseId 逐个试候选端点
  const base = '/jy-application-resourcemanage';
  const cid = window.__CID__;
  const cands = [
    `${base}/v1/aftertime/captions/${cid}`,
    `${base}/v1/course_vod_subtitle_with_keyword?courseId=${cid}`,
    `${base}/v1/course_vod_subtitle?courseId=${cid}`,
    `${base}/v1/course/ai/transcript/optimize/tasks?courseId=${cid}`,
    `${base}/v1/exportCourseVodSubtitle?courseId=${cid}`,
    `${base}/v1/course/ai/course/subtitle/export?courseId=${cid}`,
  ];
  const out = [];
  for (const u of cands) {
    const rec = { url: u };
    try {
      const r = await fetch(u, { credentials: 'include', headers: { Accept: 'application/json' } });
      rec.status = r.status;
      rec.ct = r.headers.get('content-type');
      const t = await r.text();
      rec.len = t.length;
      rec.body = t.slice(0, 600);
    } catch (e) { rec.error = e.message; }
    out.push(rec);
  }
  return JSON.stringify(out);
})()
