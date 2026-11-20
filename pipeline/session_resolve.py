#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""课程网页 → 节次清单 + 点播直链（依赖已登录的可见 Edge + CDP）。

对外主函数：
    info = resolve_course(url)         # 自动完成：启动浏览器 → 打开链接 → 定位课程 → 取节次与直链
    info["sessions"] = [{courseId, date, begin, end, name, duration, url, vodId}, ...]
"""
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

import common as C
import settings

API = "/jy-application-resourcemanage"
CDP_PORT = C.CDP_PORT


# ------------------------------------------------------------------ 浏览器控制
def _cdp_alive():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % CDP_PORT, timeout=2) as r:
            json.loads(r.read().decode("utf-8", "replace"))
            return True
    except Exception:
        return False


def _find_edge():
    """config.json 的 edge_path 优先；否则在 Windows 常见安装位置里找。"""
    configured = settings.get("edge_path")
    if configured:
        p = os.path.expandvars(os.path.expanduser(str(configured)))
        if os.path.exists(p):
            return p
        print("[警告] config.json 里的 edge_path 不存在：%s，改用自动查找" % p, file=sys.stderr)
    for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        "/usr/bin/microsoft-edge",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ):
        if p and os.path.exists(p):
            return p
    hit = glob.glob(r"C:\Program Files*\Microsoft\Edge\Application\msedge.exe")
    return hit[0] if hit else None


_PROC = None          # 由本进程启动的 Edge（只有自己启动的才由自己关）
_HEADLESS = None      # 本次启动是否无头

# 登录态快照：Edge 被强杀（或崩溃）时会话 cookie 来不及落盘，登录态直接消失。
# 每次接触浏览器时把 cookie 存一份到 _gen，下次启动先灌回去，能省一次扫码。
SNAPSHOT = os.path.join(C.GEN, "cookies_%d.json" % CDP_PORT)
SNAPSHOT_TTL = 12 * 3600


def sync_cookies(action="restore"):
    """把 cookie 灌回浏览器并把当前 cookie 写回快照。返回 (saved, restored) 或 None。

    action="restore"：先灌旧快照（超过 SNAPSHOT_TTL 视为不可信，跳过），再写回当前 cookie；
    action="dump"   ：只写回当前 cookie（关闭浏览器前调用）。
    失败不抛异常——登录态本来就要过期，这里只是“多争取一次不用扫码”。
    """
    try:
        C.ensure_dirs(C.GEN)
        args = ["node", os.path.join(C.HERE, "cookies.js"), "sync",
                str(CDP_PORT), SNAPSHOT, action]
        fresh = (os.path.exists(SNAPSHOT)
                 and (time.time() - os.path.getmtime(SNAPSHOT)) < SNAPSHOT_TTL)
        if action == "restore" and not fresh:
            args[-1] = "dump"
        r = C.run(args)
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        m = re.search(r"saved=(\d+)\s+restored=(\d+)", out)
        if m:
            saved, restored = int(m.group(1)), int(m.group(2))
            if restored:
                print("[登录] 已从快照灌回 %d 个 cookie（省一次扫码）" % restored, file=sys.stderr)
            return saved, restored
        if "COOKIES_FAIL" in out:
            print("[登录] cookie 快照失败：%s" % out.split("COOKIES_FAIL", 1)[1].strip()[:120],
                  file=sys.stderr)
    except Exception as e:
        print("[登录] cookie 快照失败：%s" % str(e)[:120], file=sys.stderr)
    return None


def ensure_browser(start_url="https://courses.ecnu.edu.cn", wait=60, headless=False):
    """确保 9222 上有可用的 Edge。

    headless=True 时用无头 Edge：不弹窗，跑完由 close_browser() 关掉。
    若 9222 已经有 Edge（比如用户正开着的可见窗口），直接复用、不另起、也不会去关它。
    """
    global _PROC, _HEADLESS
    if _cdp_alive():
        # 复用别人（或上次没关干净）的浏览器：先把快照里的 cookie 灌回（可能已被强杀丢了会话），
        # 再清掉残留 SSO 页，否则 logged_in() 会被误判
        sync_cookies("restore")
        close_sso_tabs()
        return True
    exe = _find_edge()
    if not exe:
        raise RuntimeError("找不到 msedge.exe，请手动启动 Edge 并加 --remote-debugging-port=%d" % CDP_PORT)
    C.ensure_dirs(C.PROFILE)
    args = [exe,
            "--remote-debugging-port=%d" % CDP_PORT,
            "--user-data-dir=" + C.PROFILE,
            "--no-first-run", "--no-default-browser-check",
            "--disable-features=Translate,MediaRouter",
            "--disable-sync", "--metrics-recording-only"]
    if headless:
        args += ["--headless=new", "--disable-gpu", "--window-size=1600,1000",
                 "--screenshot-quality=0"]
        print("[浏览器] 启动无头 Edge（不显示窗口，跑完自动关闭）", file=sys.stderr)
    else:
        print("[浏览器] 启动可见 Edge（登录态目录：%s）" % C.PROFILE, file=sys.stderr)
    args.append(start_url)
    _PROC = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _HEADLESS = bool(headless)
    for _ in range(wait):
        if _cdp_alive():
            time.sleep(2)
            sync_cookies("restore")     # 刚启动的浏览器：先把上次的 cookie 灌回去再返回
            return True
        time.sleep(1)
    raise RuntimeError("Edge 启动后 %d 秒内仍无法连接 CDP" % wait)


def _kill_profile_procs():
    """按命令行精确杀掉只用本仓库 profile 的 Edge（不碰用户自己的 Edge）。

    只匹配 `--user-data-dir` 指向本仓库 profile 的进程，跨机器/跨目录都能用。
    """
    prof = C.PROFILE
    if os.name == "nt":
        cmd = (
            "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
            "Where-Object { $_.CommandLine -and $_.CommandLine.Contains('%s') } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            % prof.replace("'", "''")
        )
        try:
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except Exception:
            pass
    else:
        try:
            subprocess.run(["pkill", "-f", prof], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=30)
        except Exception:
            pass


def close_browser():
    """只关自己启动的浏览器；复用的（用户自己开的）不动。

    顺序：先把 cookie 存快照 → CDP 优雅关闭（登录态正常落盘）→ 等它自己退 →
    还赖着才按 profile 精确清掉（此时快照已是最后保险）。
    """
    global _PROC, _HEADLESS
    if _PROC is None:
        return False
    sync_cookies("dump")             # 关之前存档：万一后面要强杀，至少 cookie 还在快照里
    closer = os.path.join(C.HERE, "close_browser.js")
    try:
        r = C.run(["node", closer, str(CDP_PORT)])
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        if out:
            print("[浏览器] " + out.splitlines()[-1][:120], file=sys.stderr)
    except Exception:
        pass
    for _ in range(25):
        if _PROC.poll() is not None and not _cdp_alive():
            break
        time.sleep(0.5)
    # 进程还在不一定没关干净：Edge 会留后台子进程，只要 CDP 已断就算关好了
    forced = _cdp_alive()
    try:
        _kill_profile_procs()          # 优雅关闭后仍残留的，精确清掉
    finally:
        _PROC = None
        _HEADLESS = None
    if forced:
        print("[浏览器] 没能在 12 秒内断开 CDP，已强制结束；"
              "登录态以 %s 的快照为准" % os.path.basename(SNAPSHOT), file=sys.stderr)
    else:
        print("[浏览器] 已关闭后台浏览器", file=sys.stderr)
    return True


def owns_browser():
    return _PROC is not None


def _node(args, retries=3):
    """跑一次 cdp_probe.js。页面正在跳转时 evaluate 会报 Execution context was destroyed，
    这是瞬时错误（本次就因此白丢过一段课件），这里自动重试几次再抛。"""
    last = ""
    for i in range(retries):
        r = C.run(["node", C.CDP] + args)
        if r.returncode == 0:
            return (r.stdout or "").strip()
        last = (r.stderr or r.stdout or "")
        if "Execution context was destroyed" not in last:
            break
        time.sleep(1.5 + i * 1.5)
    raise RuntimeError("CDP 失败：" + last[-500:])


def goto(url):
    _node(["goto", url, "courses.ecnu.edu.cn"])
    time.sleep(2)


def close_sso_tabs():
    """关掉停在 SSO 的标签页（只碰本工作区 profile 里的浏览器）。

    扫码失败/过期时 SSO 页会留在 profile 里，而旧版 logged_in() 只要看到“任意一个 SSO 标签页”
    就判未登录，于是后续每条命令都报“登录态失效”。这里在复用浏览器前先清干净。
    """
    js = os.path.join(C.GEN, "close_sso_tabs.js")
    C.ensure_dirs(C.GEN)
    if not os.path.exists(js):
        with open(js, "w", encoding="utf-8") as f:
            f.write(
                "const PW = process.env.PLAYWRIGHT_CORE || 'playwright-core';\n"
                "const { chromium } = require(PW);\n"
                "(async () => {\n"
                "  try {\n"
                "    const b = await chromium.connectOverCDP('http://127.0.0.1:%d');\n"
                "    const ctx = b.contexts()[0];\n"
                "    const pages = ctx.pages();\n"
                "    const live = pages.filter((p) => !/sso\\.ecnu\\.edu\\.cn/.test(p.url()));\n"
                "    if (!live.length) { console.log('KEEP_SSO_ONLY'); }\n"
                "    else {\n"
                "      for (const p of pages) {\n"
                "        if (/sso\\.ecnu\\.edu\\.cn/.test(p.url())) {\n"
                "          await p.close().catch(() => {});\n"
                "          console.log('CLOSED_SSO');\n"
                "        }\n"
                "      }\n"
                "    }\n"
                "  } catch (e) { console.log('SKIP ' + e.message.slice(0, 60)); }\n"
                "  process.exit(0);\n"
                "})();\n" % CDP_PORT
            )
    try:
        C.run(["node", js])
    except Exception:
        pass


def logged_in():
    """已登录 = 存在一个停在课程平台业务页（既不是 SSO、也不是应用自己的 #/login）的页面。

    旧实现是「全部标签页里不含 sso 即已登录」，两个坑：① 只要有一个残留 SSO 页，
    已登录的浏览器就被判未登录（2026-11-17 实测复现）；② 未登录时应用会停在
    .../#/login（不是 SSO 域名），于是又被误判成已登录。
    """
    out = _node(["list"])
    for line in (out or "").splitlines():
        if "{" not in line:
            continue
        try:
            d = json.loads(line[line.index("{"):])
        except Exception:
            continue
        url = d.get("url") or ""
        if "sso.ecnu.edu.cn" in url or "#/login" in url:
            continue
        if "courses.ecnu.edu.cn" in url:
            return True
    return False


def logged_in_wait(timeout=12):
    """等应用路由安定下来再判断（SPA 会先渲染 #/login 再恢复会话）。"""
    end = time.time() + timeout
    while True:
        if logged_in():
            return True
        if time.time() >= end:
            return False
        time.sleep(2)


