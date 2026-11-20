# 兼容性与异设备筛查

目标：**换一台机器（甚至换一个人）只需改 `config.json`**。下表是逐项筛查的结果。

## 一、已消除的写死项

| 原状态 | 风险 | 现在 |
|---|---|---|
| `ASR_HOME` 默认 `D:\<你自己的ASR目录>` | 别人机器上不存在 → 全流程跑不动 | 读 `config.json` 的 `asr_home`，可用环境变量覆盖；缺失时自检报"未配置"而不是乱跑 |
| 6 个 JS 里写死 `<某个本机安装路径>/playwright-core` | 路径不存在 → 所有浏览器操作崩 | 改为 `process.env.PLAYWRIGHT_CORE \|\| 'playwright-core'`，`npm install` 后开箱可用 |
| 杀进程按 `*<仓库目录名>\edge-profile*` 匹配 | 换目录名/换机器 → 杀不到，残留进程占端口 | 用 `config.profile_dir` 解析出的**完整 profile 路径**匹配 |
| `probes/*.js` 写死 `teclIds=<某门课的ID>` | 泄漏作者课程 + 别人跑不通 | 改为从页面 URL / `globalThis.TECL_ID` 取 |
| `--sense-voice-language=zh` 硬编码 | 其它语种课程无法识别 | 读 `config.asr_language` |
| 引擎临时目录固定在 `ASR_HOME\temp` | 未配置 ASR 时无目录可写 | 未配置时退回系统临时目录 |

## 二、Windows 相关（本工具的既有前提）

| 项目 | 现状 | 换设备的注意点 |
|---|---|---|
| Edge 可执行文件 | 依次找 `Program Files`、`Program Files (x86)`、`%LOCALAPPDATA%`，可用 `edge_path` 指定 | 绿色版 / 便携版 Edge 必须显式配 `edge_path` |
| 残留进程清理 | `Get-CimInstance Win32_Process` + `Stop-Process`（PowerShell） | 依赖 WMI 服务正常；PowerShell 被策略限制时会失败（已有 try/except，退化为"等它自己退"） |
| 非 Windows | 保留了 `pkill -f <profile>` 与常见 Edge 安装路径 | **未验证**，macOS/Linux 上请自行改 `_find_edge()` |
| 路径分隔符 | 全走 `os.path.join`，JS 用 `/` | 正常 |

## 三、编码与路径

| 项目 | 现象 | 处理 |
|---|---|---|
| 仓库放在中文路径下 | 浏览器、ffmpeg、Python 都没问题 | 可以用 |
| **ASR 引擎读中文路径会失败** | 引擎直接在中文目录报错/输出空 | 切块与临时文件强制放在**纯 ASCII** 目录：`asr_home\temp\cr\<tag>_<crc32>`（未配置 ASR 时用系统临时目录） |
| 路径超长（>260 字符） | Windows 未开长路径支持时写文件失败 | `outputs\<课名>_<id>_<日期>\<日期>\audio\xxx.m4a` 容易逼近上限；建议开启 `LongPathsEnabled`，或把仓库放浅一点 |
| 控制台中文乱码 | 仅显示问题，文件本身是 UTF-8 | 先 `chcp 65001`，或设 `PYTHONUTF8=1` |

## 四、浏览器与登录（最脆的一环）

| 项目 | 现状 | 可能失效的点 |
|---|---|---|
| 端口 | 默认 `9222`，可改 `cdp_port` | **端口被占用时会直接复用那个浏览器**；如果那是别人/别的项目的 Edge，行为不可预期。换端口即可 |
| profile 独占 | `edge-profile\` 由 Edge 独占 | 同一台机器上**同时只能跑一个进程**用这个 profile |
| 登录判定 | 看当前页面是否还在 SSO 域 | 平台改版、SSO 域名变化 → 判定失效 |
| 扫码登录 | 点 `.ant-tabs-tab` 里含「扫码」的标签，截 `img[src*=qrlogin]` | Ant Design 版本升级 / 标签文案变化 → 需改选择器（在 `pipeline/qr_login.js`） |
| 密码登录 | **不做**（易盾拼图滑块会拦合成拖拽） | 永远需要人工 |
| 无头模式 | `--headless=new`，1600×1000 | 若平台未来做无头检测，需改回可见模式（`--show`） |
| cookie 快照 | `pipeline/_gen/cookies_<port>.json`，12 小时 TTL | 只是"省一次扫码"，不是保活；过期就重新扫 |

## 五、资源开销（换设备前先看）

| 项目 | 量级 |
|---|---|
| 每段 m4a | ≈23 MB / 55 分钟（16 kHz 单声道 64 kbps） |
| 每段峰值临时占用 | mp4 + wav ≈ 1 GB，跑完自动删（`_work\`） |
| 识别速度 | 8 线程 CPU 下约 5–10× 实时（55 分钟课约 6–10 分钟）；无 GPU 依赖 |
| 并发下载 | 默认 8 连接（单连接会被限速），可改 `fetch_media.py --conn` |

## 六、换机器的最小步骤（清单）

1. 装 Python 3.9+、Node 18+、ffmpeg（进 PATH）、Edge；
2. `npm install`；
3. 按 [docs/ASR.md](ASR.md) 装外部 ASR，把三个路径写进 `config.json`；
4. `python pipeline\run.py check` → 全 `OK`；
5. `python pipeline\run.py login` → 扫码；
6. `python pipeline\run.py plan --course "课名"` → 能看到日期就说明整条链路通了。

任何一步失败，先看 `check` 的输出——它会把每个依赖的**解析后绝对路径**打出来，比猜快得多。
