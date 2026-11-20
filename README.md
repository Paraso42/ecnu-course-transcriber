# ecnu-course-transcriber

[![ci](https://github.com/Paraso42/ecnu-course-transcriber/actions/workflows/ci.yml/badge.svg)](https://github.com/Paraso42/ecnu-course-transcriber/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

把**华东师范大学课程平台**（courses.ecnu.edu.cn）的课堂录播，变成可以读、可以搜、可以听的本地资料：

```
录播 → 音频(m4a) + 原始转写(raw.txt/json) + 浅层修订文本(light.txt)
      ↳ 可选：平台官方字幕 + AI 总结、每段一份 Word、平台「AI 课件」截图
```

它是给**一个人的一学期**用的工具，不是一个通用的爬虫框架：一次运行 = 一个文件夹，
每段录音的转写各存各的、时间戳各段从 0 起，不拼接、不改写。

---

## 它能做什么

| 能力 | 说明 |
|---|---|
| 盘点课程 | 只给课名，列出全部节次、日期、时长、哪些还没取 |
| 下载 + 转写 | 课程录播 → m4a（16 kHz 单声道）+ 带 `[HH:MM:SS]` 的逐句文本 |
| 浅层修订 | 只折叠口误重复、规范标点，**不碰术语、不改内容** |
| 官方记录 | 平台自带字幕与课后 AI 总结，原文照搬进 `official/` |
| Word 版 | 每段一份 docx：前面字幕、后面总结 |
| 课件截图 | 平台「AI 课件」切片（相机拍投影，不是 PPT 原件）+ 索引 + 合订 PDF |
| 断点续跑 | 已完成的段自动跳过；识别结果是按块缓存的，中断不白干 |

## 它不做什么

- **不做术语校正**（`干系胞→干细胞` 这类需要结合课件，留给下游）；
- **不做总结、润色、翻译、删减**；
- **不接管你的账号**：不读、不存、不传你的密码和验证码，登录靠你自己在浏览器里完成（扫码）；
- **不是通用平台工具**：接口是 ECNU 课程平台的，换学校要改 `pipeline/session_resolve.py`；
- **不伪造**：平台没有官方字幕就写"没有"，绝不用本地识别结果冒充。

---

## 前置条件

| 依赖 | 版本 / 说明 |
|---|---|
| Windows | 10 或 11（浏览器控制、进程清理走 Windows 路径；其它系统未验证） |
| Python | 3.9+（只用标准库，无需 pip 安装本项目依赖） |
| Node.js | 18+（跑浏览器探针；`npm install` 装 `playwright-core`） |
| Microsoft Edge | 任意近期版本（复用你已装的，不额外下载内核） |
| ffmpeg | 需在 PATH，或装在常见位置（脚本会自动找） |
| **外部 ASR** | **不在本仓库**：sherpa-onnx + SenseVoice，见 [docs/ASR.md](docs/ASR.md) |
| Pillow | 可选，只用于把课件截图合成 PDF（`pip install pillow`） |

---

## 快速开始

```powershell
git clone https://github.com/Paraso42/ecnu-course-transcriber.git
cd ecnu-course-transcriber

# 1. 装浏览器驱动
npm install

# 2. 写本机配置（路径按你的机器改）
copy config.example.json config.json

# 3. 装外部 ASR（一次性），见 docs/ASR.md，然后自检
python pipeline\run.py check

# 4. 登录（无头，不弹窗；失效会生成二维码让你扫）
python pipeline\run.py login

# 5. 盘点一门课，看它还缺哪几天
python pipeline\run.py plan --course "课程名"

# 6. 开跑（例如只取两天 + 顺带抓课件 + 官方记录做 Word）
python pipeline\run.py all --course "课程名" --dates "2026-11-10,2026-11-17" `
    --courseware --official-since 2026-11-10 --official-docx
```

跑完会打印一段可直接复制的**运行文件夹绝对路径**，例如：

```
D:\path\to\ecnu-course-transcriber\outputs\<课程名>_<teclId>_<运行日期>
```

---

## 配置：`config.json`

从 `config.example.json` 复制。`config.json` 被 `.gitignore` 排除，不会进版本库。

| 键 | 含义 | 缺省 |
|---|---|---|
| `asr_home` | 外部 ASR 目录（**必填**，否则只能 `--no-transcribe`） | 空 |
| `asr_bin` | 引擎可执行文件，相对 `asr_home` 或绝对路径 | `bin/sherpa-onnx-offline.exe` |
| `asr_model` | 模型文件 | `model/model.int8.onnx` |
| `asr_tokens` | 词表 | `model/tokens.txt` |
| `asr_language` | 识别语种（`zh`/`en`/`auto`…） | `zh` |
| `playwright_core` | 已有 playwright-core 的路径；留空则用 `npm install` 装的 | 空 |
| `edge_path` | 指定 Edge 可执行文件；留空自动查找 | 空 |
| `cdp_port` | 浏览器调试端口 | `9222` |
| `profile_dir` | 登录态目录（**含 cookie，勿提交**） | `edge-profile` |
| `outputs_dir` | 产出根目录 | `outputs` |
| `courseware_dir` | 独立抓课件时的根目录 | `courseware` |

环境变量 `ASR_HOME` / `PLAYWRIGHT_CORE` / `EDGE_PATH` / `CDP_PORT` 可临时覆盖同名配置。

---

## 常用命令

```powershell
python pipeline\run.py check                          # 依赖自检
python pipeline\run.py login                          # 登录态检查（失效则出二维码）
python pipeline\run.py plan    --course "课名"         # 盘点：日期/段数/缺哪些/官方与课件覆盖
python pipeline\run.py all     --course "课名" --dates "2026-11-10,2026-11-17"
python pipeline\run.py all     --url "<课程链接>"      # 用链接代替课名
python pipeline\run.py all     --course "课名" --dates "2026-11-10" --no-transcribe --courseware
python pipeline\run.py courseware --sessions sessions_<课>_<id>.json --dates "2026-11-10" --into outputs\<运行目录>
python pipeline\run.py overview                       # 进度总览
python pipeline\run.py prune                          # 清理旧运行（默认只演练）
```

四种产出组合对应：

| 想要 | 参数 |
|---|---|
| 只转写 | （默认） |
| 转写 + PPT | `--courseware` |
| 只要 PPT | `--courseware --no-transcribe` |
| 只要官方记录/Word | `--official-since <最早日期> [--official-docx] --no-transcribe` |

---

## 产出结构

```
outputs\<课程名>_<teclId>_<运行日期>\
    2026-11-10\
        audio\1110-1.m4a              原始语音，供人工试听
        1110-1.raw.txt                逐句 `[HH:MM:SS] 文本`
        1110-1.raw.json               句子级起止秒
        1110-1.light.txt              浅层修订（时间戳不变）
    official\
        2026-11-10\1110-1.official.txt  平台官方字幕（原文）
        word\1110-1_<日期>_官方字幕与总结.docx
    courseware\                       平台 AI 课件切片（加 --courseware 才有）
    manifest.json                     每段的文件与状态
    README.md                         本次产出说明
```

---

## 登录、隐私与账号安全

- 登录**由你本人完成**：`run.py login` 检测到未登录会在无头浏览器里截一张二维码 PNG，
  你用微信/企业微信扫一下即可。程序**不读、不输、不保存**你的密码与验证码。
- 登录态存在 `edge-profile\`（普通浏览器 profile）。这是唯一可能泄露账号的目录，
  **已在 `.gitignore` 中排除**；`pipeline/_gen/cookies_<端口>.json` 是同一登录态的 cookie 快照，
  同样被排除。分享仓库前请确认这两个位置没有被打包。
- 登录态会自然过期（数小时到数天）。本工具**不做保活、不续期**——过期就重新扫一次。
- 所有音频、文本、截图**只存在本地** `outputs\`、`courseware\`，不上传任何地方。
- 识别用的是本地离线模型（sherpa-onnx），没有云端 API 调用。

## 合理使用

本工具用于**个人学习**：把自己已选课程的录播转成便于检索的文字。
请遵守学校的课程平台使用规定与教师的知识产权——不要把课程录音、截图、转写二次分发，
不要用它批量抓取他人课程。

---

## 兼容性

换机器、换系统、换 Edge 版本可能踩到的坑，以及已经做过适配处理的位置，见
[docs/COMPAT.md](docs/COMPAT.md)。已知限制里面也写了"哪些必然需要人工介入"。

---

## 代码结构

```
pipeline/
    run.py            命令行入口：check / login / plan / resolve / all / process / courseware / overview / prune
    session_resolve.py 浏览器与接口：定位课程、列节次、取点播直链、登录态
    courseware.py     平台 AI 课件切片抓取（截图 + OCR + 去重 + PDF）
    asr_file.py       切块 → 调外部 ASR → 重组句子（句级时间戳）
    polish.py         raw → light 的浅层修订规则
    official.py       官方字幕/总结抓取与落盘
    official_docx.py  官方字幕 + 总结 → docx
    common.py         公共路径/工具/外部依赖自检
    settings.py       config.json 读取与环境变量覆盖
cdp_probe.js          CDP 探针驱动（node）
fetch_media.py        并发 HTTP 下载（支持 Range 续传）
probes/               手工调试用的页面内脚本样例
AGENTS.md             给 AI 智能体用的操作手册（本仓库也可当"技能说明"读）
docs/ASR.md           外部语音识别怎么装、怎么换
```

## 关于"智能体"

本仓库**刻意保持为"脚本 + 说明书"**，没有引入 LangChain / AutoGen 之类的框架：
`AGENTS.md` 描述了完整的工作流（先保登录 → 盘点 → 问清要什么 → 拼命令 → 交路径），
任何能执行命令的 AI 智能体读完它就能接手这个流程。想自己按命令行用，则完全不需要读 `AGENTS.md`。

## 许可

MIT，见 [LICENSE](LICENSE)。外部依赖各自遵循其许可（sherpa-onnx: Apache-2.0 等），详见 [docs/ASR.md](docs/ASR.md)。
