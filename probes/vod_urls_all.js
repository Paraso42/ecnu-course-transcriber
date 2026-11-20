(async () => {
  const base = '/jy-application-resourcemanage';
  const ids = [514480, 514481, 514482, 516230, 516231, 516232, 523945, 523946, 523947];
  const out = {};
  for (const cid of ids) {
    const r = await fetch(`${base}/v1/course_vod_urls_new?courseId=${cid}`, {
      credentials: 'include', headers: { Accept: 'application/json' },
    });
    const j = await r.json();
    const d = j.data || {};
    const list = (d.courseVodViewList || []).map((v) => ({ vodId: v.vodId, vodTime: v.vodTime, url: v.url }));
    out[cid] = { name: d.courName, begin: d.courBeginTime, list };
  }
  return JSON.stringify(out, null, 1);
})()
