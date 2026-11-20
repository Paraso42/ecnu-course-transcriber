#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""平台「AI 课件」切片 —— 按节次抓 PPT 截图 + 画面 OCR，按讲次（上课日）归组。

平台接口（需登录态，前端同源调用）：
    GET /jy-application-resourcemanage/v1/course/ai/ppt?courseId=<courseId>
    → data.docList[] = { imageId, imageSeekTime(该段内秒), imageUrl(jpg 直链),
                         ocrText(画面文字), pptDocId, imageSnapshotTime }

要点：
  * 这是**相机拍投影**的截图，不是 PPT 原件（平台不提供原件下载）；
  * imageUrl 是公开直链，下载不需要 cookie；
  * 同一讲次内按 md5 去重（同页停留会被截多次），PDF 只留首次出现；
  * 每张图文件名的秒数 = 段内出现时刻，可与同段 m4a / raw.txt 的 [HH:MM:SS] 对齐。

对外主函数：
    rep = grab(course, sessions, out_root=None, run_root=None, ...)
"""
import hashlib
import json
import os
import re
import time
import urllib.request

import common as C
import session_resolve as S

API = "https://courses.ecnu.edu.cn/jy-application-resourcemanage"   # 绝对地址：页面可能正停在 SSO 域
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0 Safari/537.36")
NOISE_HINT = ("srunportal", "srun_portal", "此电脑", "回收站", "控制面板", "登录")


# ------------------------------------------------------------------ 基础工具
def safe_name(s):
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]", "_", (s or "").strip())
    return s[:60] or "course"


def _hhmmss(sec):
    sec = max(0, int(sec or 0))
    return "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def _http_get(url, tries=3, timeout=45):
    """课件图片是公开直链，不需要 cookie；仍带常规头，失败重试。"""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Referer": "https://courses.ecnu.edu.cn/",
                "Accept": "image/avif,image/webp,image/jpeg,*/*",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:                       # 网络抖动重试
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("下载失败：…%s（%s）" % (url[-48:], last))


def _looks_noise(ocr):
    """粗判桌面/登录页这类非课件画面（只在索引里标注，不删文件）。"""
    t = (ocr or "").strip()
    if not t:
        return True
    return sum(1 for k in NOISE_HINT if k in t) >= 1


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------ 平台接口
class LoginRequired(RuntimeError):
    """平台返回登录页/401 —— 说明是登录态失效，不是“这天没课件”。"""


def _looks_like_login_page(raw):
    head = (raw or "")[:600].lstrip().lower()
    return (head.startswith("<!doctype") or head.startswith("<html")
            or "<title>统一登录" in (raw or "")
            or "sso.ecnu.edu.cn" in (raw or "")[:2000])


def ppt_docs(course_id):
    """取一个 courseId 的课件切片清单（含 OCR 文字），按出现时刻排序。"""
    js = """(async () => {
  const r = await fetch('%s/v1/course/ai/ppt?courseId=%s',
    { credentials: 'include', headers: { Accept: 'application/json' } });
  return await r.text();
})()""" % (API, course_id)
    res = S.run_probe(js, "ppt_%s" % course_id)
    raw = res.get("_raw") if isinstance(res, dict) else None
    if raw is None:
        raw = json.dumps(res, ensure_ascii=False)
    try:
        j = json.loads(raw)
    except Exception:
        if _looks_like_login_page(raw):
            raise LoginRequired(
                "课件接口返回登录页（登录态已失效，courseId=%s）" % course_id)
        raise RuntimeError("课件接口返回非 JSON（courseId=%s）：%s" % (course_id, str(raw)[:200]))
    if j.get("code") not in (None, 0, "0"):
        raise RuntimeError("课件接口报错（courseId=%s）：%s" % (course_id, j.get("message")))
    docs = ((j.get("data") or {}).get("docList")) or []
    out = []
    for d in docs:
        url = d.get("imageUrl") or ""
        if not url:
            continue
        out.append({
            "seek": int(d.get("imageSeekTime") or 0),
            "url": url,
            "ocr": (d.get("ocrText") or "").replace("\r", " ").replace("\n", " ").strip(),
            "snap": d.get("imageSnapshotTime"),
        })
    out.sort(key=lambda x: x["seek"])
    return out


# ------------------------------------------------------------------ 单段下载
def grab_segment(seg_dir, docs, force=False):
    """下载一段的切片。已存在且非空则跳过（断点续跑）。

    返回 (files, fails)；files = [(本地路径, doc)]，序号按接口返回顺序，不从失败处顺延。
    docs 为空时**不建目录**（避免留下一个空文件夹和 0 字节 ocr.txt，和“失败”混淆）。
    """
    files, fails = [], []
    if not docs:
        return files, fails
    C.ensure_dirs(seg_dir)
    for i, d in enumerate(docs, 1):
        name = "%02d_seek%05d.jpg" % (i, d["seek"])
        p = os.path.join(seg_dir, name)
        if os.path.exists(p) and os.path.getsize(p) > 10 * 1024 and not force:
            files.append((p, d))
            continue
        try:
            blob = _http_get(d["url"])
        except Exception as e:
            fails.append((d["seek"], str(e)))
            continue
        with open(p, "wb") as f:
            f.write(blob)
        files.append((p, d))
    return files, fails


def _write_ocr_txt(seg_dir, seg, date, files, fails, docs_n):
    if not files and not fails:
        return          # 接口返回 0 张：不写空 ocr.txt（否则和“下载失败”长得一样）
    C.ensure_dirs(seg_dir)
    lines = ["# %s  %s  课件截图（平台 AI 切片：接口返回 %d 张，落盘 %d 张）" % (
        seg, date, docs_n, len(files)),
        "# [出现时刻] seek=秒  本地文件  画面文字（OCR 原样，仅供定位，以图为准）", ""]
    for p, d in files:
        lines.append("[%s] seek=%s %s  %s" % (
            _hhmmss(d["seek"]), d["seek"], os.path.basename(p), d["ocr"][:400]))
    for seek, err in fails:
        lines.append("[%s] seek=%s 下载失败 %s" % (_hhmmss(seek), seek, err))
    with open(os.path.join(seg_dir, "ocr.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ------------------------------------------------------------------ 归组产物
def _dedupe(files_by_seg):
    """跨段去重：同一讲次里完全相同的帧只留首次。返回 [(seg, path, doc, md5)]。"""
    seen, keep = {}, []
    for seg, files in files_by_seg:
        for p, d in files:
            h = _md5(p)
            if h in seen:
                continue
            seen[h] = (seg, os.path.basename(p))
            keep.append((seg, p, d, h))
    return keep


def _write_index(ldir, label, seg_order, files_by_seg):
    rows, seen = [], {}
    for seg, files in files_by_seg:
        for p, d in files:
            h = _md5(p)
            dup = seen.get(h)
            if not dup:
                seen[h] = "%s@%s" % (seg, _hhmmss(d["seek"]))
            rows.append((seg_order.index(seg) if seg in seg_order else 99,
                         d["seek"], seg, os.path.basename(p), d["ocr"], dup))
    rows.sort(key=lambda r: (r[0], r[1]))

    out = ["# %s 课件索引" % label, "",
           "共 %d 张（按段内时刻排序）。文件名里的秒数 = 该段视频内的出现时刻，"
           "可直接对齐同段 m4a / raw.txt 的 [HH:MM:SS]。" % len(rows), "",
           "| # | 段 | 出现时刻 | 文件 | 类型 | 画面文字（节选） |",
           "|---|---|---|---|---|---|"]
    for i, (_, seek, seg, name, ocr, dup) in enumerate(rows, 1):
        kind = "重复帧" if dup else ("疑似非课件" if _looks_noise(ocr) else "课件")
        note = ("（同 %s）" % dup) if dup else ""
        txt = re.sub(r"\s+", " ", (ocr or "")).replace("|", "/")[:90]
        out.append("| %d | %s | %s | %s%s | %s | %s |" % (
            i, seg, _hhmmss(seek), name, note, kind, txt))
    with open(os.path.join(ldir, "索引.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return len(rows)


def _write_pdf(ldir, label, ordered):
    """把去重后的帧按时间顺序合成一份 PDF（PIL 缺失则跳过，不影响 jpg）。"""
    try:
        from PIL import Image
    except Exception as e:
        print("  [PDF 跳过] 缺 Pillow：%s" % e)
        return None
    if not ordered:
        return None
    pages = []
    for p in ordered:
        try:
            pages.append(Image.open(p).convert("RGB"))
        except Exception:
            continue
    if not pages:
        return None
    pdf = os.path.join(ldir, "%s_幻灯片.pdf" % safe_name(label))
    try:
        pages[0].save(pdf, "PDF", save_all=True, append_images=pages[1:], resolution=150.0)
    except Exception as e:
        print("  [PDF 失败] %s" % e)
        return None
    return pdf


README_TPL = """# {title} 课件截图