def run_probe(js_code, tag="probe"):
    """把 JS 写入临时文件后在页面上下文执行，返回解析后的 JSON。"""
    C.ensure_dirs(C.GEN)
    js_path = os.path.join(C.GEN, tag + ".js")
    out_path = os.path.join(C.GEN, tag + ".out.json")
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(js_code)
    _node(["evalfile", "courses.ecnu.edu.cn", js_path, out_path])
    with open(out_path, encoding="utf-8") as f:
        raw = f.read().strip()
    try:
        return json.loads(raw)
    except Exception:
        return {"_raw": raw}


# ------------------------------------------------------------------ 平台接口
def list_courses():
    with open(os.path.join(C.PROBES, "list_courses.js"), encoding="utf-8") as f:
        return run_probe(f.read(), "list_courses")


def sessions_of(tecl_id):
    js = """(async () => {
  const base = '%s';
  const u = `${base}/v1/subject_vod_list_new?page.pageIndex=1&page.pageSize=200&teclIds=%s`
    + '&page.orders[0].asc=true&page.orders[0].field=courBeginTime';
  const r = await fetch(u, { credentials: 'include', headers: { Accept: 'application/json' } });
  const j = await r.json();
  const recs = (j.data && (j.data.records || j.data.list)) || [];
  const fmt = (t) => {
    if (!t) return null;
    if (typeof t === 'string') return t.replace('T', ' ').slice(0, 16);
    const d = new Date(t); const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  };
  return JSON.stringify(recs.map((x) => ({
    courseId: x.id, courseNo: x.courseNo, begin: fmt(x.courBeginTime), end: fmt(x.courEndTime),
    vodStatus: x.vodStatus, transcriptTask: x.transcriptOptimizeTaskStatus,
  })));
})()""" % (API, tecl_id)
    return run_probe(js, "sessions_%s" % tecl_id)


