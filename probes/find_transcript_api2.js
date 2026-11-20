(async () => {
  // 在课程平台首页 bundle 里找：路由名、play-center 相关 chunk、字幕/转写相关关键字
  const scripts = Array.from(document.querySelectorAll('script[src]')).map((s) => s.src);
  const out = { bundles: [], chunks: [], words: {}, apis: [] };
  const words = ['subtitle', 'caption', 'srt', 'vtt', 'transcript', 'asr', 'speech', '语音', '字幕', '转写', '字幕识别', 'text-track'];
  const apiRx = /["'`](\/v\d+\/[A-Za-z0-9_\-]+)["'`]/g;
  const chunkRx = /["'`]((?:\.\/)?[\w\-\/]*play[\w\-\/]*\.js)["'`]/g;
  for (const src of scripts) {
    let txt = '';
    try {
      const r = await fetch(src, { credentials: 'include' });
      txt = await r.text();
    } catch (e) { continue; }
    out.bundles.push({ src, len: txt.length });
    for (const w of words) {
      let n = 0, idx = -1, ctx = [];
      const lw = txt.toLowerCase();
      while ((idx = lw.indexOf(w.toLowerCase(), idx + 1)) >= 0) {
        n++;
        if (ctx.length < 3) ctx.push(txt.slice(Math.max(0, idx - 90), idx + 90).replace(/\s+/g, ' '));
      }
      if (n) out.words[w] = { n, ctx };
    }
    let m;
    apiRx.lastIndex = 0;
    while ((m = apiRx.exec(txt))) out.apis.push(m[1]);
    chunkRx.lastIndex = 0;
    while ((m = chunkRx.exec(txt))) out.chunks.push(m[1]);
  }
  out.apis = [...new Set(out.apis)].filter((u) => /vod|course|subtitle|transcript|text/i.test(u)).slice(0, 60);
  out.chunks = [...new Set(out.chunks)].slice(0, 30);
  return JSON.stringify(out);
})()