## 这是什么
平台自带的「AI 课件」切片：系统从每段录播里自动按讲授页截取画面，并把画面上的文字 OCR 出来。
**不是老师的 PPT 原文件**（平台不提供下载），是投影/屏幕的相机截图，通常 1920×1080。

抓取时间：{when}
抓取接口：`GET {api}/v1/course/ai/ppt?courseId=<courseId>`

## 目录
```
{tree}
_课件清单.json        ← 逐段切片数、失败项、PDF 页数
```

文件名 `NN_seekSSSSS.jpg`：`NN` 段内序号，`SSSSS` = 该段视频内出现时刻（秒），
可与同段 `m4a` / `raw.txt` 的 `[HH:MM:SS]` 直接对齐（如 `05_seek00362.jpg` = 该段 00:06:02）。

## 已知局限
1. 投影照片：有反光、透视、相机噪点；标题行常被 IPCamera 时间戳压住，正文一般可读。
2. 截的是教师屏幕，所以夹着桌面 / 文件夹 / Word / 浏览器等演示画面，`索引.md` 的“类型”列已标出。
3. 覆盖率不均：有的段只有几张（当堂在讲课程要求、或人声极少），有的段几十张。
4. 同页停留会被截多次，已按字节去重，PDF 只保留首次出现。
5. OCR 文字有错字（与语音转写同类问题，如 `五项色`→`5-羟色胺`），**以图为准**，不要直接引用文字。