def vod_urls(course_ids):
    js = """(async () => {
  const base = '%s';
  const ids = %s;
  const out = {};
  for (const cid of ids) {
    const r = await fetch(`${base}/v1/course_vod_urls_new?courseId=${cid}`,
      { credentials: 'include', headers: { Accept: 'application/json' } });
    const j = await r.json();
    const d = j.data || {};
    out[cid] = { courName: d.courName, begin: d.courBeginTime,
      list: (d.courseVodViewList || []).map((v) => ({ vodId: v.vodId, vodTime: v.vodTime, url: v.url })) };
  }
  return JSON.stringify(out);
})()""" % (API, json.dumps(course_ids))
    return run_probe(js, "vod_urls")


# ------------------------------------------------------------------ 课程定位
def _url_hints(url):
    hints = {}
    for k in ("subjId", "teclId", "courseId", "id"):
        m = re.search(r"[?&]%s=(\d+)" % k, url, re.I)
        if m:
            hints[k.lower()] = int(m.group(1))
    m = re.search(r"/(\d{4,6})(?:[/?#]|$)", url)
    if m:
        hints.setdefault("numeric", int(m.group(1)))
    return hints


def match_course(url, courses):
    """按 URL 里的 id / 数字 / 课程名定位课程，返回 (course|None, 候选列表)"""
    hints = _url_hints(url)
    for key in ("teclid", "subjid", "courseid"):
        if key in hints:
            for c in courses:
                if hints[key] in (c.get("teclId"), c.get("subjId")):
                    return c, courses
    if "numeric" in hints:
        v = hints["numeric"]
        for c in courses:
            if v in (c.get("teclId"), c.get("subjId")):
                return c, courses
    # 按课程名匹配 URL（URL 里常带课程名或拼音，退化为只保留一条时直接用它）
    if len(courses) == 1:
        return courses[0], courses
    return None, courses


