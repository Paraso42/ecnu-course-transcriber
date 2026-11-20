#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""原始转写 → 初步修正文本（只做浅层语法校准）。

允许改的（本步骤范围）：
  1) 口误重复折叠：这个这个 → 这个
  2) 单字结巴折叠：的的 / 了了 / 是是 …
  3) 标点规范化：连续标点折叠、半角转全角、句首多余标点、句末补句号
  4) 中文字符之间的多余空格
  5) 断句：超长无标点句在逗号/顿号处拆开

**明确不做**（留给后续课程工作区，结合课件做）：
  * 专业术语校正（干系胞→干细胞、引窝→隐窝、sonny 黑潮→Sonic hedgehog …）
  * 英文/数字的语义改写、同音字订正、人名与机构名核对
  * 内容增删、总结、改写

时间戳一律原样保留，保证能与音频、与 raw 版逐句对齐。
"""
import argparse
import os
import re
import sys

import common as C

# 常见口头重复单元（只在**紧邻重复**且中间无标点时折叠）
STUTTER_UNITS = [
    "这个", "那个", "我们", "你们", "他们", "就是", "然后", "所以", "但是",
    "因为", "如果", "其实", "应该", "可以", "知道", "不是", "这样", "那样",
    "什么", "怎么", "现在", "那么", "而且", "不过",
]
STUTTER_SINGLE = "的了是我你他她在就也都和与及对把被给让向从为以于"

PUNCT_MAP = {",": "，", ".": "。", "?": "？", "!": "！", ":": "：", ";": "；"}
SENT_END = "。？！"
CJK = r"[\u4e00-\u9fff]"


def fold_stutter(s):
    for u in STUTTER_UNITS:
        s = re.sub("(" + re.escape(u) + r")(?:\1)+", r"\1", s)
    s = re.sub("([" + STUTTER_SINGLE + r"])\1+", r"\1", s)
    # 指示/量词类重复：这一步这一步、这种这种、那样那样 …
    s = re.sub(r"((?:这|那)一?[个步种样些])(?:\1)+", r"\1", s)
    # 语气词结巴：呃呃呃 → 呃（语气词本身按约定保留）
    s = re.sub(r"([呃嗯啊哦呀])\1+", r"\1", s)
    return s


def normalize_punct(s):
    s = s.replace("...", "……").replace("。。。", "。")
    # 半角标点紧跟在中文之后 → 全角
    for a, b in PUNCT_MAP.items():
        s = re.sub("(?<=" + CJK + ")" + re.escape(a), b, s)
    s = re.sub(r"[，、]{2,}", "，", s)
    s = re.sub(r"([。？！])\1+", r"\1", s)
    s = re.sub(r"[，、；：]+(?=[。？！])", "", s)          # 句末标点前的多余逗号
    s = s.strip()
    s = re.sub(r"^[，、；：。？！\s]+", "", s)              # 句首标点
    return s


def strip_spaces(s):
    # 中文与中文之间的空格；保留英文/数字周围的空格
    s = re.sub(r"(?<=" + CJK + r")[ \t]+(?=" + CJK + r")", "", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def ensure_end(s):
    if not s:
        return s
    if s[-1] in SENT_END or s.endswith("……"):
        return s
    return s + "。"


def split_long(s, limit=90):
    """超长无句末标点的句子，优先在逗号处拆成多句。"""
    if len(s) <= limit or s[-1] in SENT_END:
        return [s]
    parts, cur = [], ""
    for seg in re.split(r"(?<=[，；：])", s):
        if len(cur) + len(seg) > limit and cur:
            parts.append(cur)
            cur = seg
        else:
            cur += seg
    if cur:
        parts.append(cur)
    out = []
    for p in parts:
        p = ensure_end(p.rstrip("，；："))
        if p:
            out.append(p)
    return out or [s]


def polish_sentence(text):
    s = fold_stutter(text)
    s = normalize_punct(s)
    s = strip_spaces(s)
    s = ensure_end(s)
    return s


def polish_lines(lines):
    """输入 [时间戳, 文本]，输出修正后的 [(时间戳, 文本)]"""
    out = []
    for ts, text in lines:
        pieces = split_long(polish_sentence(text))
        if not pieces:
            continue
        # 拆分出的第一句沿用原时间戳；后续句子没有独立时间，用空时间戳占位
        out.append((ts, pieces[0]))
        for p in pieces[1:]:
            out.append(("", p))
    return out


def parse_raw(path):
    rows = []
    pat = re.compile(r"^\[([0-9:]+)\]\s?(.*)$")
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = pat.match(line.rstrip("\n"))
            if m:
                rows.append((m.group(1), m.group(2)))
            elif line.strip():
                rows.append(("", line.strip()))
    return rows


def polish_file(raw_txt, light_txt=None):
    """读 .raw.txt，写 .light.txt，返回输出路径。"""
    out = light_txt or raw_txt.replace(".raw.txt", ".light.txt")
    rows = parse_raw(raw_txt)
    fixed = polish_lines(rows)
    changed = sum(1 for (_, s1), (_, s2) in zip(rows, fixed) if s1 != s2)
    with open(out, "w", encoding="utf-8") as f:
        for ts, text in fixed:
            f.write(("[%s] " % ts if ts else "") + text + "\n")
    print("  [修正] %d 句 → %d 句（改动 %d 句）" % (len(rows), len(fixed), changed))
    return out


def main():
    ap = argparse.ArgumentParser(description="原始转写 → 初步修正文本")
    ap.add_argument("raw_txt")
    ap.add_argument("light_txt", nargs="?")
    a = ap.parse_args()
    print("→", polish_file(a.raw_txt, a.light_txt))


if __name__ == "__main__":
    sys.exit(main())
