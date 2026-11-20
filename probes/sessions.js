// 课程 ID 不写死：从页面 URL / location.hash 取，或先注入 globalThis.TECL_ID
(async () => {
  const q = new URLSearchParams(location.search);
  const h = new URLSearchParams((location.hash.split('?')[1] || ''));
  const teclId = globalThis.TECL_ID || q.get('teclId') || h.get('teclId');
  if (!teclId) throw new Error('缺 teclId：先执行 globalThis.TECL_ID="你的课程ID"');const base = '/jy-application-resourcemanage';
  const u = `${base}/v1/subject_vod_list_new?page.pageIndex=1&page.pageSize=100&teclIds=${teclId}&page.orders[0].asc=true&page.orders[0].field=courBeginTime`;
  const r = await fetch(u, { credentials: 'include', headers: { Accept: 'application/json' } });
  const j = await r.json();
  const recs = (j.data && (j.data.records || j.data.list)) || [];
  const fmt = (t) => {
    if (!t) return null;
    if (typeof t === 'string') return t;
    const d = new Date(t);
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  };
  return JSON.stringify(recs.map((x) => ({
    courseId: x.id,
    courseNo: x.courseNo,
    begin: fmt(x.courBeginTime),
    end: fmt(x.courEndTime),
    vodStatus: x.vodStatus,
    vodTransferStatus: x.vodTransferStatus,
    transcriptTask: x.transcriptOptimizeTaskStatus,
    download: x.vodDownloadEnable,
    week: x.weekNumber || x.week,
    play: x.courPlayCount,
  })), null, 1);
})()