def _norm_name(s):
    return re.sub(r"[《》\s\-—_·:：()（）]", "", (s or "")).lower()


def sniff_page_ids(wait_ms=9000):
    """读页面自己发出的请求与 storage，嗅探课程/科目编号。

    用途：播放页的 URL 往往只是一串加密 token（如 `#/play-center?mko2GSK...==`），
    读不出课程身份；但 SPA 渲染时必然请求带 `courseId=` 的接口，从这些 URL 里就能反推。
    必须在调用我们自己的接口**之前**执行，避免污染（我们按 teclIds=... 查询）。
    """
    js = """(async () => {
  const pat = /(?:courseId|subjId|teclId)=(\\d{3,8})/g;
  const scan = (s) => { const out = []; let m; pat.lastIndex = 0;
    while ((m = pat.exec(s))) out.push(m[1]); return out; };
  const deadline = Date.now() + %d;
  let resources = [];
  while (Date.now() < deadline) {
    resources = performance.getEntriesByType('resource').map((e) => e.name);
    const stores = [];
    try { for (const k in localStorage) stores.push(k); } catch (e) {}
    try { for (const k in sessionStorage) stores.push(k); } catch (e) {}
    const net = [], store = [];
    for (const u of resources) for (const id of scan(u)) net.push(u);
    for (const k of stores) {
      let v = '';
      try { v = localStorage.getItem(k) || sessionStorage.getItem(k) || ''; } catch (e) {}
      if (scan(v).length) store.push(k + ' :: ' + v.slice(0, 200));
    }
    if (net.length || store.length)
      return JSON.stringify({ found: true, net: net, store: store, resources: resources.slice(-40) });
    await new Promise((r) => setTimeout(r, 600));
  }
  return JSON.stringify({ found: false, net: [], store: [],
    resources: performance.getEntriesByType('resource').map((e) => e.name).slice(-40) });
})()""" % wait_ms
    d = run_probe(js, "sniff")
    if not isinstance(d, dict) or "_raw" in d:
        return {"found": False, "net": [], "store": [], "raw": str(d)[:300]}
    return d


