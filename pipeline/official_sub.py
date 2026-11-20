#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""抓平台的**官方语音识别记录**（课后字幕 + AI 总结），原样保存并生成 Word。

平台接口（课程平台 courses.ecnu.edu.cn，需登录态）：
    字幕  GET /jy-application-resourcemanage/v1/course_vod_subtitle?courseId=<id>
          → data[]：bg/ed 起止毫秒、res 文本
    总结  GET /jy-application-resourcemanage/v1/course/ai/summary/search/<courseId>
          → data：fullOverview、keyPoints[]、documentSkims[](bg/ed/overview/content)

产出（写进同一次运行的输出目录，与本地转写并列，放在 official\\ 下）：
    official\\<日期>\\<段名>.official.txt    逐条字幕：`[HH:MM:SS] 原文`（与平台一一对应）
    official\\<日期>\\<段名>.official.json   同上结构化（含平台原始 bg/ed 毫秒）
    official\\<日期>\\<段名>.summary.json    平台 AI 总结原始返回
    official\\<日期>\\<段名>.summary.txt     总结的可读版（字段逐字复制）
    official\\word\\<段名>_官方字幕与总结.docx  每段一份：前面字幕、后面总结
    official\\official_subtitles.json         全过程总览（哪些段有、哪些没有）

原则：**一个字也不改**——只做分节、加标题与时间戳排版，所有正文均为平台原文逐字复制。

用法：
    python pipeline\\official_sub.py --sessions sessions_new.json --run-dir outputs\\...
    python pipeline\\official_sub.py --sessions sessions_new.json --run-dir outputs\\... --since 2026-09-14
