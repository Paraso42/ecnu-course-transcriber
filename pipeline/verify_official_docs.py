#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验：官方字幕/总结 Word 是否与平台原文逐字一致、时间戳行数是否与字幕条数一致。"""
import json
import os
import re
import sys

from docx import Document

TS = re.compile(r"^\[\d{2}:\d{2}:\d{2}\] ")


def main(run):
    idx = json.load(open(os.path.join(run, "official", "official_subtitles.json"), encoding="utf-8"))
    segs = [x for x in idx["sessions"] if x.get("has_official")]
    bad = []
    for x in segs:
        seg, date = x["segName"], x["date"]
        cap = json.load(open(os.path.join(run, "official", date, seg + ".official.json"), encoding="utf-8"))
        summ = json.load(open(os.path.join(run, "official", date, seg + ".summary.json"),
                              encoding="utf-8"))["data"]
        doc = Document(os.path.join(run, "official", "word",
                                    "%s_%s_官方字幕与总结.docx" % (seg, date)))
        paras = [p.text for p in doc.paragraphs]
        text = "\n".join(paras)
        errs = []
        if any(c["text"] not in text for c in cap["captions"]):
            errs.append("字幕内容缺失或被改写")
        if summ.get("fullOverview") and summ["fullOverview"] not in text:
            errs.append("全文概述不一致")
        if any(k not in text for k in summ.get("keyPoints") or []):
            errs.append("要点不一致")
        for sk in summ.get("documentSkims") or []:
            if sk["content"] not in text:
                errs.append("分段摘要不一致")
            if (sk.get("overview") or "") not in text:
                errs.append("分段标题不一致")
        n_ts = sum(1 for p in paras if TS.match(p))
        if n_ts != len(cap["captions"]):
            errs.append("时间戳行 %d ≠ 字幕 %d 条" % (n_ts, len(cap["captions"])))
        print("%-7s %s  段落 %-5d 字幕 %-5d %s" % (seg, date, len(paras), len(cap["captions"]),
                                                   "OK" if not errs else "FAIL " + "; ".join(errs)))
        if errs:
            bad.append(seg)
    print("\n合计 %d 份，%s" % (len(segs), "全部通过" if not bad else "失败：" + "、".join(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "outputs"))