def course_name_of(course_ids):
    """用 courseId 反查课程名（播放页只给 courseId 时用）。"""
    js = """(async () => {
  const base = '%s';
  const ids = %s;
  const out = {};
  for (const cid of ids) {
    try {
      const r = await fetch(`${base}/v1/course_vod_urls_new?courseId=${cid}`,
        { credentials: 'include', headers: { Accept: 'application/json' } });
      const j = await r.json();
      const d = j.data || {};
      out[cid] = { courName: d.courName || null,
                   begin: d.courBeginTime || null,
                   count: (d.courseVodViewList || []).length };
    } catch (e) { out[cid] = { error: e.message }; }
  }
  return JSON.stringify(out);
})()""" % (API, json.dumps(course_ids))
    return run_probe(js, "names_%s" % "_".join(str(c) for c in course_ids[:3]))


def match_sniff(d, courses):
    """把嗅探结果与课程列表对上号；认不出返回 None。"""
    if not d or not d.get("found"):
        print("  [嗅探] 页面暂时没发出带课程编号的请求（资源 %d 条）" % len((d or {}).get("resources") or []))
        return None

    ids = {"courseId": set(), "subjId": set(), "teclId": set()}
    for u in d.get("net") or []:
        for k in ids:
            for m in re.finditer(k + r"=(\d+)", u):
                ids[k].add(int(m.group(1)))
    for s in d.get("store") or []:
        for k in ids:
            for m in re.finditer(k + r"=(\d+)", s):
                ids[k].add(int(m.group(1)))
    ids = {k: sorted(v) for k, v in ids.items()}
    print("  [嗅探] 命中 → teclId=%s subjId=%s courseId=%s" % (
        ids["teclId"][:3], ids["subjId"][:3], ids["courseId"][:5]))

    # ① 直接命中课程列表里的 teclId / subjId
    for c in courses:
        if c.get("teclId") in ids["teclId"] or c.get("subjId") in ids["subjId"]:
            print("  [嗅探] 直接命中 → %s（teclId=%s）" % (c.get("subjName"), c.get("teclId")))
            return c

    # ② 用 courseId 反查课程名，再按名字匹配
    if ids["courseId"]:
        names = course_name_of(ids["courseId"][:3])
        if isinstance(names, dict) and "_raw" not in names:
            for cid, info in names.items():
                cname = _norm_name((info or {}).get("courName"))
                if not cname:
                    continue
                for c in courses:
                    sname = _norm_name(c.get("subjName"))
                    if sname and (cname.startswith(sname) or sname in cname):
                        print("  [嗅探] courseId=%s 的 courName=%s → %s" % (
                            cid, info.get("courName"), c.get("subjName")))
                        return c
    return None


def match_name(name, courses):
    """按课程名定位课程：先归一化后精确相等，再双向子串包含；多门命中就交给用户选。

    返回 (course|None, 候选列表)。候选列表在"没认准"时给出，供上层列出来让用户点。
    """
    q = _norm_name(name)
    if not q:
        return None, courses
    exact = [c for c in courses if _norm_name(c.get("subjName")) == q]
    if len(exact) == 1:
        return exact[0], courses
    if exact:
        return None, exact
    part = [c for c in courses
            if q in _norm_name(c.get("subjName")) or _norm_name(c.get("subjName")) in q]
    if len(part) == 1:
        return part[0], courses
    return None, (part or courses)


