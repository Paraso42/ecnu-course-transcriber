// 课程 ID 不写死：从页面 URL / location.hash 取，或先注入 globalThis.TECL_ID
(async () => {
  const q = new URLSearchParams(location.search);
  const h = new URLSearchParams((location.hash.split('?')[1] || ''));
  const teclId = globalThis.TECL_ID || q.get('teclId') || h.get('teclId');
  if (!teclId) throw new Error('缺 teclId：先执行 globalThis.TECL_ID="你的课程ID"');const base = '/jy-application-resourcemanage';
  const u = `${base}/v1/subject_vod_list_new?page.pageIndex=1&page.pageSize=1000&teclIds=${teclId}&page.orders[0].asc=true&page.orders[0].field=courBeginTime`;
  const r = await fetch(u, { credentials: 'include', headers: { Accept: 'application/json' } });
  const j = await r.json();
  const recs = (j.data && (j.data.records || j.data.list)) || [];
  const sampleKeys = recs[0] ? Object.keys(recs[0]) : [];
  const rows = recs.map((x) => ({
    courseId: x.id || x.courseId,
    name: x.courName || x.name || x.title,
    begin: x.courBeginTime || x.beginTime,
    end: x.courEndTime,
    dur: x.courDuration || x.duration,
    vodStatus: x.vodStatus ?? x.vodTransferStatus,
    transcript: x.transcriptStatus ?? x.aiTranscriptStatus,
    summary: x.summaryStatus ?? x.aiSummaryStatus,
  }));
  return JSON.stringify({ http: r.status, total: recs.length, sampleKeys, rows }, null, 1);
})()

