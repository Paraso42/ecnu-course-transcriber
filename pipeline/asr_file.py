#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""单个音频文件 → 原始转写（逐句带时间戳）。

输出：
  <name>.raw.txt   每行 `[HH:MM:SS] 句子`
  <name>.raw.json  结构化：{"sentences":[{"i","start","end","text"}], ...}

要点：
  * SenseVoice 单次输入约 30 秒，先切块再批量识别；
  * 引擎返回 tokens + 逐 token 起始时间 → 按句末标点重组句子，得到**句级时间戳**；
  * 跨块未断完的句子会接续到下一块，不会在 30 秒处被硬切断。
"""
import argparse
import glob
import json
import os
import re
import sys
import time

import common as C

END_PUNCT = "。？！"
ALL_PUNCT = "。？！，、；："
MAX_SENT_CHARS = 120      # 单句超长时强制断开，避免整段无标点
MIN_SENT_CHARS = 2        # 只有标点/单字的碎片直接丢


def split_wav(wav, cdir):
    C.require_ffmpeg()
    C.ensure_dirs(cdir)
    exist = sorted(glob.glob(os.path.join(cdir, "chunk_*.wav")))
    if exist:
        return exist
    r = C.run([C.FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", wav, "-f", "segment",
               "-segment_time", str(C.CHUNK), "-ac", "1", "-ar", "16000",
               os.path.join(cdir, "chunk_%04d.wav")])
    files = sorted(glob.glob(os.path.join(cdir, "chunk_*.wav")))
    if not files:
        raise RuntimeError("切块失败：" + (r.stderr or "")[-500:])
    return files


def asr_files(files, cache_path):
    """批量识别；结果按块号缓存在 cache_path（jsonl），支持断点续跑。"""
    done = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            for line in f:
                try:
                    o = json.loads(line)
                    done[o["i"]] = o
                except Exception:
                    pass
    todo = [(i, p) for i, p in enumerate(files) if i not in done]
    print("  [识别] 已完成 %d / 共 %d 块" % (len(done), len(files)))
    t0 = time.time()
    C.ensure_dirs(os.path.dirname(cache_path))
    with open(cache_path, "a", encoding="utf-8") as fout:
        for k in range(0, len(todo), C.BATCH):
            batch = todo[k:k + C.BATCH]
            r = C.run([C.SHERPA, "--tokens=" + C.TOKENS, "--sense-voice-model=" + C.MODEL,
                       "--sense-voice-language=" + (C.ASR_LANG or "auto"),
                       "--sense-voice-use-itn=true",
                       "--num-threads=8"] + [p for _, p in batch])
            objs = []
            for line in (r.stdout or "").splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if "tokens" in o or "text" in o:
                    objs.append(o)
            if len(objs) != len(batch):
                print("  [警告] 批次返回 %d/%d 条" % (len(objs), len(batch)))
            for (i, _), o in zip(batch, objs):
                rec = {"i": i, "text": o.get("text", ""),
                       "tokens": o.get("tokens") or [],
                       "timestamps": o.get("timestamps") or []}
                done[i] = rec
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            n = len(done)
            spd = n * C.CHUNK / max(1e-6, time.time() - t0)
            print("    进度 %d/%d (%d%%) %.0f×实时" % (n, len(files), round(n / len(files) * 100), spd))
    return [done[i] for i in sorted(done)]


def to_sentences(chunks, audio_duration=None):
    """把逐块 token 流重组成句子，返回 [{i,start,end,text}]"""
    sents = []
    buf, start = [], None
    last_t = 0.0

    for ci, ch in enumerate(chunks):
        toks = ch.get("tokens") or []
        ts = ch.get("timestamps") or []
        base = ci * C.CHUNK
        for j, tk in enumerate(toks):
            if not tk:
                continue
            t_abs = base + (ts[j] if j < len(ts) else last_t)
            last_t = t_abs
            if not buf:
                start = t_abs
            buf.append(tk)
            if tk in END_PUNCT:
                sents.append({"i": len(sents), "start": round(start, 3),
                              "end": round(t_abs + 0.3, 3), "text": "".join(buf).strip()})
                buf, start = [], None
            elif len(buf) >= MAX_SENT_CHARS:
                sents.append({"i": len(sents), "start": round(start, 3),
                              "end": round(t_abs + 0.3, 3), "text": "".join(buf).strip()})
                buf, start = [], None
    if buf:
        sents.append({"i": len(sents), "start": round(start, 3),
                      "end": round(last_t + 0.5, 3), "text": "".join(buf).strip()})

    # 去掉纯标点/极短碎片：过短的（如"那么。"）并入下一句，避免碎片句
    out = []
    pending = None
    for s in sents:
        core = s["text"].strip(ALL_PUNCT + " ")
        if len(core) < MIN_SENT_CHARS:
            continue
        if len(core) <= 4 and s["text"][-1] not in "？！":
            # 太短且不是问句/感叹 → 视为被打断的残句，挂到下一句开头
            pending = (pending[0] if pending else s["text"], pending[1] if pending else s["start"])
            continue
        if pending:
            s = dict(s)
            frag = pending[0].rstrip("。，、；： ")
            s["text"] = frag + s["text"]
            s["start"] = pending[1]
            pending = None
        s["i"] = len(out)
        out.append(s)
    if pending:                      # 结尾残句，单独保留
        out.append({"i": len(out), "start": round(pending[1], 3), "end": round(last_t + 0.5, 3),
                    "text": pending[0]})
    return out


def write_outputs(sents, outdir, name, meta):
    C.ensure_dirs(outdir)
    raw_txt = os.path.join(outdir, name + ".raw.txt")
    with open(raw_txt, "w", encoding="utf-8") as f:
        for s in sents:
            f.write("[%s] %s\n" % (C.fmt_ts(s["start"]), s["text"]))
    raw_json = os.path.join(outdir, name + ".raw.json")
    payload = dict(meta)
    payload.update({"name": name, "sentence_count": len(sents),
                    "chars": sum(len(s["text"]) for s in sents), "sentences": sents})
    with open(raw_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return raw_txt, raw_json


def transcribe(wav, outdir, name, work=None, extra_meta=None):
    C.ensure_dirs(outdir)
    # 注意：切块目录必须纯 ASCII——sherpa 读不了含中文的音频路径
    work = work or C.asr_scratch(outdir, name)
    files = split_wav(wav, os.path.join(work, "chunks_" + name))
    chunks = asr_files(files, os.path.join(work, name + ".chunks.jsonl"))
    sents = to_sentences(chunks)
    dur = None
    try:
        import wave
        with wave.open(wav, "rb") as w:
            dur = w.getnframes() / float(w.getframerate())
    except Exception:
        pass
    meta = {"audio": os.path.basename(wav), "duration_sec": round(dur, 2) if dur else None,
            "asr": {"engine": "sherpa-onnx + SenseVoice-Small int8",
                    "language": "zh", "itn": True, "chunk_sec": C.CHUNK,
                    "model": C.MODEL},
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    if extra_meta:
        meta.update(extra_meta)
    return write_outputs(sents, outdir, name, meta)


def main():
    ap = argparse.ArgumentParser(description="音频 → 原始转写（逐句时间戳）")
    ap.add_argument("wav")
    ap.add_argument("outdir")
    ap.add_argument("--name", required=True, help="输出文件前缀，如 0914-1")
    ap.add_argument("--work", default=None)
    a = ap.parse_args()
    C.require_env()
    t, j = transcribe(a.wav, a.outdir, a.name, a.work)
    print("→", t)
    print("→", j)


if __name__ == "__main__":
    sys.exit(main())
