(async () => {
  const base = '/jy-application-resourcemanage';
  const u = `${base}/v1/group_subject_vod_list/t-1?acteId=10&orgaIds=&labeIds=&subjSource=&page.pageIndex=1&page.pageSize=100&page.orders[0].asc=false&page.orders[0].field=updateTime`;
  const r = await fetch(u, { credentials: 'include', headers: { Accept: 'application/json' } });
  const j = await r.json();
  const recs = (j.data && j.data.records) || [];
  const rows = recs.map((x) => ({
    subjName: x.subjName, subjId: x.subjId, teclId: x.teclId, subjCode: x.subjCode,
    teacNames: x.teacNames, courTimes: x.courTimes, playCount: x.courPlayCount,
    pptSlice: x.coursePptSliceCount, term: `${x.acyeBeginYear}-${x.acyeEndYear}`,
  }));
  return JSON.stringify(rows, null, 1);
})()