def resolve_course(url=None, tecl_id=None, login_wait=0, course_name=None, headless=False):
    """完整流程：浏览器 → 打开页面 → 定位课程 → 节次 → 直链。

    url 可以为 None：此时按 course_name（课程名）或 tecl_id 直接定位——
    对应用户"只报一个课程名"的开场场景。

    headless=True：用无头浏览器（不弹窗），调用方负责跑完 close_browser()。

    返回体里可能带：
      _need_login  用户还没登录（浏览器已打开，等用户登完重跑即可）
      _need_choice 无法判断是哪门课（附带 courses 候选）
    """
    if not (url or tecl_id or course_name):
        raise RuntimeError("必须给出 url / course_name / tecl_id 之一")
    ensure_browser(headless=headless)
    if url:
        goto(url)
    if not logged_in():
        if login_wait and login_wait > 0:
            print("[登录] 请在打开的 Edge 窗口里完成 CAS 登录（最多等 %d 秒）…" % login_wait)
            _node(["waitlogin", str(login_wait)])
            goto(url)
            if not logged_in():
                return {"_need_login": True, "sourceUrl": url}
        else:
            return {"_need_login": True, "sourceUrl": url}

    # 嗅探必须在调我们自己的接口之前（否则 performance 里会混入我们自己的 teclIds= 查询）
    sniff = None if (tecl_id or course_name) else sniff_page_ids()

    courses = list_courses()
    if isinstance(courses, dict) and "_raw" in courses:
        raise RuntimeError("取课程列表失败：" + courses["_raw"][:300])

    if tecl_id:
        course = next((c for c in courses if c.get("teclId") == int(tecl_id)), None)
    elif course_name:                               # ③ 用户只报了课名：按名字匹配
        course, cands = match_name(course_name, courses)
        if not course:
            return {"_need_choice": True, "courses": cands, "query": course_name}
    else:
        course, _ = match_course(url, courses)      # ① URL 里带 id 的常规情形
        if not course and sniff:                    # ② 播放页加密链接：靠页面流量反推
            course = match_sniff(sniff, courses)
    if not course:
        return {"_need_choice": True, "courses": courses}

    sessions = sessions_of(course["teclId"])
    if isinstance(sessions, dict) and "_raw" in sessions:
        raise RuntimeError("取节次失败：" + sessions["_raw"][:300])
    if not sessions:
        raise RuntimeError("该课程没有点播记录（teclId=%s）" % course["teclId"])

    urls = vod_urls([s["courseId"] for s in sessions])
    if isinstance(urls, dict) and "_raw" in urls:
        raise RuntimeError("取直链失败：" + urls["_raw"][:300])

    rows = []
    for s in sessions:
        d = urls.get(str(s["courseId"])) or {}
        streams = d.get("list") or []
        rows.append({
            "courseId": s["courseId"],
            "date": (s.get("begin") or "")[:10],
            "begin": s.get("begin"),
            "end": s.get("end"),
            "duration": streams[0]["vodTime"] if streams else None,
            "vodId": streams[0]["vodId"] if streams else None,
            "url": streams[0]["url"] if streams else None,
            "streamCount": len(streams),
            "courName": d.get("courName") or course.get("subjName"),
        })

    # 同一日期内按开始时间编号 1..N
    rows.sort(key=lambda x: (x["date"] or "", x["begin"] or ""))
    per_date = {}
    for r in rows:
        n = per_date.get(r["date"], 0) + 1
        per_date[r["date"]] = n
        r["index"] = n
        mmdd = (r["date"] or "").replace("-", "")[4:]
        r["segName"] = "%s-%d" % (mmdd or "seg", n)

    return {"course": course, "sessions": rows, "sourceUrl": url,
            "resolvedAt": time.strftime("%Y-%m-%d %H:%M:%S")}


CHECK_API_JS = """(async () => {
  // 用课件接口做鉴权探针：登录页/失效时会返回 HTML 或干脆跨域失败，正常时是 200 + JSON。
  // 必须用绝对 URL：页面可能正停在 sso.ecnu.edu.cn 上，相对路径会打到 SSO 域名上去。
  const u = 'https://courses.ecnu.edu.cn/jy-application-resourcemanage/v1/course/ai/ppt?courseId=539136';
  try {
    const r = await fetch(u, { credentials: 'include', headers: { Accept: 'application/json' } });
    const t = await r.text();
    let o = null, parsed = false;
    try { o = JSON.parse(t); parsed = true; } catch (_) {}
    return JSON.stringify({
      origin: location.origin, status: r.status, json: parsed,
      ok: parsed && o && o.ok === true,
      code: parsed && o ? o.code : null,
      head: t.slice(0, 120),
    });
  } catch (e) {
    return JSON.stringify({ origin: location.origin, err: String(e.message).slice(0, 120) });
  }
})()"""


