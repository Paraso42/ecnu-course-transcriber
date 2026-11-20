#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""course-transcriber 流水线公共配置与工具。

设计约束（重要）：
  * ASR 引擎/模型**不在本仓库**，由 config.json 的 `asr_home` 指向外部安装（第三方开源项目）。
  * 所有中间产物写在输出目录的 _work\\ 下，最终只留音频 + 三份文本。
"""
import os
import shutil
import subprocess
import sys

import settings

# 输出全部是中文；英文版 Windows 的控制台代码页（cp1252/cp437）会直接抛
# UnicodeEncodeError 把命令打断。这里统一把标准输出改成 UTF-8 + 替换非法字符，
# 与终端实际显示无关——文件内容始终是 UTF-8。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------- 外部依赖路径
ASR_HOME = settings.asr_home()                       # 空字符串 = 尚未配置
SHERPA = settings.asr_path("asr_bin")
TOKENS = settings.asr_path("asr_tokens")
MODEL = settings.asr_path("asr_model")
ASR_LANG = settings.get("asr_language") or "zh"
PLAYWRIGHT_CORE = settings.playwright_core()          # 空 = 用仓库内 npm 安装的那份
CDP_PORT = settings.cdp_port()

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                     # 仓库根目录
PROBES = os.path.join(ROOT, "probes")
GEN = os.path.join(HERE, "_gen")                 # 动态生成的探针脚本
CAPTURES = os.path.join(ROOT, "captures")
CDP = os.path.join(ROOT, "cdp_probe.js")
FETCH = os.path.join(ROOT, "fetch_media.py")
PROFILE = settings.profile_dir()
OUT_DIR = os.path.join(ROOT, settings.get("outputs_dir") or "outputs")
CW_DIR = os.path.join(ROOT, settings.get("courseware_dir") or "courseware")

CHUNK = 30          # SenseVoice 单次输入上限约 30 秒
BATCH = 12          # 每批喂给引擎的块数
CONN = 8            # 下载并发连接数


def find_ffmpeg():
    """优先用 PATH，其次找 WinGet 安装位置。"""
    p = shutil.which("ffmpeg")
    if p:
        return p
    import glob
    for pat in (
        r"C:\Users\*\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ):
        hit = glob.glob(pat)
        if hit:
            return hit[0]
    raise RuntimeError("找不到 ffmpeg，请安装或把 ffmpeg.exe 加入 PATH")


def _probe_ffmpeg():
    """找不到 ffmpeg 不该在 import 阶段就炸：自检要能把它当成"缺依赖"报出来。"""
    try:
        return find_ffmpeg()
    except RuntimeError:
        return None


FFMPEG = _probe_ffmpeg()


def require_ffmpeg():
    """真正要用 ffmpeg 的地方先调它，缺了就给出可操作的安装提示。"""
    if not FFMPEG:
        print("[错误] 找不到 ffmpeg。安装后重试：\n"
              "    Windows : winget install Gyan.FFmpeg（或把 ffmpeg.exe 加入 PATH）\n"
              "    macOS   : brew install ffmpeg\n"
              "    Debian  : sudo apt install ffmpeg", file=sys.stderr)
        sys.exit(2)
    return FFMPEG


def run(cmd, timeout=None):
    """统一跑外部命令；把 config 里的路径以环境变量传给 node 脚本。"""
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=settings.node_env())


def ensure_dirs(*paths):
    for p in paths:
        os.makedirs(p, exist_ok=True)


def fmt_ts(sec):
    """秒 → HH:MM:SS"""
    sec = max(0, int(round(sec)))
    return "%02d:%02d:%02d" % (sec // 3600, sec % 3600 // 60, sec % 60)


def asr_scratch(seed, name):
    """给 sherpa 用的临时目录：**必须纯 ASCII**（引擎读不了中文路径）。

    优先放在 ASR_HOME\\temp\\cr（与第三方引擎同盘，避免跨盘拷贝）；
    未配置 ASR_HOME 时退到系统临时目录。
    """
    import re
    import tempfile
    import zlib
    tag = name if re.fullmatch(r"[A-Za-z0-9._-]+", name or "") else "seg"
    h = zlib.crc32((seed or "").encode("utf-8")) & 0xFFFFFFFF
    base = os.path.join(ASR_HOME, "temp", "cr") if ASR_HOME else \
        os.path.join(tempfile.gettempdir(), "course-transcriber", "cr")
    return os.path.join(base, "%s_%08x" % (tag, h))


def probe_env():
    """探查外部依赖是否就绪，返回 [(名称, 是否存在, 路径)]"""
    return [
        ("ASR 引擎", os.path.exists(SHERPA), SHERPA or "未配置 asr_home"),
        ("SenseVoice 模型", os.path.exists(MODEL), MODEL or "未配置 asr_model"),
        ("词表 tokens.txt", os.path.exists(TOKENS), TOKENS or "未配置 asr_tokens"),
        ("ffmpeg", bool(FFMPEG), FFMPEG or "未安装（见上方安装提示）"),
        ("CDP 探针脚本", os.path.exists(CDP), CDP),
        ("下载脚本", os.path.exists(FETCH), FETCH),
        ("登录态目录", True, PROFILE),
    ]


ASR_ITEMS = ("ASR 引擎", "SenseVoice 模型", "词表 tokens.txt")


def require_env(need_asr=True, need_ffmpeg=True):
    """依赖闸门。

    need_asr / need_ffmpeg 只在"要转写"时才是必需的：
    只要 PPT 截图或平台官方记录时（--no-transcribe），没装 ASR、没有 ffmpeg 也应放行。
    """
    items = probe_env()
    bad = []
    for name, ok, _ in items:
        if ok:
            continue
        if name in ASR_ITEMS and not need_asr:
            continue
        if name == "ffmpeg" and not need_ffmpeg:
            continue
        bad.append(name)
    if bad:
        print("[错误] 缺少依赖：" + "、".join(bad), file=sys.stderr)
        for n, ok, p in items:
            print("   %s %s %s" % ("OK  " if ok else "缺失", n, p), file=sys.stderr)
        if any(n in ASR_ITEMS for n in bad):
            print("   提示：ASR 是第三方项目，安装见 docs/ASR.md；"
                  "只想取 PPT/官方记录可加 --no-transcribe。", file=sys.stderr)
        sys.exit(2)
