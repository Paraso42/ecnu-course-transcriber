(async () => {
  const base = '/jy-application-resourcemanage';
  const cid = 514480;
  const urls = [
    `${base}/v1/course_vod_urls_new?courseId=${cid}`,
    `${base}/v1/course/ai/transcript/optimize/tasks?courseId=${cid}`,
    `${base}/v1/course/ai/textSummary/${cid}`,
  ];
  const out = [];
  for (const u of urls) {
    try {
      const r = await fetch(u, { credentials: 'include', headers: { Accept: 'application/json' } });
      const t = await r.text();
      out.push(`### ${u.split('?')[0]}\nHTTP ${r.status}  len=${t.length}\n${t.slice(0, 1200)}`);
    } catch (e) { out.push(`### ${u}\nERR ${e.message}`); }
  }
  return out.join('\n\n');
})()
