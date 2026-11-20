(async () => {
  const base = '/jy-application-resourcemanage';
  const ids = [514480, 514481, 514482];
  const out = {};
  for (const cid of ids) {
    const u = `${base}/v1/course_vod_urls_new?courseId=${cid}`;
    const r = await fetch(u, { credentials: 'include', headers: { Accept: 'application/json' } });
    const j = await r.json();
    const d = j.data || {};
    const list = (d.courseVodViewList || []).map((v) => ({
      vodId: v.vodId, vodTime: v.vodTime, viewNum: v.viewNum, url: v.url,
    }));
    const live = d.courseLiveViewList ? d.courseLiveViewList.length : null;
    out[cid] = { courName: d.courName, room: d.classRoomName, begin: d.courBeginTime, count: list.length, live, list };
  }
  return JSON.stringify(out, null, 1);
})()