"""
import argparse
import json
import os
import sys
import time

import common as C
import session_resolve as S

API = "https://courses.ecnu.edu.cn/jy-application-resourcemanage"   # 绝对地址，不依赖当前页面 origin
EP_SUB = API + "/v1/course_vod_subtitle?courseId=%s"
EP_SUM = API + "/v1/course/ai/summary/search/%s"

PROBE = """(async () => {
  const r = await fetch('%s', { credentials: 'include', headers: { Accept: 'application/json' } });
  const t = await r.text();
  return JSON.stringify({ status: r.status, body: t });
})()"""


# ------------------------------------------------------------------ 取数
def _get(url, tag):
    d = S.run_probe(PROBE % url, tag)
    if not isinstance(d, dict) or "body" not in d:
        return None, None
    try:
        j = json.loads(d["body"])
    except Exception:
        return d.get("status"), None
    return d.get("status"), j


def fetch_subtitle(course_id):
    status, j = _get(EP_SUB % course_id, "sub")
    return status, ((j or {}).get("data") or [])


def fetch_summary(course_id):
    status, j = _get(EP_SUM % course_id, "sum")
    data = (j or {}).get("data") or {}
    if not data.get("fullOverview") and not (data.get("documentSkims") or []):
        return status, None
    return status, data


# ------------------------------------------------------------------ 落盘
def fmt_ts(sec):
    sec = max(0, int(round(sec)))
    return "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def write_subtitle(rows, outdir, seg, s, status):
    C.ensure_dirs(outdir)
    caps = []
    for r in rows:
        text = r.get("res") or ""
        if not text.strip():
            continue
        caps.append({"i": len(caps), "start": round((r.get("bg") or 0) / 1000.0, 2),
                     "end": round((r.get("ed") or 0) / 1000.0, 2), "text": text})
    txt = os.path.join(outdir, seg + ".official.txt")
    with open(txt, "w", encoding="utf-8") as f:
        for c in caps:
            f.write("[%s] %s\n" % (fmt_ts(c["start"]), c["text"]))
    meta = {
        "name": seg, "source": "课程平台官方语音识别记录（课后字幕）",
        "endpoint": EP_SUB % s["courseId"], "httpStatus": status,
        "courseId": s["courseId"], "date": s.get("date"), "begin": s.get("begin"),
        "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(caps), "chars": sum(len(c["text"]) for c in caps),
        "duration_sec": round(max([c["end"] for c in caps] or [0]), 2),
        "note": "逐条原样保存，未合并、未纠错；时间戳取自平台 bg 字段（毫秒→秒）",
        "captions": caps,
    }
    js = os.path.join(outdir, seg + ".official.json")
    with open(js, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return txt, js, meta


def write_summary(data, outdir, seg, s, status):
    C.ensure_dirs(outdir)
    js = os.path.join(outdir, seg + ".summary.json")
    payload = {"name": seg, "source": "课程平台 AI 总结", "endpoint": EP_SUM % s["courseId"],
               "httpStatus": status, "courseId": s["courseId"], "date": s.get("date"),
               "begin": s.get("begin"), "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "note": "平台返回原样保存，未改一字", "data": data}
    with open(js, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    txt = os.path.join(outdir, seg + ".summary.txt")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("# %s 官方 AI 总结（平台原文，未改动）\n\n" % seg)
        if data.get("keyPoints"):
            f.write("## 要点\n\n")
            for k in data["keyPoints"]:
                f.write("- %s\n" % k)
            f.write("\n")
        if data.get("fullOverview"):
            f.write("## 全文概述\n\n%s\n\n" % data["fullOverview"])
        skims = data.get("documentSkims") or []
        if skims:
            f.write("## 分段摘要\n\n")
            for sk in skims:
                f.write("### [%s–%s] %s\n\n%s\n\n" % (
                    fmt_ts((sk.get("bg") or 0) / 1000.0), fmt_ts((sk.get("ed") or 0) / 1000.0),
                    sk.get("overview") or "", sk.get("content") or ""))
    return txt, js, {"chars": len(data.get("fullOverview") or ""),
                     "keyPoints": len(data.get("keyPoints") or []),
                     "skims": len(data.get("documentSkims") or [])}


# ------------------------------------------------------------------ 主流程
def fetch_and_write(sessions, run_dir, course=None, source_url=None, skip_existing=True,
                    quiet=False, docs=False):
    """逐段扒官方字幕 + 总结，落到 <run_dir>\\official\\<日期>\\，可顺带生成 Word。"""
    def say(*a):
        if not quiet:
            print(*a)

    root = os.path.join(run_dir, "official")
    summary = {"course": course, "sourceUrl": source_url,
               "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "endpoints": {"subtitle": EP_SUB % "<courseId>", "summary": EP_SUM % "<courseId>"},
               "sessions": []}
    for s in sessions:
        seg = s.get("segName") or "%s-%s" % ((s.get("date") or "").replace("-", "")[4:], s.get("index"))
        outdir = os.path.join(root, s["date"])
        txt = os.path.join(outdir, seg + ".official.txt")
        js = os.path.join(outdir, seg + ".official.json")
        sjs = os.path.join(outdir, seg + ".summary.json")
        say("=== %s  %s ===" % (seg, s.get("begin")))

        cached = None
        if skip_existing and os.path.exists(js) and os.path.exists(sjs):
            try:
                with open(js, encoding="utf-8") as f:
                    cached = json.load(f)
            except Exception:
                cached = None
            if not (cached or {}).get("count"):
                cached = None
        if cached:
            say("  [复用] 已扒过 %d 条字幕 → %s" % (cached["count"], os.path.basename(txt)))
            with open(sjs, encoding="utf-8") as f:
                sm = json.load(f).get("data") or {}
            summary["sessions"].append({
                "segName": seg, "date": s["date"], "begin": s.get("begin"),
                "courseId": s["courseId"], "has_official": True,
                "count": cached["count"], "chars": cached.get("chars"),
                "duration_sec": cached.get("duration_sec"), "reused": True,
                "summary": {"chars": len(sm.get("fullOverview") or ""),
                            "keyPoints": len(sm.get("keyPoints") or []),
                            "skims": len(sm.get("documentSkims") or [])},
                "files": {"official_txt": os.path.relpath(txt, run_dir),
                          "official_json": os.path.relpath(js, run_dir),
                          "summary_json": os.path.relpath(sjs, run_dir)}})
            continue

        status, rows = fetch_subtitle(s["courseId"])
        if not rows:
            say("  [无] 平台没有该节次的识别记录（http %s）" % status)
            summary["sessions"].append({"segName": seg, "date": s["date"], "courseId": s["courseId"],
                                        "has_official": False, "httpStatus": status})
            continue
        txt, js, meta = write_subtitle(rows, outdir, seg, s, status)
        sstatus, sdata = fetch_summary(s["courseId"])
        sm = None
        if sdata:
            _, sjs, sm = write_summary(sdata, outdir, seg, s, sstatus)
        say("  [有] 字幕 %d 条 / %d 字；总结 %s" % (
            meta["count"], meta["chars"],
            ("要点 %d · 分段 %d" % (sm["keyPoints"], sm["skims"])) if sm else "无"))
        summary["sessions"].append({
            "segName": seg, "date": s["date"], "begin": s.get("begin"), "courseId": s["courseId"],
            "has_official": True,
            "count": meta["count"], "chars": meta["chars"], "duration_sec": meta["duration_sec"],
            "summary": sm,
            "files": {"official_txt": os.path.relpath(txt, run_dir),
                      "official_json": os.path.relpath(js, run_dir),
                      "summary_json": os.path.relpath(sjs, run_dir) if sm else None}})

    if docs:
        import official_docx
        official_docx.build_all(run_dir, summary, say=say)

    out = os.path.join(root, "official_subtitles.json")
    C.ensure_dirs(root)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    have = sum(1 for x in summary["sessions"] if x["has_official"])
    say("\n有官方记录 %d / %d 段 → %s" % (have, len(summary["sessions"]), out))
    return summary


def load_meta(run_dir, date, seg):
    """读取已落盘的官方字幕元信息（run.py 生成 manifest 时用）；没有则 None。"""
    p = os.path.join(run_dir, "official", date, seg + ".official.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="扒取课程平台的官方语音识别记录（字幕 + AI 总结）")
    ap.add_argument("--sessions", required=True, help="run.py resolve 生成的 sessions.json")
    ap.add_argument("--run-dir", required=True, help="写进哪次运行的输出目录")
    ap.add_argument("--dates", default=None, help="只扒这些日期（逗号分隔）；默认全部")
    ap.add_argument("--since", default=None, help="只扒该日期及之后，如 2026-10-10")
    ap.add_argument("--refresh", action="store_true", help="忽略本地已有文件，重新向平台取")
    ap.add_argument("--docx", action="store_true", help="同时生成每段一份的 Word（字幕 + 总结）")
    a = ap.parse_args()

    info = json.load(open(a.sessions, encoding="utf-8"))
    if isinstance(info, list):           # 兼容裸数组（pipeline\_gen\sessions_<id>.out.json）
        info = {"course": {}, "sessions": info}
    sessions = info.get("sessions") or []
    dates = [d.strip() for d in (a.dates or "").split(",") if d.strip()]
    if dates:
        sessions = [s for s in sessions if s["date"] in dates]
    if a.since:
        sessions = [s for s in sessions if (s["date"] or "") >= a.since]

    fetch_and_write(sessions, a.run_dir, info.get("course"), info.get("sourceUrl"),
                    skip_existing=not a.refresh, docs=a.docx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