def api_logged_in():
    """接口级登录判定（保守）：只在**明确失效**时否决 URL 判定。

    为什么保守：实测从平台域名内部请求课件接口，未登录也可能拿到 200+JSON，
    所以“接口通了”不足以证明登录有效；但“返回 HTML / 跨域失败 / 非 200”足以证明**失效**
    —— 2026-11-17 那次「课件接口返回非 JSON + 旧检查仍显示有效」就是这么漏过去的。
    返回 (verdict, detail)，verdict ∈ {True 明确有效, False 明确失效, None 无法判定}。
    """
    res, last = None, ""
    for _ in range(4):
        try:
            res = run_probe(CHECK_API_JS, "login_check")
            break
        except Exception as e:
            last = str(e)[:160]      # 页面在跳转时 evaluate 会报 Execution context was destroyed
            res = None
            time.sleep(2.5)
    if res is None:
        return None, "接口探测失败：%s" % last
    if isinstance(res, dict) and "status" not in res and "_raw" in res:
        try:                         # 探针把结果当字符串回传时再解一层
            res = json.loads(res["_raw"])
        except Exception:
            pass
    if not isinstance(res, dict):
        return None, "接口返回不可解析：%s" % str(res)[:120]
    if res.get("err"):
        return None, "接口不可达：%s" % str(res.get("err"))[:100]
    status, code = res.get("status"), res.get("code")
    if status == 200 and res.get("json") and (res.get("ok") or code in (0, "0", None)):
        return True, "接口 200 + JSON（ok）"
    return False, "接口 status=%s code=%s head=%s" % (
        status, code, str(res.get("head"))[:100])


def check_login(headless=True, deep=True):
    """一次性检查：开浏览器 → 访问课程平台 → 判断登录态 → 关掉（不试图续期会话）。

    deep=True 时再做一次**接口级**校验（页面离开 SSO 不代表接口有权限）。
    """
    ensure_browser(headless=headless)
    goto("https://courses.ecnu.edu.cn")
    ok = logged_in_wait(12)
    detail = "页面已进入业务页" if ok else "页面仍停在登录页"
    if ok and deep:
        verdict, adetail = api_logged_in()
        if verdict is False:
            ok = False                  # 只有“明确失效”才否决，避免接口抖动误杀有效会话
        detail = adetail if verdict is not None else "%s（%s）" % (detail, adetail)
    if not headless:
        if detail:
            print("[登录] 判定依据：%s" % detail, file=sys.stderr)
        return ok
    close_browser()
    if detail:
        print("[登录] 判定依据：%s" % detail, file=sys.stderr)
    return ok


def qr_login(out_png, timeout=180, headless=True):
    """无头生成二维码并等待扫码登录，截图存到 out_png。

    返回 dict：{"ok": True/False, "qr": 路径, "reason": ...}
    """
    ensure_browser(headless=headless)
    # 先删掉上次残留的二维码，避免失败时把旧图当成本次结果发出去
    try:
        if os.path.exists(out_png):
            os.remove(out_png)
    except Exception:
        pass
    r = C.run(["node", os.path.join(C.HERE, "qr_login.js"), out_png, str(timeout)])
    txt = (r.stdout or "").strip()
    ok = "LOGIN_OK" in txt
    if headless:
        close_browser()
    return {"ok": ok, "qr": out_png if os.path.exists(out_png) else None,
            "raw": txt[-600:]}


if __name__ == "__main__":
    url = sys.argv[1]
    tecl = sys.argv[2] if len(sys.argv) > 2 else None
    info = resolve_course(url, tecl)
    print(json.dumps(info, ensure_ascii=False, indent=1))