## 建议用法
先用 `索引.md` 扫一遍挑出真课件页 → 对照 jpg 校正术语 → 再按秒数回到同段转写，
得到“这一页老师讲了什么”。术语校正与知识梳理在课程工作区里做，本目录只提供素材。
"""


def _write_readme(root, title, tree_lines, when):
    with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as f:
        f.write(README_TPL.format(title=title, when=when, api=API,
                                  tree="\n".join(tree_lines)))


# ------------------------------------------------------------------ 主入口
def grab(course, sessions, out_root=None, run_root=None, no_pdf=False,
         labels=None, force=False):
    """抓取指定节次的课件截图。

    course   : resolve 出来的 course 字典（subjName / teclId / subjCode）
    sessions : 要抓的节次列表（已按 --date 过滤）
    out_root : 独立运行时根目录（默认 <工作区>/courseware）
    run_root : 传了就写进该运行目录下的 courseware\\（与转写同一次运行同框）
    no_pdf   : 不合成 PDF
    labels   : {日期: 讲次名}，用于目录名，如 {"2026-09-15": "第1讲_导论"}
    force    : 已存在的图片也重下
    """
    labels = labels or {}
    title = "%s（%s）" % (course.get("subjName") or "课程", course.get("subjCode") or "-")
    if run_root:
        root = os.path.join(run_root, "courseware")
    else:
        root = os.path.join(out_root or os.path.join(C.ROOT, "courseware"),
                            "%s_%s_%s" % (safe_name(course.get("subjName")),
                                          course.get("teclId"), time.strftime("%Y-%m-%d")))
    C.ensure_dirs(root)

    groups = {}
    for s in sessions:
        groups.setdefault(s["date"], []).append(s)

    report = {"course": course.get("subjName"), "teclId": course.get("teclId"),
              "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"), "root": root,
              "lectures": [], "total": 0, "failed": []}
    tree_lines = []
    print("[课件] 平台 AI 切片：%d 天 / %d 段 → %s" % (len(groups), len(sessions), root))

    for date in sorted(groups):
        segs = sorted(groups[date], key=lambda s: s.get("begin") or "")
        label = labels.get(date) or date
        ldir = os.path.join(root, safe_name(label))
        print("=== %s  %s ===" % (label, date))

        files_by_seg, seg_order, per_seg = [], [], {}
        for s in segs:
            seg = s.get("segName") or "%s-%s" % (date.replace("-", "")[4:], s.get("index") or 1)
            seg_order.append(seg)
            seg_dir = os.path.join(ldir, seg)
            try:
                docs = ppt_docs(s["courseId"])
            except LoginRequired:
                raise                      # 登录态失效：整次中止，由调用方报“需要登录”
            except Exception as e:
                print("  %s  接口失败：%s" % (seg, e))
                report["failed"].append({"seg": seg, "date": date, "error": "接口失败：%s" % e})
                per_seg[seg] = 0
                continue
            files, fails = grab_segment(seg_dir, docs, force=force)
            _write_ocr_txt(seg_dir, seg, date, files, fails, len(docs))
            files_by_seg.append((seg, files))
            per_seg[seg] = len(files)
            print("  %s  切片 %d 张%s" % (seg, len(files),
                                         "" if not fails else "（%d 张失败）" % len(fails)))
            for seek, err in fails:
                report["failed"].append({"seg": seg, "date": date,
                                         "error": "seek=%s %s" % (seek, err)})
            report["total"] += len(files)

        keep = _dedupe(files_by_seg)
        pdf = None
        n_index = 0
        if keep:
            C.ensure_dirs(ldir)                     # 有图才建讲次目录
            n_index = _write_index(ldir, label, seg_order, files_by_seg)
            if not no_pdf:
                pdf = _write_pdf(ldir, label, [p for _, p, _, _ in keep])
        report["lectures"].append({
            "date": date, "label": label, "dir": ldir if keep else None,
            "segments": per_seg, "index_rows": n_index,
            "pdf": pdf, "pdf_pages": len(keep) if pdf else 0})
        n_seg_imgs = sum(per_seg.values())
        if n_seg_imgs:
            tree_lines.append("%s\\   （%d 段 / %d 张%s）" % (
                safe_name(label), len(segs), n_seg_imgs,
                " / %d 页 PDF" % len(keep) if pdf else ""))
        day_failed = [f for f in report["failed"] if f["date"] == date]
        if n_seg_imgs == 0 and not day_failed:
            # 只有“接口正常返回 0 张”才敢说这句；有失败项时不许下这个结论
            print("  [注意] 这天没有课件切片（平台本讲无切片：当天可能没讲课/在放片）")
        elif n_seg_imgs == 0 and day_failed:
            print("  [注意] 这天 %d 个节次全部取失败，原因见上（不等于“没讲课”）" % len(day_failed))

    _write_readme(root, title, tree_lines, time.strftime("%Y-%m-%d %H:%M"))
    with open(os.path.join(root, "_课件清单.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    print("\n[课件] 完成：%d 张 / %d 天%s" % (
        report["total"], len(report["lectures"]),
        "" if not report["failed"] else "；失败 %d 项" % len(report["failed"])))
    print("[课件] 目录：%s" % root)
    return report


def ensure_login(headless=False):
    """课件接口需要登录态：浏览器没开就开（可按需无头），开了再确认已进入业务页。"""
    S.ensure_browser(headless=headless)
    return S.logged_in_wait(12)


def parse_labels(text):
    """--label "2026-09-15=第1讲_导论,2026-09-20=第2讲_神经科学基础" → dict"""
    out = {}
    for part in (text or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out
