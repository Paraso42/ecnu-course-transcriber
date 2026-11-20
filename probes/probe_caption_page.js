(async () => {
  // 打开「AI 字幕任务管理」路由，观察它请求了哪些接口
  const before = new Set(performance.getEntriesByType('resource').map((e) => e.name));
  location.hash = '#/ai-task-caption-manage';
  await new Promise((r) => setTimeout(r, 9000));
  const now = performance.getEntriesByType('resource').map((e) => e.name);
  const fresh = now.filter((u) => !before.has(u));
  return JSON.stringify({
    href: location.href,
    title: document.title,
    fresh: fresh.slice(-80),
    text: (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 1200),
  });
})()
