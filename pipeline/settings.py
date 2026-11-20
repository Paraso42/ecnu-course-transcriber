#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""机型相关配置：config.json → 环境变量 → 内置默认值。

设计目标：**换一台机器只改 config.json，不改代码**。
优先级（高 → 低）：环境变量 > config.json > 默认值。

config.json 放在仓库根目录，已被 .gitignore 排除；仓库里只提交 config.example.json。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 允许用 COURSERES_CONFIG 指定另一份配置（便于一台机器跑多套环境）
CONFIG_PATH = os.environ.get("COURSERES_CONFIG") or os.path.join(ROOT, "config.json")

DEFAULTS = {
    # 外部 ASR 引擎目录（第三方项目，不属于本仓库）。留空则视为未安装。
    "asr_home": "",
    # 识别引擎可执行文件（相对 asr_home 或绝对路径）
    "asr_bin": "bin/sherpa-onnx-offline.exe",
    # SenseVoice 模型文件与词表（相对 asr_home 或绝对路径）
    "asr_model": "model/model.int8.onnx",
    "asr_tokens": "model/tokens.txt",
    # 可选：论坛/README 里常见的其它布局，改这三项即可
    "asr_language": "zh",
    # playwright-core 所在目录。留空 = 用仓库内 `npm install` 装的（require('playwright-core')）
    "playwright_core": "",
    # 可选：指定 Edge 可执行文件；留空则自动在常见安装位置查找
    "edge_path": "",
    # 浏览器调试端口与登录态目录
    "cdp_port": 9222,
    "profile_dir": "edge-profile",
    # 产出根目录（相对仓库根）
    "outputs_dir": "outputs",
    "courseware_dir": "courseware",
}

# 环境变量覆盖项：便于 CI / 临时切换
ENV_KEYS = {
    "ASR_HOME": "asr_home",
    "PLAYWRIGHT_CORE": "playwright_core",
    "EDGE_PATH": "edge_path",
    "CDP_PORT": "cdp_port",
}


def _resolve(p, base):
    """相对路径按仓库根解析；绝对路径原样返回。"""
    if not p:
        return ""
    p = os.path.expandvars(os.path.expanduser(str(p)))
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))


def load():
    cfg = dict(DEFAULTS)
    src = "默认值"
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8-sig") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update({k: v for k, v in data.items()
                            if k in DEFAULTS and v not in (None, "")})
                src = os.path.basename(CONFIG_PATH)
        except Exception as e:                                  # 配置坏了不该让整个流程崩
            print("[警告] %s 解析失败，改用默认值：%s" % (CONFIG_PATH, e), file=sys.stderr)
    for env, key in ENV_KEYS.items():
        v = os.environ.get(env)
        if v:
            cfg[key] = v
            src = "环境变量"
    cfg["_source"] = src
    return cfg


CONFIG = load()


def get(key):
    return CONFIG.get(key, DEFAULTS.get(key))


def asr_path(key):
    """asr_bin / asr_model / asr_tokens 这类相对 asr_home 的路径。"""
    raw = get(key)
    if not raw:
        return ""
    if os.path.isabs(raw):
        return raw
    home = get("asr_home")
    return os.path.normpath(os.path.join(home, raw)) if home else ""


def asr_home():
    return _resolve(get("asr_home"), ROOT)


def playwright_core():
    v = get("playwright_core")
    return _resolve(v, ROOT) if v else ""


def profile_dir():
    return _resolve(get("profile_dir") or "edge-profile", ROOT)


def cdp_port():
    try:
        return int(get("cdp_port") or 9222)
    except (TypeError, ValueError):
        return 9222


def node_env():
    """所有 node 子进程共享的环境变量：把配置传给 JS，避免脚本里写死路径。"""
    env = dict(os.environ)
    pw = playwright_core()
    if pw:
        env["PLAYWRIGHT_CORE"] = pw
    env["CDP_PORT"] = str(cdp_port())
    return env
