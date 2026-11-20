(async () => {
  // 看 aftertime/captions、transcript/optimize、exportCourseVodSubtitle 在 bundle 里的调用方式（method、参数）
  const urls = [...new Set(performance.getEntriesByType('resource').map((e) => e.name))]
    .filter((u) => /static\/js\/.*\.js/.test(u));
  const keys = ['/v1/aftertime/captions/', 'transcript/optimize', 'exportCourseVodSubtitle', 'course_vod_subtitle'];
  const out = [];
  for (const u of urls) {
    let txt = '';
    try { txt = await (await fetch(u, { credentials: 'include' })).text(); } catch (e) { continue; }
    for (const k of keys) {
      let idx = -1;
      while ((idx = txt.indexOf(k, idx + 1)) >= 0) {
        out.push({ bundle: u.split('/').pop(), key: k,
                   ctx: txt.slice(Math.max(0, idx - 260), idx + 260).replace(/\s+/g, ' ') });
      }
    }
  }
  return JSON.stringify({ n: out.length, hits: out.slice(0, 12) });
})()
