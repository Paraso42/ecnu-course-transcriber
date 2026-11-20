#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把平台官方字幕 + AI 总结排成 Word（每段一份：前面字幕、后面总结）。

**内容一个字也不改**：所有正文都是 official\\<日期>\\<段名>.official.json /
.summary.json 里的平台原文，逐字复制；本模块只负责分节、加标题、排时间戳。

用法（一般由 official_sub.py --docx 调用）：
    python pipeline\\official_docx.py --run-dir outputs\\<本次运行>
"""
import argparse
import json
import os
import sys

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor


def _font(run, name="宋体", size=10.5, bold=False, color=None):
    run.font.name = name
    run.font.size = Pt(size)
    run.bold = bold
    if color:
        run.font.color.rgb = RGBColor(*color)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def _para(doc, text, name="宋体", size=10.5, bold=False, space_after=4, align=None,
          color=None, indent=0):
    p = doc.add_paragraph()
    if align:
        p.alignment = align
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    pf.line_spacing = 1.25
    if indent:
        pf.left_indent = Pt(indent)
    r = p.add_run(text)
    _font(r, name, size, bold, color)
    return p


def _heading(doc, text, level, size, color=(0x1F, 0x3B, 0x73)):
    p = doc.add_heading(level=level)
    p.paragraph_format.space_before = Pt(14 if level == 1 else 10)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(text)
    _font(r, "微软雅黑", size, bold=True, color=color)
    return p


def fmt_ts(sec):
    sec = max(0, int(round(sec)))
    return "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def build_one(run_dir, course, seg, date, begin):
    off_dir = os.path.join(run_dir, "official", date)
    with open(os.path.join(off_dir, seg + ".official.json"), encoding="utf-8") as f:
        cap = json.load(f)
    sum_path = os.path.join(off_dir, seg + ".summary.json")
    summ = None
    if os.path.exists(sum_path):
        with open(sum_path, encoding="utf-8") as f:
            summ = (json.load(f).get("data") or {})

    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = "宋体"
    st.font.size = Pt(10.5)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")

    subj = (course or {}).get("subjName") or ""
    _para(doc, "%s　%s" % (subj, seg), "微软雅黑", 20, True, space_after=2,
          align=WD_ALIGN_PARAGRAPH.CENTER, color=(0x1F, 0x3B, 0x73))
    _para(doc, "官方语音识别字幕 + AI 总结（平台原文，未改动）", "微软雅黑", 11, False,
          space_after=10, align=WD_ALIGN_PARAGRAPH.CENTER, color=(0x66, 0x66, 0x66))

    meta = "日期：%s　开始：%s　课程号：%s" % (
        date, (begin or "")[11:] or "-", (course or {}).get("subjCode") or "-")
    _para(doc, meta, "宋体", 9.5, space_after=2, align=WD_ALIGN_PARAGRAPH.CENTER,
          color=(0x88, 0x88, 0x88))
    _para(doc, "来源：华东师范大学课程平台（courses.ecnu.edu.cn）｜ 字幕 %d 条" % cap.get("count", 0),
          "宋体", 9.5, space_after=14, align=WD_ALIGN_PARAGRAPH.CENTER, color=(0x88, 0x88, 0x88))

    _heading(doc, "一、官方语音识别字幕", 1, 14)
    _para(doc, "（平台逐条转写结果，时间戳为平台给的起止时间，文字一字未改）", "宋体", 9,
          space_after=8, color=(0x88, 0x88, 0x88))
    for c in cap.get("captions") or []:
        _para(doc, "[%s] %s" % (fmt_ts(c["start"]), c["text"]), "宋体", 10.5, space_after=2)

    if summ:
        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        _heading(doc, "二、官方 AI 总结", 1, 14)
        _para(doc, "（平台生成的课后总结，文字一字未改）", "宋体", 9, space_after=8,
              color=(0x88, 0x88, 0x88))

        if summ.get("keyPoints"):
            _heading(doc, "要点", 2, 12)
            for k in summ["keyPoints"]:
                p = doc.add_paragraph(style="List Bullet")
                p.paragraph_format.space_after = Pt(2)
                _font(p.add_run(k), "宋体", 10.5)

        if summ.get("fullOverview"):
            _heading(doc, "全文概述", 2, 12)
            _para(doc, summ["fullOverview"], "宋体", 10.5, space_after=8)

        skims = summ.get("documentSkims") or []
        if skims:
            _heading(doc, "分段摘要", 2, 12)
            for sk in skims:
                _heading(doc, "[%s–%s] %s" % (fmt_ts((sk.get("bg") or 0) / 1000.0),
                                              fmt_ts((sk.get("ed") or 0) / 1000.0),
                                              sk.get("overview") or ""), 3, 11,
                         color=(0x33, 0x33, 0x33))
                _para(doc, sk.get("content") or "", "宋体", 10.5, space_after=10)

    outdir = os.path.join(run_dir, "official", "word")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "%s_%s_官方字幕与总结.docx" % (seg, date))
    doc.save(out)
    return out


def build_all(run_dir, summary, say=print):
    """对 official_subtitles.json 里每段有官方记录的节次生成一份 Word，返回路径列表。"""
    course = summary.get("course") or {}
    metas = {}
    for x in summary.get("sessions") or []:
        if x.get("has_official"):
            metas[x["segName"]] = x
    outs = []
    for seg, x in metas.items():
        p = build_one(run_dir, course, seg, x["date"], x.get("begin"))
        say("  [Word] %s" % os.path.basename(p))
        outs.append(p)
    # 记录到总览里，manifest 可以直接引用
    by_seg = {os.path.basename(p): p for p in outs}
    for x in summary.get("sessions") or []:
        if x.get("has_official"):
            fn = "%s_%s_官方字幕与总结.docx" % (x["segName"], x["date"])
            if fn in by_seg:
                x.setdefault("files", {})["docx"] = os.path.relpath(by_seg[fn], run_dir)
    return outs


def main():
    ap = argparse.ArgumentParser(description="官方字幕 + 总结 → 每段一份 Word")
    ap.add_argument("--run-dir", required=True)
    a = ap.parse_args()
    idx = os.path.join(a.run_dir, "official", "official_subtitles.json")
    if not os.path.exists(idx):
        print("[错误] 还没扒官方记录：%s" % idx)
        return 1
    with open(idx, encoding="utf-8") as f:
        summary = json.load(f)
    outs = build_all(a.run_dir, summary)
    with open(idx, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    print("\n生成 %d 份 Word → %s" % (len(outs), os.path.join(a.run_dir, "official", "word")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
