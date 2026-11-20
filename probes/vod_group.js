(async () => {
  const base = '/jy-application-resourcemanage';
  const u = `${base}/v1/group_subject_vod_list/t-1?acteId=10&orgaIds=&labeIds=&subjSource=&page.pageIndex=1&page.pageSize=100&page.orders[0].asc=false&page.orders[0].field=updateTime`;
  const r = await fetch(u, { credentials: 'include', headers: { Accept: 'application/json' } });
  const t = await r.text();
  let j = null;
  try { j = JSON.parse(t); } catch (e) { return 'HTTP ' + r.status + ' 非 JSON: ' + t.slice(0, 500); }
  const res = j.result || j.data || j;
  const listKey = ['list', 'records', 'rows', 'items'].find((k) => res && Array.isArray(res[k]));
  const list = listKey ? res[listKey] : (Array.isArray(res) ? res : []);
  const sample = list[0] ? Object.fromEntries(Object.entries(list[0]).map(([k, v]) => [k, typeof v === 'object' && v ? JSON.stringify(v).slice(0, 120) : v])) : null;
  return JSON.stringify({
    http: r.status,
    topKeys: Object.keys(j),
    resultKeys: res && typeof res === 'object' ? Object.keys(res) : typeof res,
    listKey,
    total: list.length,
    sample,
  }, null, 1);
})()
