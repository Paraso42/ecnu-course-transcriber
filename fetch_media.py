#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
分块并行下载（HTTP Range），支持断点续传与完整性校验。
用于从 ECNU 点播服务器拉取 mp4（单连接被限速 ~570 KB/s，多连接可叠加）。

用法:
  python fetch_media.py <url> <输出文件> [--conn 8] [--part 16]
"""
import argparse
import os
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import quote

CHUNK = 8 * 1024 * 1024  # 每个 Range 请求 8 MB


def ascii_url(u):
    """把 URL 里原样出现的中文按 UTF-8 百分号编码掉。

    平台个别直链带中文文件名（如 …/闵四教203-0920-D12-LS.mp4?auth_key=…），urllib 会把
    请求行按 ascii 编码，于是 head() 直接抛 UnicodeEncodeError，该段被判「下载失败」。
    只编码非 ASCII 部分，URL 保留字符（: / ? # & = % 等）原样不动。
    """
    try:
        u.encode("ascii")
        return u
    except UnicodeEncodeError:
        return quote(u, safe=":/?#[]@!$&'()*+,;=%~")


def head(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(r.headers["Content-Length"]), r.headers.get("Accept-Ranges", "")


def grab(url, start, end, path, retries=6):
    if os.path.exists(path) and os.path.getsize(path) == end - start + 1:
        return
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
                while True:
                    b = r.read(1024 * 256)
                    if not b:
                        break
                    f.write(b)
            if os.path.getsize(path) == end - start + 1:
                return
        except Exception as e:
            print(f"  [retry {attempt+1}] {start}-{end}: {e}", flush=True)
            time.sleep(2)
    raise RuntimeError(f"分块失败 {start}-{end}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("out")
    ap.add_argument("--conn", type=int, default=8)
    ap.add_argument("--part", type=int, default=16, help="每个连接分到的 8MB 块数上限，1=逐块抢")
    args = ap.parse_args()
    args.url = ascii_url(args.url)

    total, ranges = head(args.url)
    print(f"总大小 {total/1048576:.1f} MB  Accept-Ranges={ranges}")
    if os.path.exists(args.out) and os.path.getsize(args.out) == total:
        print("已完整存在，跳过")
        return

    part_dir = args.out + ".parts"
    os.makedirs(part_dir, exist_ok=True)
    jobs = []
    for s in range(0, total, CHUNK):
        e = min(s + CHUNK - 1, total - 1)
        p = os.path.join(part_dir, f"{s:012d}-{e:012d}")
        jobs.append((s, e, p))
    todo = [j for j in jobs if not (os.path.exists(j[2]) and os.path.getsize(j[2]) == j[1] - j[0] + 1)]
    print(f"分块 {len(jobs)} 个，待下 {len(todo)} 个，并发 {args.conn}")

    lock = threading.Lock()
    idx = {"i": 0}
    done = {"n": 0}
    err = []

    def worker():
        while True:
            with lock:
                if idx["i"] >= len(todo):
                    return
                s, e, p = todo[idx["i"]]
                idx["i"] += 1
            try:
                grab(args.url, s, e, p)
                with lock:
                    done["n"] += 1
                    if done["n"] % 5 == 0 or done["n"] == len(todo):
                        got = done["n"] * CHUNK / 1048576
                        print(f"  进度 {done['n']}/{len(todo)} 约 {got:.0f} MB", flush=True)
            except Exception as ex:
                err.append(str(ex))

    threads = [threading.Thread(target=worker) for _ in range(args.conn)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    if err:
        print("失败:", err[:3])
        sys.exit(1)

    print("合并…")
    with open(args.out, "wb") as out:
        for s, e, p in jobs:
            with open(p, "rb") as f:
                while True:
                    b = f.read(1024 * 1024)
                    if not b:
                        break
                    out.write(b)
    size = os.path.getsize(args.out)
    dt = time.time() - t0
    print(f"完成 {size/1048576:.1f} MB，用时 {dt/60:.1f} 分钟，平均 {size/dt/1048576:.2f} MB/s")
    if size != total:
        print("!! 大小不符")
        sys.exit(1)
    for _, _, p in jobs:
        try:
            os.remove(p)
        except OSError:
            pass
    try:
        os.rmdir(part_dir)
    except OSError:
        pass


if __name__ == "__main__":
    main()
