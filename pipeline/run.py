#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""course-transcriber 主流水线：课程网页 → 音频 + 原始转写 + 初步修正文本。

用法：
  python pipeline\\run.py plan    --course "课程名"     # 开场盘点：哪些日期还没取完（JSON）
  python pipeline\\run.py all     --url "<课程网页链接>"    # 或 --course "课程名"（只知课名时）
  python pipeline\\run.py resolve --url "<链接>" [--save sessions.json]
  python pipeline\\run.py process --sessions sessions.json [--date 2026-10-12] [--limit 3]
  python pipeline\\run.py prune   [--apply]        # 清理被更晚运行完全覆盖的旧运行（默认只演练）
  python pipeline\\run.py overview [--term 2026-2027]   # 按「课程 → 日期」看识别进度

输出（一次运行一个文件夹；结束时打印「交付路径」纯文本，可直接复制）：
  outputs\\<课程名>_<teclId>_<运行日期>\\
      2026-10-12\\audio\\1012-1.m4a              （wav 仅识别时临时存在，跑完即删）
                1012-1.raw.txt 1012-1.raw.json 1012-1.light.txt
      official\\（平台官方字幕/总结）  courseware\\（平台课件切片，可选）
      manifest.json  README.md  _work\\（中间产物，可删）
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time

import common as C
import settings
import asr_file
import official_sub
import polish
import courseware
import session_resolve


def safe_name(s):
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]", "_", (s or "").strip())
    return s[:60] or "course"


def download(url, mp4):
    if os.path.exists(mp4) and os.path.getsize(mp4) > 10 * 1024 * 1024:
        print("  [跳过] 视频已存在 %.0f MB" % (os.path.getsize(mp4) / 1048576))
        return True
    print("  [下载] 8 连接并发 …")
    r = C.run([sys.executable, C.FETCH, url, mp4, "--conn", str(C.CONN)])
    ok = os.path.exists(mp4) and os.path.getsize(mp4) > 10 * 1024 * 1024
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()
    print("   ", tail[-1] if tail else "(无输出)")
    return ok


