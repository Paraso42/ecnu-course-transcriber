(async () => {
  const base = '/jy-application-resourcemanage';
  const urls = [
    `${base}/resource/resources_tree_me?sorts[0].name=sortIndex&sorts[0].order=ASC`,
  ];
  const out = [];
  for (const u of urls) {
    try {
      const r = await fetch(u, { credentials: 'include', headers: { Accept: 'application/json' } });
      const t = await r.text();
      out.push(`### ${u}\nHTTP ${r.status}\n${t}`);
    } catch (e) {
      out.push(`### ${u}\nERR ${e.message}`);
    }
  }
  return out.join('\n\n');
})()
