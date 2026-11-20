// 示例探针：列出一门课的全部节次
// 用法：node cdp_probe.js evalfile courses.ecnu.edu.cn probes/sessions2.js out.json
// 课程 ID 不写死：从页面 URL / location.hash 里取，或先注入 globalThis.TECL_ID。
(async () => {
  const q = new URLSearchParams(location.search);
  const h = new URLSearchParams((location.hash.split('?')[1] || ''));
  const teclId = globalThis.TECL_ID || q.get('teclId') || h.get('teclId');
  if (!teclId) throw new Error('缺 teclId：先执行 globalThis.TECL_ID="你的课程ID"，或改用带 teclId 的页面');
  const base = '/jy-application-resourcemanage';
  const u = `${base}/v1/subject_vod_list_new?page.pageIndex=1&page.pageSize=100&teclIds=${teclId}&page.orders[0].asc=true&page.orders[0].field=courBeginTime`;
  const r = await fetch(u, { credentials: 'include', headers: { Accept: 'application/json' } });
  const j = await r.json();
  const recs = (j.data && (j.data.records || j.data.list)) || [];
  return recs.map((x) => `${x.courBeginTime} | id=${x.id} | vod=${x.vodStatus} | task=${x.transcriptOptimizeTaskStatus}`).join('\n');
})()