def make_audio(src, m4a, wav_tmp=None):
    """产出：m4a（给人听，体积小）；wav 只作识别用的临时文件（16 kHz 单声道）。

    依据：音频的唯一用途是"用户挑重点亲自听" + 喂给识别引擎。
    原始视频音轨本身就是 16 kHz 单声道 AAC，转 64k m4a 听感无损，不必留 100 MB 的 wav。
    wav_tmp 传 None 表示只要音频、不转写（--audio-only）。
    """
    C.require_ffmpeg()
    if not (os.path.exists(m4a) and os.path.getsize(m4a) > 512 * 1024):
        print("  [音频] 转 m4a（16 kHz 单声道 64k，供试听）…")
        C.run([C.FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", src, "-vn",
               "-ac", "1", "-ar", "16000", "-c:a", "aac", "-b:a", "64k", m4a])
    if wav_tmp and not (os.path.exists(wav_tmp) and os.path.getsize(wav_tmp) > 1024 * 1024):
        print("  [音频] 抽 16 kHz 单声道 wav（识别用临时文件）…")
        C.ensure_dirs(os.path.dirname(wav_tmp))
        C.run([C.FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", src, "-vn",
               "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav_tmp])
    return os.path.exists(m4a), (not wav_tmp) or os.path.exists(wav_tmp)


def process(info, outroot, only_date=None, limit=None, keep_video=False, keep_wav=False,
            audio_only=False, only_dates=None, official_since=None, official_docx=False,
            transcribe=True, only_segs=None):
    C.require_env(need_asr=transcribe, need_ffmpeg=transcribe)
    course = info["course"]
    sessions = info["sessions"]
    dates = only_dates or ([only_date] if only_date else None)
    if dates:
        sessions = [s for s in sessions if s["date"] in dates]
    if only_segs:
        sessions = [s for s in sessions if (s.get("segName") or "") in only_segs]
    if limit:
        sessions = sessions[:limit]
    if not sessions:
        print("[错误] 没有匹配的节次")
        return None

    run_name = "%s_%s_%s" % (safe_name(course.get("subjName")), course.get("teclId"),
                             time.strftime("%Y-%m-%d"))
    run_root = os.path.join(outroot, run_name)
    work_root = os.path.join(run_root, "_work")
    C.ensure_dirs(run_root, work_root)

    # Word 依赖官方字幕：只给了 --official-docx 时自动补上 --official-since（取所选日期里最早的一天），
    # 避免"选了 Word 却什么都没生成"这种静默失效。
    if official_docx and not official_since:
        ds = sorted({(s["date"] or "") for s in sessions if s.get("date")})
        if ds:
            official_since = ds[0]
            print("[官方字幕] 选的是 Word 版，自动包含官方字幕+总结（%s 起）" % official_since)

    # 先把「平台官方语音识别记录」扒下来（只对 --official-since 之后的节次；已扒过的复用）
    if official_since:
        targets = [s for s in sessions if (s["date"] or "") >= official_since]
        if targets:
            print("[官方字幕] 平台自动转写记录：%d 段待查（%s 起）" % (len(targets), official_since))
            try:
                official_sub.fetch_and_write(targets, run_root, course, info.get("sourceUrl"),
                                             docs=official_docx)
            except Exception as e:
                print("  [警告] 官方字幕获取失败（不影响本地转写）：%s" % e)

    entries = []
    if not transcribe:
        print("[转写] 本次跳过（只取附加资源：PPT 课件 / 官方记录）")
    for s in sessions:
        seg = s.get("segName") or "%s-%s" % (
            (s.get("date") or "").replace("-", "")[4:] or "seg", s.get("index") or 1)
        date_dir = os.path.join(run_root, s["date"] or "unknown")
        audio_dir = os.path.join(date_dir, "audio")
        C.ensure_dirs(audio_dir)
        m4a = os.path.join(audio_dir, seg + ".m4a")
        wav_tmp = os.path.join(work_root, seg + ".wav")      # 识别用临时文件，用完即删
        wav_keep = os.path.join(audio_dir, seg + ".wav")
        raw_txt = os.path.join(date_dir, seg + ".raw.txt")
        print("=== %s  %s  (%s) ===" % (seg, s.get("begin") or "?", s["courseId"]))

        err = None
        local = s.get("localWav")
        if not transcribe:
            done = True                       # 不下载、不识别：只走到 entries（官方/课件在别处取）
        else:
            if not s.get("url") and not (local and os.path.exists(local)):
                err = "平台未给直链（可能未转码完成）"
            if audio_only:
                done = os.path.exists(m4a)
            else:
                done = os.path.exists(raw_txt) and (os.path.exists(m4a) or
                                                    (keep_wav and os.path.exists(wav_keep)))
        if err is None and done:
            if transcribe:
                print("  已完成，跳过（如需重做请删对应文件）")
        else:
            mp4 = os.path.join(work_root, seg + ".mp4")
            if err is None and local and os.path.exists(local):
                # 已有本地音频：直接用它当输入（跳过下载）
                print("  [输入] 使用本地音频 %s" % local)
                src = local
            elif err is None:
                src = None
                if not download(s["url"], mp4):
                    err = "下载失败"
                else:
                    src = mp4
            if err is None:
                ok_m4a, ok_wav = make_audio(src, m4a, None if audio_only else wav_tmp)
                if not (ok_m4a and ok_wav):
                    err = "音频转换失败"
            if err is None and not audio_only:
                try:
                    t, j = asr_file.transcribe(wav_tmp, date_dir, seg,
                                               extra_meta={"courseId": s["courseId"],
                                                           "courBeginTime": s.get("begin"),
                                                           "sourceUrl": info.get("sourceUrl")})
                    polish.polish_file(t)
                except Exception as e:
                    err = "转写失败：%s" % e
            # 收尾：mp4 与识别用 wav 都是中间产物，默认不留（音频只留 m4a 供人听）
            if keep_wav and os.path.exists(wav_tmp):
                try:
                    if os.path.exists(wav_keep):
                        os.remove(wav_keep)
                    shutil.move(wav_tmp, wav_keep)
                except OSError:
                    pass
            for f in (mp4, wav_tmp):
                if os.path.exists(f) and not (f == mp4 and keep_video) and not (f == wav_tmp and keep_wav):
                    try:
                        os.remove(f)
                    except OSError:
                        pass

        off_txt = os.path.join(run_root, "official", s["date"], seg + ".official.txt")
        off_json = os.path.join(run_root, "official", s["date"], seg + ".official.json")
        off_docx = os.path.join(run_root, "official", "word",
                                "%s_%s_官方字幕与总结.docx" % (seg, s["date"]))
        off_meta = official_sub.load_meta(run_root, s["date"], seg)
        entries.append({
            "segName": seg, "date": s["date"], "begin": s.get("begin"),
            "courseId": s["courseId"], "vodId": s.get("vodId"),
            "duration_sec": s.get("duration"), "streams": s.get("streamCount"),
            "official": ({"count": off_meta.get("count"), "chars": off_meta.get("chars"),
                          "duration_sec": off_meta.get("duration_sec"),
                          "source": off_meta.get("source")} if off_meta else None),
            "files": {
                "audio_wav": os.path.relpath(wav_keep, run_root)
                              if (keep_wav and os.path.exists(wav_keep)) else None,
                "audio_m4a": os.path.relpath(m4a, run_root) if os.path.exists(m4a) else None,
                "raw_txt": os.path.relpath(raw_txt, run_root) if os.path.exists(raw_txt) else None,
                "raw_json": os.path.relpath(raw_txt.replace(".raw.txt", ".raw.json"), run_root)
                            if os.path.exists(raw_txt.replace(".raw.txt", ".raw.json")) else None,
                "light_txt": os.path.relpath(raw_txt.replace(".raw.txt", ".light.txt"), run_root)
                             if os.path.exists(raw_txt.replace(".raw.txt", ".light.txt")) else None,
                "official_txt": os.path.relpath(off_txt, run_root) if off_meta else None,
                "official_json": os.path.relpath(off_json, run_root) if off_meta else None,
                "official_docx": os.path.relpath(off_docx, run_root) if os.path.exists(off_docx) else None,
            },
            "error": err,
        })
        if err:
            print("  [错误]", err)

    manifest = {"course": course, "sourceUrl": info.get("sourceUrl"),
                "resolvedAt": info.get("resolvedAt"),
                "generatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
                "asr": {"engine": "sherpa-onnx + SenseVoice-Small int8",
                        "chunk_sec": C.CHUNK, "language": "zh", "itn": True},
                "audio": {"output": "m4a 16 kHz mono aac 64k（供人工试听）",
                          "note": "wav 仅在识别过程中临时存在，默认不保留（--keep-wav 可留）"},
                "official_index": ("official/official_subtitles.json"
                                   if os.path.exists(os.path.join(run_root, "official",
                                                                  "official_subtitles.json")) else None),
                "sessions": entries}
    with open(os.path.join(run_root, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    write_readme(run_root, manifest)
    return run_root, entries


def write_readme(run_root, m):
    c = m["course"]
    ok = [e for e in m["sessions"] if not e["error"]]
    bad = [e for e in m["sessions"] if e["error"]]
    off = [e for e in m["sessions"] if e.get("official")]
    lines = [
        "# %s — 语音提取与转写产出" % c.get("subjName"),
        "",
        "- 课程：%s（%s） 教师：%s" % (c.get("subjName"), c.get("subjCode"), c.get("teacNames")),
        "- 来源页面：%s" % (m.get("sourceUrl") or "-"),
        "- 生成时间：%s" % m.get("generatedAt"),
        "- 识别模型：%s（离线）" % m["asr"]["engine"],
        "- 成功 %d 段 / 失败 %d 段；其中 %d 段另有平台官方识别记录" % (len(ok), len(bad), len(off)),
        "",
        "## 目录结构与文件说明",
        "",
        "```",
        "outputs\\<本次运行>\\",
        "  <日期>\\",
        "    audio\\<段名>.m4a      # 16 kHz 单声道 64k：挑重点亲自听就用这个（≈23 MB / 55 分钟）",
        "    <段名>.raw.txt        # ① 原始转写：每句一行，行首 [HH:MM:SS]",
        "    <段名>.raw.json       # ① 的结构化版（含每句起止秒，便于程序对齐）",
        "    <段名>.light.txt      # ② 初步修正：标点/断句/口误重复，时间戳不变",
        "  official\\<日期>\\",
        "    <段名>.official.txt   # ③ 平台官方语音识别记录（逐条，`[HH:MM:SS] 原文`）",
        "    <段名>.official.json  # ③ 的结构化版（平台原始 bg/ed 毫秒）",
        "    <段名>.summary.json   # ④ 平台官方 AI 总结（原始返回）",
        "    <段名>.summary.txt    # ④ 的可读版（原文逐字）",
        "  official\\word\\<段名>_<日期>_官方字幕与总结.docx   # ⑤ 每段一份：前面字幕、后面总结",
        "  official\\official_subtitles.json   # 官方记录的覆盖情况（哪些段有、哪些没有）",
        "  manifest.json          # 全部文件清单与元数据",
        "  README.md              # 本说明",
        "  _work\\                 # 下载的 mp4 与识别用 wav 的临时存放处（用完自动删），可整目录删除",
        "```",
        "",
        "同一门课**同一天的所有节次**放在同一个日期文件夹下，**互不拼接**；"
        "平台官方记录单独放在 `official\\` 下，不与本地转写混放。",
        "",
        "## 三份文本的差别（重要）",
        "",
        "| 文件 | 内容 | 用途 |",
        "|---|---|---|",
        "| `*.raw.txt` | 引擎原始输出，只做了分句与时间戳 | 溯源、复核、给后续流程做输入 |",
        "| `*.light.txt` | 原始 + 浅层校准：口误重复折叠（这个这个→这个）、标点规范、碎片句并入、超长句拆分 | 阅读与后续加工 |",
        "| `*.official.txt` | 平台自己自动转写的字幕记录，**逐条原样**（未合并、未纠错），时间戳取自平台的字幕起止时间 | 与本地转写互相印证；平台没有的节次就是没有 |",
        "",
        "**本流程不做**专业术语校正（如 干系胞→干细胞、引窝→隐窝、sonny 黑潮→Sonic hedgehog）："
        "这些需要结合课件与上下文，留到对应课程工作区里做。",
        "",
        "## 节次清单",
        "",
        "| 段名 | 日期 | 开始 | 时长 | 状态 | 官方字幕 |",
        "|---|---|---|---|---|---|",
    ]
    for e in m["sessions"]:
        dur = e.get("duration_sec")
        o = e.get("official")
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            e["segName"], e["date"], (e.get("begin") or "")[11:] or "-",
            ("%d 分 %d 秒" % (dur // 60, dur % 60)) if dur else "-",
            "❌ " + e["error"] if e["error"] else "✅",
            ("%d 条 / %d 字" % (o.get("count") or 0, o.get("chars") or 0)) if o else "—（平台没有）"))
    lines += ["", "## 时间戳格式", "",
              "`[HH:MM:SS]` 为该句在**本段音频**中的起始位置（段与段各自从 0 开始计），"
              "可直接把音频拖进播放器跳到该时间点核对。", ""]

    idx_path = os.path.join(run_root, "official", "official_subtitles.json")
    if os.path.exists(idx_path):
        try:
            with open(idx_path, encoding="utf-8") as f:
                idx = json.load(f)
        except Exception:
            idx = {}
        rows = idx.get("sessions") or []
        have = [x for x in rows if x.get("has_official")]
        lines += ["## 平台官方语音识别记录（整门课）", "",
                  "平台自己做了转写与课后总结的节次：**%d / %d 段**。"
                  "内容按平台原文逐字保存，一个字未改；`official\\word\\` 下每段一份 Word（前面字幕、后面总结）。" %
                  (len(have), len(rows)), "",
                  "| 段名 | 日期 | 官方字幕 | 官方总结 | Word |",
                  "|---|---|---|---|---|"]
        for x in rows:
            sm = x.get("summary") or {}
            lines.append("| %s | %s | %s | %s | %s |" % (
                x.get("segName"), x.get("date"),
                ("%d 条" % x["count"]) if x.get("has_official") else "—（平台没有）",
                ("要点 %d · 分段 %d" % (sm.get("keyPoints") or 0, sm.get("skims") or 0)) if sm else "-",
                "✅" if (x.get("files") or {}).get("docx") else "-"))
        lines += ["", "（平台没有的节次就是没有：转写任务可能还没跑，过几天再扒一次即可。）", ""]
    with open(os.path.join(run_root, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def handle_blocker(info):
    """处理 _need_login / _need_choice，返回 True 表示应中止。"""
    if info.get("_need_login"):
        print("\n[需要登录] 已打开 Edge，但登录态失效。")
        print("  请在弹出的窗口里完成 CAS 登录（账号密码只由你输入），登录后重跑同一条命令即可。")
        return True
    if info.get("_need_choice"):
        print("\n[需要选择] 无法从链接判断是哪门课，可选：")
        for c in info["courses"]:
            print("  teclId=%s  %s  %s  教师：%s" % (c.get("teclId"), c.get("subjName"),
                                                c.get("subjCode"), c.get("teacNames")))
        print("\n请带 --tecl-id <数字> 重跑。")
        return True
    return False


# ------------------------------------------------------------------ prune（清理）
REGEN_META = {"manifest.json", "README.md"}   # 每次运行必然不同，不参与字节比对
RUN_NAME = re.compile(r"^(.+)_(\d+)_(\d{4}-\d{2}-\d{2})$")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def _run_files(run_dir):
    """{相对路径: 字节数}，跳过 manifest/README 这类每次运行都会重写的元数据。"""
    out = {}
    for dp, _, names in os.walk(run_dir):
        for n in names:
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, run_dir)
            if rel.replace("\\", "/") in REGEN_META:
                continue
            out[rel] = os.path.getsize(p)
    return out


def _dir_bytes(path):
    return sum(os.path.getsize(os.path.join(dp, n))
               for dp, _, names in os.walk(path) for n in names)


def _rmtree_guarded(outroot, path):
    """只允许删 outroot 的直接子目录，防止路径拼错删到别处。"""
    root = os.path.abspath(outroot)
    target = os.path.abspath(path)
    if os.path.dirname(target) != root or not RUN_NAME.match(os.path.basename(target)):
        raise RuntimeError("拒绝删除：%s 不是 %s 下的运行文件夹" % (target, root))
    shutil.rmtree(target)


def prune_runs(outroot, apply=False):
    """删除「已被更晚运行完全覆盖」的旧运行文件夹。

    判定标准（全部满足才删）：
      1. 同一门课（课程名 + teclId 相同），按运行日期**从新到旧**处理——最新的先留下；
      2. 该运行里的**每一个**产出文件，都能在某个「已判定保留」的运行里
         找到相同相对路径、相同大小、相同 SHA-256 的副本；
      3. manifest.json / README.md 不参与比对（每次运行必然重写）。
    默认只演练打印；加 --apply 才真删。
    """
    if not os.path.isdir(outroot):
        print("[信息] 输出目录还不存在，没有可清理的运行：%s" % outroot)
        return 0
    names = sorted(os.listdir(outroot))
    groups = {}
    for name in names:
        path = os.path.join(outroot, name)
        m = RUN_NAME.match(name)
        if os.path.isdir(path) and m:
            groups.setdefault((m.group(1), m.group(2)), []).append((m.group(3), name, path))
    if not groups:
        print("没有找到形如 <课程名>_<teclId>_<日期> 的运行文件夹")
        return 0

    hcache = {}

    def sha(p):
        if p not in hcache:
            hcache[p] = _sha256(p)
        return hcache[p]

    total = 0
    n_del = 0
    for (cname, tecl), runs in sorted(groups.items()):
        runs.sort(key=lambda r: r[0], reverse=True)   # 由新到旧：最新的一次先留
        kept = []                                     # [(path, files, name)] 已判定保留
        print("\n== %s（teclId=%s，%d 次运行）==" % (cname, tecl, len(runs)))
        for pos, (date, name, path) in enumerate(runs):
            files = _run_files(path)
            if not files:
                print("  [保留] %-42s 空运行，没有可比对的产出文件" % name)
                kept.append((path, files, name))
                continue
            covered_by, missing = set(), None
            for rel, size in files.items():
                hit = None
                for kpath, kfiles, kname in kept:
                    if kfiles.get(rel) == size and sha(os.path.join(kpath, rel)) == sha(os.path.join(path, rel)):
                        hit = kname
                        break
                if not hit:
                    missing = rel
                    break
                covered_by.add(hit)
            if missing is None:
                nbytes = _dir_bytes(path)
                total += nbytes
                n_del += 1
                print("  [可删] %-42s %7.1f MB  逐文件哈希已被 %s 覆盖"
                      % (name, nbytes / 1048576, "、".join(sorted(covered_by))))
                if apply:
                    _rmtree_guarded(outroot, path)
                    print("        ↳ 已删除")
            else:
                kept.append((path, files, name))
                if pos == 0:
                    print("  [保留] %-42s 最新一次运行（比对基线）" % name)
                else:
                    print("  [保留] %-42s 含更晚运行里没有的内容（如 %s）" % (name, missing))

    print("\n合计：%d 个运行文件夹%s，%s %.1f MB"
          % (n_del, "可删" if not apply else "已删", "可回收" if not apply else "已释放",
             total / 1048576))
    if n_del and not apply:
        print("（这是演练，未动任何文件；确认无误后加 --apply 执行）")
    return 0


# ------------------------------------------------------------------ overview（总览）
DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SEG_TXT = re.compile(r"^(\d{4}-\d+)\.raw\.txt$")


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _seg_pairs(run_dir, manifest):
    """[(date, seg)]：优先用 manifest，缺失或为空时退回扫日期目录。"""
    pairs = []
    for s in ((manifest or {}).get("sessions") or []):
        if s.get("date") and s.get("segName"):
            pairs.append((s["date"], s["segName"]))
    if pairs:
        return pairs
    for date in sorted(os.listdir(run_dir)):
        d = os.path.join(run_dir, date)
        if not (os.path.isdir(d) and DATE_DIR.match(date)):
            continue
        for n in sorted(os.listdir(d)):
            m = SEG_TXT.match(n)
            if m:
                pairs.append((date, m.group(1)))
    return pairs


def _fmt_hours(sec):
    return "%.1f 小时" % (sec / 3600.0) if sec else "-"


def _teachers(v):
    """兼容两种历史形态：list（新）与 "甲/乙/丙" 字符串（早期试点 manifest）。"""
    if isinstance(v, (list, tuple)):
        v = [str(x) for x in v]
    elif isinstance(v, str):
        v = [x for x in re.split(r"[/、，,]", v) if x.strip()]
        v = [x.strip() for x in v]
    else:
        return ""
    if not v:
        return ""
    return "、".join(v) if len(v) <= 2 else "%s 等 %d 人" % (v[0], len(v))


def overview(outroot, term=None):
    """按「课程 → 日期」列出已有识别产出的进度，只到日期这一级。

    判定「有识别」= 该日期下存在至少一个 `*.raw.txt`（识别成功的唯一凭证）。
    同一门课多次运行会按 (课程, teclId) 合并去重，同一日期同一段只计一次。
    """
    if not os.path.isdir(outroot):
        print("[信息] 还没有任何产出：%s" % outroot)
        print("       跑一次 `run.py all --course \"课名\"` 后，这里就会出现运行文件夹。")
        return 0
    groups = {}
    for name in sorted(os.listdir(outroot)):
        path = os.path.join(outroot, name)
        m = RUN_NAME.match(name)
        if not (os.path.isdir(path) and m):
            continue
        man = _load_json(os.path.join(path, "manifest.json"))
        course = (man or {}).get("course") or {}
        tecl = str(course.get("teclId") or m.group(2))
        g = groups.setdefault(tecl, {"meta": {}, "dates": {}, "runs": []})
        g["runs"].append((m.group(3), course))      # 记下每次运行的课名信息，最后按新→旧取值
        durations = {}
        for s in ((man or {}).get("sessions") or []):
            if s.get("segName"):
                durations[(s.get("date"), s["segName"])] = s.get("duration_sec")
        for date, seg in _seg_pairs(path, man):
            raw = os.path.join(path, date, seg + ".raw.txt")
            if not os.path.exists(raw):
                continue                        # 没识别成功的不算
            dates = g["dates"].setdefault(date, {})
            if seg in dates:
                continue
            dates[seg] = {
                "dur": durations.get((date, seg)),
                "m4a": os.path.exists(os.path.join(path, date, "audio", seg + ".m4a")),
                "light": os.path.exists(os.path.join(path, date, seg + ".light.txt")),
            }

    for g in groups.values():
        for date, course in sorted(g["runs"], reverse=True):   # 新 → 旧：只补缺的字段
            for k in ("subjName", "subjCode", "teacNames", "term", "courTimes"):
                if course.get(k) and k not in g["meta"]:
                    g["meta"][k] = course[k]

    print("识别进度总览（截至 %s）" % time.strftime("%Y-%m-%d %H:%M"))
    shown = segs_total = dates_total = 0
    for tecl, g in sorted(groups.items(),
                          key=lambda kv: (kv[1]["meta"].get("subjCode") or "", kv[0])):
        meta = g["meta"]
        if term and meta.get("term") and meta["term"] != term:
            continue
        dates = {d: v for d, v in g["dates"].items() if v}
        if not dates:
            continue                            # 只列有识别的课
        shown += 1
        segs = sum(len(v) for v in dates.values())
        segs_total += segs
        dates_total += len(dates)
        print("\n%s（%s · teclId=%s）" % (meta.get("subjName") or "?", meta.get("subjCode") or "-", tecl))
        sub = [x for x in (meta.get("term"), _teachers(meta.get("teacNames"))) if x]
        if sub:
            print("  " + " · ".join(sub))
        prog = ("%d/%s" % (segs, meta["courTimes"])) if meta.get("courTimes") else str(segs)
        print("  已识别 %s 段，覆盖 %d 个日期" % (prog, len(dates)))
        for date in sorted(dates):
            v = dates[date]
            dur = sum((x["dur"] or 0) for x in v.values())
            flags = []
            if any(not x["m4a"] for x in v.values()):
                flags.append("缺 m4a")
            if any(not x["light"] for x in v.values()):
                flags.append("缺 light")
            note = ("   ⚠ " + "、".join(flags)) if flags else ""
            print(("    %s   %2d 段   %s%s" % (date, len(v), _fmt_hours(dur), note)).rstrip())
    if not shown:
        print("\n（%s没有识别产出）" % (("学期 %s 下" % term) if term else "outputs 里"))
        return 0
    print("\n合计：%d 门课 / %d 段 / %d 个日期" % (shown, segs_total, dates_total))
    return 0


# ------------------------------------------------------------------ plan（开场盘点）
def plan_report(info, outroot):
    """盘点一门课「哪些日期还没取完」，输出 JSON，供开场提问直接用。

    判定：某日期下**所有**节次都有 `*.raw.txt` 才算取完（done）；
    部分有 = partial；一个都没有 = none。同时标出该日期是否已有
    官方记录（official/）与课件切片（courseware/），避免重复获取。
    """
    course = info.get("course") or {}
    tecl = str(course.get("teclId") or "")
    sessions = info.get("sessions") or []

    expect, seg2date = {}, {}
    for s in sessions:
        d, seg = s.get("date") or "", s.get("segName") or ""
        if d and seg:
            expect.setdefault(d, []).append(seg)
            seg2date[seg] = d
    for d in expect:
        expect[d].sort()

    roots = [outroot, os.path.join(C.ROOT, "courseware")]   # 独立抓的课件也在这棵树下
    runs, got, cw_dates = [], {}, set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            m = RUN_NAME.match(name)
            if not (os.path.isdir(path) and m and m.group(2) == tecl):
                continue
            runs.append(path)
            man = _load_json(os.path.join(path, "manifest.json"))
            for date, seg in _seg_pairs(path, man):
                rec = got.setdefault(date, {}).setdefault(
                    seg, {"raw": False, "m4a": False, "light": False, "official": False})
                rec["raw"] = rec["raw"] or os.path.exists(
                    os.path.join(path, date, seg + ".raw.txt"))
                rec["m4a"] = rec["m4a"] or os.path.exists(
                    os.path.join(path, date, "audio", seg + ".m4a"))
                rec["light"] = rec["light"] or os.path.exists(
                    os.path.join(path, date, seg + ".light.txt"))
                rec["official"] = rec["official"] or os.path.exists(
                    os.path.join(path, "official", date, seg + ".official.txt"))
            cw = os.path.join(path, "courseware")
            cw_roots = [cw]
            if os.path.abspath(root) == os.path.abspath(os.path.join(C.ROOT, "courseware")):
                cw_roots.append(path)      # 独立抓课件时，运行目录本身就是课件根
            for cw_root in cw_roots:
                if not os.path.isdir(cw_root):
                    continue
                ledger = _load_json(os.path.join(cw_root, "_课件清单.json"))
                for lec in ((ledger or {}).get("lectures") or []):
                    if lec.get("date"):
                        cw_dates.add(lec["date"])
                for dp, dirs, _ in os.walk(cw_root):
                    for d in dirs:
                        if d in seg2date:          # 目录名就是段名（如 0915-1）
                            cw_dates.add(seg2date[d])

    rows = []
    for d in sorted(expect):
        segs = expect[d]
        have = got.get(d, {})
        done = [s for s in segs if have.get(s, {}).get("raw")]
        status = "done" if len(done) == len(segs) else ("partial" if done else "none")
        rows.append({
            "date": d,
            "segs": len(segs),
            "done": len(done),
            "status": status,
            "missing": [s for s in segs if s not in done],
            "official": any(have.get(s, {}).get("official") for s in segs),
            "courseware": d in cw_dates,
        })

    runs = sorted(runs)
    out = {
        "course": {
            "subjName": course.get("subjName"),
            "subjCode": course.get("subjCode"),
            "teclId": course.get("teclId"),
            "term": course.get("term"),
            "teachers": _teachers(course.get("teacNames")),
            "courTimes": course.get("courTimes"),
        },
        "totalSegs": len(sessions),
        "runDirs": [os.path.abspath(p) for p in runs],
        "latestRun": os.path.abspath(runs[-1]) if runs else None,
        "dates": rows,
        "doneDates": [r["date"] for r in rows if r["status"] == "done"],
        "pendingDates": [r["date"] for r in rows if r["status"] != "done"],
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def print_delivery(run_root):
    """交付路径：打成一段可直接复制、粘给其他智能体的纯文本地址。"""
    root = os.path.abspath(run_root)
    print("\n=== 交付路径（可直接复制） ===")
    print(root)
    subs = [d for d in ("official", "courseware") if os.path.isdir(os.path.join(root, d))]
    if subs:
        print("")
        for d in subs:
            print("  %s" % os.path.join(root, d))


def norm_sessions(info):
    """兼容两种会话文件：{"course":…,"sessions":[…]} 与裸数组 […]（探针产出的就是裸数组）。"""
    if isinstance(info, dict):
        return info.get("sessions") or []
    if isinstance(info, list):
        return info
    return []


def load_sessions(path):
    """读会话文件并统一成 {"course","sessions"}。

    历史遗留：pipeline\\_gen\\sessions_<teclId>.out.json 是**裸数组**（27 项，只有
    courseId/begin/end/vodStatus/transcriptTask），而 courseware / official_sub 期待
    {"course":…,"sessions":[…]}，直接喂会 AttributeError/TypeError。这里两种都收，
    并给裸数组补齐 date / index / segName（按同一天内 begin 排序编号）。
    """
    with open(path, encoding="utf-8") as f:
        info = json.load(f)
    if isinstance(info, dict) and info.get("sessions"):
        return info
    sessions = info if isinstance(info, list) else (info.get("sessions") or [])
    course = (info.get("course") if isinstance(info, dict) else None) or {}
    if not course.get("subjName"):
        names = [s.get("courName") for s in sessions if s.get("courName")]
        course["subjName"] = names[0] if names else "course"
    if not course.get("teclId"):
        course["teclId"] = "na"          # 裸数组里没有课号，避免目录名出现 None

    sessions = sorted(sessions, key=lambda s: (s.get("date") or (s.get("begin") or "")[:10],
                                               s.get("begin") or ""))
    per_date = {}
    for s in sessions:
        if not s.get("date"):
            s["date"] = (s.get("begin") or "")[:10]
        if not s.get("segName"):
            n = per_date.get(s["date"], 0) + 1
            per_date[s["date"]] = n
            s["index"] = s.get("index") or n
            s["segName"] = "%s-%d" % ((s["date"] or "").replace("-", "")[4:] or "seg", n)
    return {"course": course, "sessions": sessions,
            "sourceUrl": (info.get("sourceUrl") if isinstance(info, dict) else None),
            "resolvedAt": (info.get("resolvedAt") if isinstance(info, dict) else None)}


def parse_segs(text):
    """--segs 1102-3,1109-1 → {"1102-3","1109-1"}"""
    return {s.strip() for s in (text or "").split(",") if s.strip()}


def save_sessions(info, path=None):
    """把本次解析出的课+节次落成标准 sessions 文件，供 courseware / official_sub 直接复用。"""
    if not isinstance(info, dict):
        return None
    course = info.get("course") or {}
    name = "sessions_%s_%s.json" % (safe_name(course.get("subjName") or "course"),
                                   course.get("teclId"))
    path = path or os.path.join(C.ROOT, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"course": course, "sessions": info.get("sessions") or [],
                   "sourceUrl": info.get("sourceUrl"),
                   "resolvedAt": info.get("resolvedAt")}, f, ensure_ascii=False, indent=1)
    return path


def cmd_courseware(info, a, run_root=None):
    """抓平台「AI 课件」切片（PPT 截图 + 画面 OCR），按上课日归组成"讲次"。"""
    sessions = norm_sessions(info)
    dates = [d.strip() for d in (getattr(a, "dates", None) or "").split(",") if d.strip()]
    if not dates and getattr(a, "date", None):
        dates = [a.date]
    if dates:
        sessions = [s for s in sessions if s["date"] in dates]
    segs = parse_segs(getattr(a, "segs", None))
    if segs:
        sessions = [s for s in sessions if (s.get("segName") or "") in segs]
    if getattr(a, "limit", None):
        sessions = sessions[:a.limit]
    if not sessions:
        print("[错误] 没有匹配的节次")
        return 1, None

    if not courseware.ensure_login(headless=getattr(a, "headless", True)):
        print("[需要登录] 登录态失效。可先跑 `run.py login --qr` 生成二维码扫码登录，再重跑本命令；"
              "我不需要也不会使用你的密码", file=sys.stderr)
        return 4, None
    try:
        rep = courseware.grab(info["course"], sessions,
                              out_root=getattr(a, "outdir", None), run_root=run_root,
                              no_pdf=getattr(a, "no_pdf", False),
                              labels=courseware.parse_labels(getattr(a, "label", None)),
                              force=getattr(a, "force", False))
    except courseware.LoginRequired as e:
        print("[需要登录] %s" % e, file=sys.stderr)
        print("  登录态失效，不是“这讲没课件”。先跑 `python pipeline\\run.py login` 再重跑本命令。",
              file=sys.stderr)
        return 4, None
    except Exception as e:
        print("[课件] 失败：%s" % e, file=sys.stderr)
        return 1, None
    return 0, (rep or {}).get("root")


def run_process(info, a, outroot):
    """跑下载+转写；--courseware 时顺带把课件切片放进同一次运行目录。"""
    res = process(info, outroot, a.date, a.limit, a.keep_video, a.keep_wav,
                  getattr(a, "audio_only", False),
                  [d.strip() for d in (getattr(a, "dates", None) or "").split(",") if d.strip()],
                  getattr(a, "official_since", None), getattr(a, "official_docx", False),
                  transcribe=not getattr(a, "no_transcribe", False),
                  only_segs=parse_segs(getattr(a, "segs", None)))
    if not res:
        return None
    run_root, entries = res
    if getattr(a, "courseware", False):
        print("\n=== 课件切片 ===")
        code, _ = cmd_courseware(info, a, run_root=run_root)
        if code != 0:
            print("[课件] 未成功（code=%s），转写产出不受影响" % code)
    return res


def main():
    ap = argparse.ArgumentParser(description="课程网页 → 音频 + 转写文本")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a1 = sub.add_parser("all", help="解析链接/课程名并直接跑完整流程")
    a1.add_argument("--url", default=None, help="课程网页链接（与 --course 二选一）")
    a1.add_argument("--course", default=None, help="课程名，如「课程名」（与 --url 二选一）")
    a1.add_argument("--tecl-id", default=None, help="已知 teclId 时可直接指定")
    a1.add_argument("--login-wait", type=int, default=0,
                    help="未登录时自动等待的秒数（默认 0：立即返回，由用户手动登录后重跑）")
    a1.add_argument("--date", default=None, help="只处理某一天，如 2026-10-12")
    a1.add_argument("--dates", default=None,
                    help="只处理多天（逗号分隔），如 2026-09-14,2026-09-21,2026-09-28")
    a1.add_argument("--limit", type=int, default=None)
    a1.add_argument("--outdir", default=os.path.join(C.ROOT, "outputs"))
    a1.add_argument("--keep-video", action="store_true")
    a1.add_argument("--keep-wav", action="store_true", help="额外保留 16 kHz wav（默认只留 m4a）")
    a1.add_argument("--audio-only", action="store_true", help="只取音频（m4a），不做识别")
    a1.add_argument("--official-since", default=None,
                    help="同时扒平台官方语音识别记录（字幕+总结），只看该日期及之后的节次，如 2026-10-10")
    a1.add_argument("--official-docx", action="store_true",
                    help="把官方字幕+总结排成 Word（每段一份：前面字幕、后面总结）")
    a1.add_argument("--courseware", action="store_true",
                    help="同时抓平台「AI 课件」切片（PPT 截图），放进本次运行目录的 courseware\\")
    a1.add_argument("--headless", action="store_true",
                    help="用无头浏览器（不弹窗口），跑完自动关闭（all/process 默认就是无头）")
    a1.add_argument("--show-browser", action="store_true",
                    help="反过来：显示浏览器窗口（排障用；默认无头）")
    a1.add_argument("--segs", default=None,
                    help="只处理某些段（逗号分隔），如 1102-3,1109-1（补单段不用重跑整天）")
    a1.add_argument("--no-transcribe", action="store_true",
                    help="跳过下载与识别，只取附加资源（配合 --courseware / --official-since / --official-docx）")

    a2 = sub.add_parser("resolve", help="只解析出节次清单（不下载）")
    a2.add_argument("--url", default=None, help="课程网页链接（与 --course 二选一）")
    a2.add_argument("--course", default=None, help="课程名，如「课程名」（与 --url 二选一）")
    a2.add_argument("--tecl-id", default=None)
    a2.add_argument("--login-wait", type=int, default=0)
    a2.add_argument("--save", default=None)
    a2.add_argument("--headless", action="store_true",
                    help="用无头浏览器（不弹窗口），跑完自动关闭")

    a3 = sub.add_parser("process", help="按 sessions.json 执行下载+转写")
    a3.add_argument("--sessions", required=True)
    a3.add_argument("--date", default=None)
    a3.add_argument("--dates", default=None,
                    help="只处理多天（逗号分隔），如 2026-09-14,2026-09-21,2026-09-28")
    a3.add_argument("--limit", type=int, default=None)
    a3.add_argument("--outdir", default=os.path.join(C.ROOT, "outputs"))
    a3.add_argument("--keep-video", action="store_true")
    a3.add_argument("--keep-wav", action="store_true", help="额外保留 16 kHz wav（默认只留 m4a）")
    a3.add_argument("--audio-only", action="store_true", help="只取音频（m4a），不做识别")
    a3.add_argument("--official-since", default=None,
                    help="同时扒平台官方语音识别记录（字幕+总结），只看该日期及之后的节次")
    a3.add_argument("--official-docx", action="store_true",
                    help="把官方字幕+总结排成 Word（每段一份：前面字幕、后面总结）")
    a3.add_argument("--courseware", action="store_true",
                    help="同时抓平台「AI 课件」切片（PPT 截图），放进本次运行目录的 courseware\\")
    a3.add_argument("--segs", default=None,
                    help="只处理某些段（逗号分隔），如 1102-3,1109-1")
    a3.add_argument("--headless", action="store_true",
                    help="用无头浏览器（不弹窗口），跑完自动关闭（默认就是无头）")
    a3.add_argument("--show-browser", action="store_true", help="显示浏览器窗口（排障用）")
    a3.add_argument("--no-transcribe", action="store_true",
                    help="跳过下载与识别，只取附加资源（配合 --courseware / --official-since / --official-docx）")

    a6 = sub.add_parser("courseware", help="抓平台「AI 课件」切片（PPT 截图 + 画面 OCR）")
    a6.add_argument("--sessions", required=True)
    a6.add_argument("--date", default=None, help="只抓某一天，如 2026-09-15")
    a6.add_argument("--dates", default=None, help="只抓多天（逗号分隔）")
    a6.add_argument("--limit", type=int, default=None)
    a6.add_argument("--outdir", default=os.path.join(C.ROOT, "courseware"),
                    help="产出根目录（默认 <工作区>\\courseware）")
    a6.add_argument("--into", default=None,
                    help="写进已有运行目录（如 outputs\\<课程名>_<teclId>_<运行日期>）")
    a6.add_argument("--label", default=None,
                    help='讲次命名，如 "2026-09-15=第1讲_导论,2026-09-20=第2讲_神经科学基础"')
    a6.add_argument("--no-pdf", action="store_true", help="不合成 PDF（只留 jpg + 索引）")
    a6.add_argument("--force", action="store_true", help="已下载过的也重下")
    a6.add_argument("--show-browser", action="store_true", help="显示浏览器窗口（默认无头）")
    a6.add_argument("--headless", action="store_true",
                    help="用无头浏览器（不弹窗口），跑完自动关闭（默认就是无头）")

    sub.add_parser("check", help="只做环境自检（不联网）")

    a4 = sub.add_parser("prune", help="清理被更晚运行完全覆盖的旧运行文件夹（默认只演练）")
    a4.add_argument("--outdir", default=os.path.join(C.ROOT, "outputs"))
    a4.add_argument("--apply", action="store_true", help="真正删除；不加只打印计划")

    a5 = sub.add_parser("overview", help="按「课程 → 日期」列出已有识别的进度（只到日期级）")
    a5.add_argument("--outdir", default=os.path.join(C.ROOT, "outputs"))
    a5.add_argument("--term", default=None, help="只看某个学期，如 2026-2027")

    a7 = sub.add_parser("plan", help="开场盘点：这门课哪些日期还没取完（输出 JSON，供提问用）")
    a7.add_argument("--course", default=None, help="课程名，如「课程名」")
    a7.add_argument("--tecl-id", default=None)
    a7.add_argument("--sessions", default=None, help="直接给 sessions.json，跳过联网解析")
    a7.add_argument("--outdir", default=os.path.join(C.ROOT, "outputs"))
    a7.add_argument("--headless", action="store_true",
                    help="用无头浏览器（不弹窗口），跑完自动关闭")

    a8 = sub.add_parser("login", help="登录态：检查 / 无头生成扫码二维码")
    a8.add_argument("--check", action="store_true", help="只检查登录态（默认行为）")
    a8.add_argument("--qr", action="store_true", help="无头生成扫码二维码并等待扫码")
    a8.add_argument("--timeout", type=int, default=180, help="扫码等待秒数（默认 180）")
    a8.add_argument("--out", default=os.path.join(C.ROOT, "captures", "qr.png"),
                    help="二维码图片保存路径")
    a8.add_argument("--show", action="store_true",
                    help="显示浏览器窗口（默认无头；仅在你看得到桌面时才需要）")
    a8.add_argument("--headless", action="store_true",
                    help="（默认即无头，保留此参数与其它子命令保持一致）")

    a = ap.parse_args()

    # all / process / courseware 默认无头：AGENTS.md 的模板命令都不带 --headless，默认可见会突然弹窗、
    # 并把 SSO 标签页留在 profile 里（进而触发登录误判）。要看得见窗口请显式 --show-browser。
    if a.cmd in ("all", "process", "courseware"):
        a.headless = False if getattr(a, "show_browser", False) else True

    # 无头模式：无论是正常结束还是 sys.exit，都把后台浏览器关掉
    if getattr(a, "headless", False):
        import atexit
        atexit.register(session_resolve.close_browser)

    if a.cmd == "login":
        hl = not a.show
        if not a.qr:
            ok = session_resolve.check_login(headless=hl)
            print("[登录] %s" % ("有效" if ok else "已失效"))
            if ok or a.check:
                sys.exit(0 if ok else 4)
            a.qr = True                      # 失效 → 无条件走扫码
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        print("[登录] 生成二维码（无头，不弹窗口）…", flush=True)
        rep = session_resolve.qr_login(a.out, a.timeout, headless=hl)
        for line in (rep.get("raw") or "").splitlines():
            print("  " + line)
        if rep.get("ok"):
            print("[登录] 成功")
            sys.exit(0)
        if rep.get("qr"):
            print("[二维码] %s" % os.path.abspath(rep["qr"]))
            print("[登录] 还没扫码（或已超时）。把上面这张二维码图片发到对话里让用户扫，"
                  "然后重跑：run.py login")
        sys.exit(4)


    if a.cmd == "check":
        ok = True
        for name, exists, path in C.probe_env():
            print("  %s %-16s %s" % ("OK  " if exists else "缺失", name, path))
            ok = ok and exists
        if not (os.path.exists(C.SHERPA) and os.path.exists(C.MODEL) and os.path.exists(C.TOKENS)):
            print("\n提示：ASR 是第三方开源项目（sherpa-onnx + SenseVoice），需单独安装。")
            print("      安装与适配见 docs/ASR.md，然后把路径写进 config.json 的 asr_home。")
            print("      没装 ASR 也能用：--no-transcribe 只取 PPT / 官方字幕。")
            print("      当前配置：%s（来源：%s）" % (settings.CONFIG_PATH, settings.get("_source")))
        try:
            import urllib.request
            urllib.request.urlopen("http://127.0.0.1:%d/json/version" % session_resolve.CDP_PORT, timeout=2)
            print("  信息 浏览器调试端口     http://127.0.0.1:%d（已有浏览器在跑，将复用）" % session_resolve.CDP_PORT)
        except Exception:
            print("  信息 浏览器调试端口     未开启（首次运行会自动启动 Edge，属正常）")
        try:
            import PIL
            print("  OK   PDF 合成            Pillow %s（课件 PDF 用；缺失则只留 jpg）" % PIL.__version__)
        except Exception:
            print("  --   PDF 合成            缺 Pillow（课件不合成 PDF）")
        print("\n结论：", "环境就绪" if ok else "有依赖缺失，见上")
        sys.exit(0 if ok else 2)

    if a.cmd == "prune":
        sys.exit(prune_runs(a.outdir, a.apply))

    if a.cmd == "overview":
        sys.exit(overview(a.outdir, a.term))

    if a.cmd == "courseware":
        info = load_sessions(a.sessions)
        if a.into:
            if not os.path.isdir(a.into):
                print("[错误] --into 指向的运行目录不存在：%s" % a.into)
                sys.exit(1)
            code, _ = cmd_courseware(info, a, run_root=a.into)
            if code == 0:
                print_delivery(a.into)
            sys.exit(code)
        code, root = cmd_courseware(info, a)
        if code == 0 and root:
            print_delivery(root)
        sys.exit(code)

    if a.cmd == "plan":
        if a.sessions:
            with open(a.sessions, encoding="utf-8") as f:
                info = json.load(f)
        else:
            info = session_resolve.resolve_course(None, a.tecl_id, 0, a.course,
                                                  headless=a.headless)
            if handle_blocker(info):
                sys.exit(4 if info.get("_need_login") else 3)
        sys.exit(plan_report(info, a.outdir))

    if a.cmd in ("resolve", "all"):
        if not (a.url or a.course or a.tecl_id):
            print("[错误] 至少给一个：--url <链接> / --course <课程名> / --tecl-id <数字>")
            sys.exit(2)
        info = session_resolve.resolve_course(a.url, a.tecl_id, a.login_wait,
                                              getattr(a, "course", None),
                                              headless=a.headless)
        if handle_blocker(info):
            sys.exit(4 if info.get("_need_login") else 3)
        if a.cmd == "all":
            # 顺手落一份标准会话清单：AGENTS.md §3-② 的「只补 PPT / 官方记录」要用它，
            # 而以前只有 resolve --save 才会写，all 跑完什么都拿不到。
            try:
                p = save_sessions(info)
                print("→ 会话清单：%s" % p)
            except Exception as e:
                print("  [警告] 会话清单未落盘：%s" % e)
        if a.cmd == "resolve":
            out = json.dumps(info, ensure_ascii=False, indent=1)
            if a.save:
                with open(a.save, "w", encoding="utf-8") as f:
                    f.write(out)
                print("→", a.save)
                print("共 %d 个节次；课次：%s" % (
                    len(info["sessions"]),
                    "、".join(sorted({s["date"] for s in info["sessions"]}))))
            else:
                print(out)
            return
    else:
        info = load_sessions(a.sessions)

    res = run_process(info, a, a.outdir)
    if not res:
        sys.exit(1)
    run_root, entries = res
    print("\n=== 完成 ===")
    print("输出目录：", run_root)
    for e in entries:
        print("  %-10s %s" % (e["segName"], "OK" if not e["error"] else "失败: " + e["error"]))
    print_delivery(run_root)


if __name__ == "__main__":
    main()
