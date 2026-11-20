# AGENTS.md — 课程语音提取与转写智能体

本工作区是**一个独立的功能智能体**：给它一个课程网页链接，它把该课程的课堂录播取到本地，转成
**原始语音文件 + 原始转写 + 初步修正文本** 三份产出，放进一个规整的输出文件夹。

它**只负责"提取 + 转写 + 浅层修订"这一段**（外加按需抓取平台自带的课件切片，当作素材交给下游）。
术语校正、知识梳理、与课件对照等工作，一律留给后续的
课程工作区（那里的智能体会结合课件与上下文处理）。

---

## 零、开场：用户只报一个课程名

用户第一句话可能只有课程名（如「课程名」），没有链接。**不要先跑下载、不要先解释**，
按下面五步走，全程用 `ask_user_question` 提问（不要只在正文里问）。

### 第 0 步：先保登录（一条命令，全程无头）

```powershell
python pipeline\run.py login
```

- **退出码 `0`**：登录态有效，直接进第 1 步；
- **退出码 `4`**：输出里有 `[二维码] <图片绝对路径>`。把这张 PNG 用 markdown 图片发到对话里，
  请用户用微信/企业微信扫（有效期约 1–2 分钟），扫完再跑一次本命令确认；
- 这条命令**无头运行**：不弹浏览器窗口、跑完自动关掉、不读也不存密码；
- **不要**试图“延长会话/定时保活”——登录态该过期就过期，每次任务开头重新确认即可。

### 第 1 步：盘点（一条命令）

```powershell
python pipeline\run.py plan --course "课程名"
```

输出是 JSON，关键字段：

| 字段 | 含义 |
|---|---|
| `course` | 课名、课号、teclId、学期、教师、总节次 |
| `dates[]` | 每个日期：`segs` 总段数、`done` 已识别段数、`status`（done/partial/none）、`missing[]`、`official`、`courseware` |
| `pendingDates` | **还没取完的日期**（提问只看这个） |
| `latestRun` | 该课最近一次运行目录（补抓课件/官方记录时用） |

退出码：`0` 正常；`4` 需要登录（Edge 已打开）；`3` 课程名没对上（带回候选课表）。

### 第 2 步：一次性问清两件事

用**一次** `ask_user_question` 调用、**两个**问题（两个都设 `multi_select: true`）：

> 记忆点：**转写也是可选项**。用户可能只要 PPT、只要官方记录，或"转写 + 任意组合"。
> 四项平级列出，不要预设谁必选，也不要用某一个选项去代表"全都不要"。

**问题 1 · 日期**（选项只放 `pendingDates`，**已完成的日期一律不列**）

- 每个选项的 label 写 `2026-11-10（3 段，未取）` 或 `2026-11-03（已取 1/3，缺 1103-2、1103-3）`
- 第一条固定放 `全部未完成日期（推荐）`（选它就等于把 pendingDates 全选）
- 若用户既勾了「全部」又勾了个别日期，**以「全部」为准**，不要重复跑或去重报错
- 若 `pendingDates` 为空：不要给出空选项，直接告诉用户"这门课现有节次都已取完"，
  再问是否要重跑某几天 / 是否换一门课。

**问题 2 · 本次要哪些产出**（`multi_select: true`，**四项平级，互不排斥**）

| 选项 | 对应能力 |
|---|---|
| `转写（m4a + raw / light）` | 下载 + 本地识别 + 两份文本（本工作区的主产出） |
| `PPT 课件截图` | 平台「AI 课件」切片（相机拍投影，不是 PPT 原件） |
| `官方字幕 + AI 总结` | 平台自带逐条字幕与课后总结，原样落 `official\` |
| `官方记录 Word 版` | 每段一份 docx（前面字幕、后面总结）；**选它自动包含「官方字幕 + AI 总结」** |

- **四项可以任意组合**：只勾 `PPT` 就是"这次只要课件、不转写"，完全合法；
- **一个都不勾** → 视为「只做转写」，并在回复里说明一句（避免空跑）；
- 只勾附加资源、没勾转写 → 命令**必须**带 `--no-transcribe`，否则会白跑一遍 ASR；
- 问题之间不要串行追问第二次；用户答完就开跑。

### 第 3 步：按选择拼命令并执行

```powershell
# ① 有未取日期（主路径）：新开一次运行
python pipeline\run.py all --course "课程名" --dates "2026-11-10,2026-11-17" `
    --courseware --official-since 2026-11-10 --official-docx

# ② 只补 PPT / 官方记录（转写早就有，不要重跑 ASR）：写进已有运行目录
python pipeline\run.py courseware --sessions sessions_<课>_<teclId>.json `
    --dates "2026-11-10" --into "<plan 给出的 latestRun>"
python pipeline\official_sub.py --sessions sessions_<课>_<teclId>.json `
    --run-dir "<plan 给出的 latestRun>" --since 2026-11-10 --docx
```

变量映射：

| 用户勾了 | 加什么参数 |
|---|---|
| `转写` | 不加（`all` 默认就下载 + 识别 + raw/light） |
| 没勾 `转写` | `--no-transcribe`（只取附加资源，不跑 ASR） |
| `PPT` | `--courseware` |
| `官方` | `--official-since <所选日期里最早的一天>` |
| `Word` | `--official-since <同上> --official-docx`（Word 依赖官方字幕，官方参数一并带上；程序也会自动补齐） |
| 一个都没勾 | 按"只做转写"处理：不加附加参数，并在回复里说明 |

没勾的能力**不要加**对应参数；**永远不要**因为"反正顺手"就加 `--audio-only`——那是"只听、不转写"的
例外路径，只有用户明确说"我只要音频听听"时才用。

四种典型组合（照抄即可）：

```powershell
# 只转写
python pipeline\run.py all --course "另一门课" --dates "2026-11-02"
# 转写 + PPT
python pipeline\run.py all --course "另一门课" --dates "2026-11-02" --courseware
# 只要 PPT（不转写）
python pipeline\run.py all --course "另一门课" --dates "2026-11-02" --courseware --no-transcribe
# 只要官方记录 + Word（不转写）
python pipeline\run.py all --course "另一门课" --dates "2026-11-02" `
    --official-since 2026-11-02 --official-docx --no-transcribe
```

### 第 4 步：交付路径（硬要求）

跑完必须把**运行文件夹的完整绝对路径**单独一行输出，不加引号、不加 markdown 修饰，方便直接复制：

```
<仓库根>\outputs\<课程名>_<teclId>_<运行日期>
```

程序结束时已自动打印 `=== 交付路径（可直接复制） ===` 段；有 `official\` / `courseware\`
时一并列出它们的绝对路径。**汇报里必须原样带上这段路径文本**——用户要把它粘给别的智能体。

---

## 一、触发与初始动作

用户通常只发一句话，例如：

> `https://courses.ecnu.edu.cn/...`（课程页面链接）

**若用户只给了课程名（没有链接）**：走上面的第零节，用 `plan --course <课名>` 开场。

收到链接后的第一件事，**不要先猜**，按下面顺序做：

1. `python pipeline\run.py resolve --url "<链接>" --save sessions.json`
   - 这一步会：启动（或复用）可见 Edge → 打开链接 → 检查登录 → 定位课程 → 列出全部节次与直链。
   - **退出码**：`0` 成功；`4` 需要用户登录；`3` 需要用户选课程。
   - **认课程的三种方式（自动依次尝试，不用你操心）**：
     1. 链接里带 `subjId= / teclId= / courseId=数字` 或路径含数字 → 直接读懂；
     2. 链接只是一串加密 token（如 `#/play-center?mko2GSK...==`）→ 打开页面后**读页面自己发出的
        请求与浏览器存储**，从 `courseId=` 反查 `courName`，再对上课程列表里的课名；
     3. 都没认出来 → 退出码 `3`，把 8 门课列出来等用户点。
2. 把 `sessions.json` 的内容整理成表格**给用户确认**：节次、日期、开始时间、时长、是否有点播直链。
3. 若退出码 `3`（认不出课程），把候选课程列表用 `ask_user_question` 让用户选，
   再用 `--tecl-id <数字>` 重跑。**也只有这种情况才需要打扰用户。**
4. 若退出码 `4`（登录态失效）：先跑 `python pipeline\run.py login`（**无头**，不弹窗）——
   它返回 `[二维码] <路径>` 时把那张图发到对话里让用户扫码，扫完重跑本命令。
   **绝不索要、绝不输入用户密码；也不要试图延长/保活会话**（该过期就过期）。
   易盾拼图滑块会拦截合成拖拽，别在这上面耗时间。

确认清单后，跑完整流程：

```powershell
python pipeline\run.py all --url "<链接>"
# 或只处理其中一天 / 前 N 段
python pipeline\run.py all --url "<链接>" --date 2026-10-12
python pipeline\run.py all --url "<链接>" --limit 3
```

> 已有 `sessions.json` 时可跳过解析：`python pipeline\run.py process --sessions sessions.json`

### 常见请求 → 对应命令

| 用户说 | 怎么做 |
|---|---|
| 「课程名」（只报课程名） | 走**第零节**：`plan --course` 盘点 → `ask_user_question` 问日期 + 资源 → 跑 → 给交付路径 |
| 「把这个课的录播都转成文字」 | `run.py all --url <链接>`（全量：下载→识别→两份文本）；只知课名时用 `--course <课名>` |
| 「我只要这一天的」 | 加 `--date 2026-10-12` |
| 「我想听某一段（比如 1019-2）」 | `run.py all --url <链接> --date 2026-10-19 --audio-only`，只出 m4a，不跑识别（约 4 分钟/段，23 MB） |
| 「先把节次列出来我看看」 | `run.py resolve --url <链接> --save sessions.json`（不下载） |
| 「这段文字读不懂，我想听原话」 | 先查该段 `*.raw.txt`（或 `*.raw.json`）里的时间戳，再把 m4a 拖到播放器对应位置；没有音频才用 `--audio-only` 补 |
| 「旧的运行文件夹能清掉吗」 | `python pipeline\run.py prune`（只演练，打印清单）；确认后加 `--apply`。只删"每个文件都能在更晚的同类运行里找到逐字节相同副本"的旧运行 |
| 「现在进度到哪了」 | `python pipeline\run.py overview`，按"课程 → 日期"汇报，见下节 |
| 「平台有没有官方语音识别记录？扒下来」 | `run.py process --sessions sessions.json --official-since 2026-10-10`（只扒不改，落 `official\`） |
| 「官方字幕和总结做成 Word」 | 同上再加 `--official-docx`，每段一份：前面字幕、后面总结；也可单跑 `python pipeline\official_sub.py --sessions sessions.json --run-dir outputs\<本次运行> --since <日期> --docx` |
| 「这两讲没有课件，去官网抓 PPT 截图」 | `run.py courseware --sessions sessions.json --date 2026-09-15 --label "2026-09-15=第1讲_导论"`（落 `courseware\`，独立成文件夹） |
| 「转写的同时把课件也一起抓了」 | `run.py all --url <链接> --courseware`（课件落到本次运行目录的 `courseware\`） |

### 官方语音识别记录（平台自带字幕 + AI 总结）

平台对部分录播自己做语音转写和课后 AI 总结，前端接口（需登录态）：

| 内容 | 接口 |
|---|---|
| 逐条字幕 | `GET /jy-application-resourcemanage/v1/course_vod_subtitle?courseId=<id>`（`bg/ed` 毫秒、`res` 文本） |
| AI 总结 | `GET /jy-application-resourcemanage/v1/course/ai/summary/search/<courseId>`（`fullOverview`、`keyPoints[]`、`documentSkims[]`） |
| 转写任务状态 | `GET .../v1/course/ai/transcript/optimize/tasks?courseId=<id>`（`status=0` 表示"初始化"，还没出记录） |

规矩：

1. **一个字也不改**：字幕、总结全部按平台原文逐字落盘，只加时间戳排版和分节标题；
2. 时间戳**只用平台给的**（`bg` 毫秒 → `HH:MM:SS`），不自己估；
3. 平台没有的节次就写"没有"，**不要用本地 ASR 冒充官方记录**；
4. 官方记录单独放 `official\`，**不与日期目录里的本地转写混放**。

### 课件截图（平台「AI 课件」切片）

有些讲次用户手里没有课件/PPT。平台会从录播里自动按讲授页截取画面并做 OCR，可以直接抓下来当素材：

```powershell
# 独立抓（一讲次一个文件夹）
python pipeline\run.py courseware --sessions sessions.json --date 2026-09-15 `
  --label "2026-09-15=第1讲_导论,2026-09-20=第2讲_神经科学基础"
# 写进已有运行目录（与转写同框，落在 <运行目录>\courseware\）
python pipeline\run.py courseware --sessions sessions.json --date 2026-09-15 --into outputs\<课程>_<id>_<日期>
# 转写时顺带抓
python pipeline\run.py all --url "<链接>" --courseware
```

| 内容 | 接口 |
|---|---|
| 课件切片清单 | `GET /jy-application-resourcemanage/v1/course/ai/ppt?courseId=<id>`（`docList[]`：`imageSeekTime` 段内秒、`imageUrl` jpg 直链、`ocrText` 画面文字） |

规矩：

1. 这是**相机拍投影**的截图，**不是 PPT 原件**（平台不提供原件下载）——向用户汇报时必须这么说，
   不要说"拿到了课件"；
2. 图片直链是公开的，下载**不需要 cookie**；但列清单要登录态，浏览器被登出时退出码 `4`；
3. 同一讲次内**按 md5 去重**（同页停留会被截多次），PDF 只留首次出现，`索引.md` 里标"重复帧"；
4. 索引里"疑似非课件"= 桌面/登录页/文件管理器这类画面，**只标注不删**，交给用户自己判断；
5. OCR 文字有错字，**以图为准**，不要拿 OCR 文字当课程资料；
6. 课件是**素材**，不做术语校正、不重排内容——那是课程工作区的事；
7. 有段返回 0 张就写"没有"，不要用别的段的上图凑数。

### 进度总览（回答「现在进度到哪了」）

```powershell
python pipeline\run.py overview                    # 全部学期
python pipeline\run.py overview --term 2026-2027   # 只看某学期
```

汇报规则：

- **只列有识别的课与日期**（该日期下有 `*.raw.txt` 才算识别过），空课程/失败日期不列；
- **只到日期这一级**：每个日期只给"段数 + 时长"，**不展开段名、不贴正文**；
- 课名下的 `已识别 X/Y 段` 是用户判断还剩多少的依据（Y = 课程总节次数），要保留；
- 出现 `⚠ 缺 m4a` / `⚠ 缺 light` 的行**必须原样转述**，不要淡化；
- 脚本输出已是对齐排版，直接转述即可（也可改成 markdown 表格），不要自行增删、不要加建议。

> `--audio-only` 是本工作区刻意保留的轻量模式：**只下载 + 转 m4a，不识别**，避免为了听 5 分钟而白跑整段 ASR。

## 二、产出规范（必须严格遵守）

```
outputs\<课程名>_<teclId>_<运行日期>\
    2026-10-12\                       ← 一个日期一个文件夹
        audio\1012-1.m4a               ← 原始语音：16 kHz 单声道 64k，供人工试听（≈23 MB/55 分钟）
        1012-1.raw.txt                 ← ① 原始转写，每句一行，行首 [HH:MM:SS]
        1012-1.raw.json                ← ① 的结构化版（每句起止秒）
        1012-1.light.txt               ← ② 初步修正文本（时间戳不变）
        audio\1012-2.*  1012-2.raw.txt  1012-2.light.txt   …
    official\                          ← 平台官方记录（有才写；没扒就不建这个目录）
        2026-10-12\
            1012-1.official.txt        ← ③ 平台逐条字幕，`[HH:MM:SS] 原文`
            1012-1.official.json       ← ③ 结构化（平台原始 bg/ed 毫秒）
            1012-1.summary.json        ← ④ 平台 AI 总结（原始返回）
            1012-1.summary.txt         ← ④ 可读版
        word\1012-1_<日期>_官方字幕与总结.docx   ← ⑤ 每段一份：前面字幕、后面总结
        official_subtitles.json        ← 官方记录覆盖情况（哪些段有、哪些没有）
    manifest.json                      ← 文件清单与元数据
    README.md                          ← 本次产出说明
    _work\                             ← mp4 与识别用 wav 的临时目录（用完自动删），可删
    courseware\                        ← 平台「AI 课件」切片（只有加了 --courseware 才有）
        第1讲_导论\
            0915-1\01_seek00001.jpg …  ocr.txt      ← 文件名里的秒数 = 该段出现时刻
            索引.md                                  ← 全讲次截图 + 时刻 + 类型 + 画面文字
            第1讲_导论_幻灯片.pdf                     ← 去重后按时间合订
        _课件清单.json                 ← 逐段切片数、失败项、PDF 页数
        README.md                      ← 来源与局限说明
```

独立抓取时（`run.py courseware`）落在 `courseware\<课程名>_<teclId>_<运行日期>\`，结构同上。

铁律：

1. **一次运行 = 一个输出文件夹**（用户要"一次一个文件夹方便拿取"）。
2. **同一门课同一天的所有节次放在同一个日期文件夹下，但绝不拼接**：音频不拼、文本不拼、时间戳各段从 0 起。
3. 每段必须齐 3 份文本 + 1 份音频（m4a）；缺任何一项都要在汇报里说明原因。
   （这条只适用于**勾了「转写」**的运行；`--no-transcribe` 的运行本来就没有这些文件，不要当成缺失）
4. 段名规则 `<MMDD>-<序号>`（同一天内按开始时间 1..N），由流水线自动生成，**不要手改**。
5. **时间戳只能来自引擎输出的 token 时间**。任何情况下不得臆造、四舍五入到分钟、或把段落时间累加错。
6. **音频只留 m4a**：用户的用途是"挑重点亲自听"，wav 只是识别时的中间文件，默认删除；只有用户
   明确要求归档高清源料时才加 `--keep-wav`。
7. **音频按需提取，不要预先批量取**：用户的习惯是"先看文字，遇到感兴趣的内容或读不懂的句子才回去听"。
   所以只在两种情况取音频：① 用户明确说想听某一段；② 这段要做转写（转写必然顺带产出 m4a）。
   绝不要因为"反正顺手"就把没走识别的节次也下载一遍。

## 三、能改与不能改（范围边界）

`*raw.txt` → `*light.txt` 这一步（`pipeline\polish.py`）**只允许**：

- 口误重复折叠：`这个这个` → `这个`、`这一步这一步` → `这一步`、`呃呃` → `呃`
- 单字结巴折叠：`的的`、`是是`、`在在` …
- 标点规范化：连续标点折叠、中文后的半角转全角、句首多余标点、句末补句号
- 中文之间的多余空格
- 碎片句并入下一句（如 `那么。` + 下一句）
- 超长无标点句在逗号处拆分

**严禁**（这些属于后续课程工作区）：

- 校正专业术语：`干系胞→干细胞`、`引窝→隐窝`、`判氏细胞→潘氏细胞`、`sonny 黑潮→Sonic hedgehog`、
  `b c l 十一 a→BCL11A`、`hope 细胞→hub cell` ……
- 改数字、人名、机构名、英文缩写，或"顺手翻译"
- 删减内容、总结、润色、调整语序
- 把语气词 `啊/呃/嗯` 删掉（约定：保留，便于回溯原话）

如果用户要求"顺便把术语也改对"，回答：这需要结合课件，建议在课程工作区里做；本工作区保产出中立。
（除非用户在这个工作区里明确要求扩展范围——那就先在 `polish.py` 里加规则，并说明这是新增能力。）

## 四、执行细节（照做即可）

| 步骤 | 命令/位置 | 说明 |
|---|---|---|
| 环境自检 | 流水线启动时自动 | 缺依赖会列出缺哪一项 |
| 浏览器 | `run.py login` 无头启动 Edge，profile 在 `edge-profile\` | 无头即可用：能取课程/节次/签名直链，下载走纯 HTTP 不经过浏览器；**只有 CAS 登录需要人工（扫码）**。跑完自动优雅关闭，不弹窗 |
| 登录 | `run.py login` | 先查登录态；失效则无头截二维码 PNG 供用户扫码。子命令都支持 `--headless`（不弹窗、跑完自动关） |
| 定位课程 | `probes\list_courses.js` | 拿 `subjId` / `teclId` |
| 认加密链接 | `sniff_page_ids()` + `match_sniff()` | 扫页面自身请求/存储里的 `courseId=`，反查课名 |
| 认不出时 | 退出码 3 + 候选列表 | 用 `ask_user_question` 让用户点，再 `--tecl-id` |
| 节次清单 | `probes\sessions2.js` 的等价接口 | 动态生成，含 `courseId` 与时间 |
| 点播直链 | `/v1/course_vod_urls_new?courseId=` | 取 `list[0].url` 与 `vodTime` |
| 下载 | `fetch_media.py --conn 8` | 单连接被限速，必须并发；4 个机位音轨相同只取 1 路 |
| 音频 | ffmpeg → 16 kHz 单声道 wav + m4a | 见 `pipeline\common.py` |
| 识别 | `<asr_home>\bin\sherpa-onnx-offline.exe` + SenseVoice int8 | **跨工作区调用，不复制进本工作区** |
| 分句 | `pipeline\asr_file.py` | 按 `。？！` 断句，用 token 时间给每句起点 |
| 修订 | `pipeline\polish.py` | 规则见上节 |
| 课件切片 | `pipeline\courseware.py`（`run.py courseware`） | `/v1/course/ai/ppt?courseId=`；投影截图 + OCR，同讲次按 md5 去重，PIL 合成 PDF |

## 五、出错怎么办

| 现象 | 处置 |
|---|---|
| 退出码 `3`：`[需要选择]` | 嗅探也没认出来。用 `ask_user_question` 让用户选课程，再 `--tecl-id` 重跑 |
| 播放页嗅探不到 | 页面可能需要点一下播放才发请求；让用户补一句课程名最省事，别反复重试 |
| 退出码 `4`：`[需要登录]` | 先跑 `python pipeline\run.py login`：它会无头检查；失效则生成二维码，把 `[二维码]` 那张图发到对话里让用户扫，再重跑原命令 |
| 退出码 `4`，但用户看不到桌面（远程/手机端，只能看聊天） | 一律走 `python pipeline\run.py login`：无头检查 → 失效则生成二维码 → 把图片发到对话里让用户扫。**不要**让用户把密码或短信验证码发过来；易盾拼图滑块会拦截合成拖拽，别在这上面耗时间 |
| `平台未给直链（可能未转码完成）` | 该节次跳过并在汇报里列出；请用户过几天再补，或换别的节次 |
| 下载报 403 | 签名过期：重跑 `resolve` 重新取链 |
| `下载失败` / 大小异常 | 重跑一次（脚本支持断点续传）；仍失败则记入 manifest 的 error 并汇报 |
| 识别报 `tokens ... does not exist` | 引擎/模型路径含非 ASCII 字符；确认 `config.json` 的 `asr_home` |
| Edge 目录被占用 | 先 `Get-CimInstance Win32_Process -Filter "Name='msedge.exe'"` 按命令行筛出用本 profile 的进程，结束它们 |
| 用户中途要另选日期 | 加 `--date` 重跑；已完成的段会自动跳过（`_work` 里的缓存也在） |
| 课件某段 0 张 | 该段平台没切片（当天没讲课/在放片）。写明"没有"，别用别段的图凑数 |
| 课件接口返回非 JSON / 报错 | 多半是登录态失效：重开 Edge 登录后重跑（退出码 `4`） |
| 课件 PDF 没生成 | 缺 Pillow：`pip install pillow`；或加 `--no-pdf` 只留 jpg + 索引，汇报时说明 |

## 六、完成的标准

1. `manifest.json` 里 `sessions[]` 每段的 `error` 为 `null`（有失败的必须逐条说明原因）；
   （本次没勾「转写」时，`error` 与 `files` 的空值属正常，不是失败）
2. 每个日期文件夹下，每段都有 `raw.txt / raw.json / light.txt / m4a`（wav 只是识别用的临时文件，
   跑完即删，**不作为验收项**；`_work\` 也允许为空）；同样只在勾了「转写」时校验
3. 抽查 2–3 句：`light.txt` 的时间戳与音频对应位置的内容一致（用 m4a 拖到该时间点听一耳朵）；
4. 向用户汇报：输出目录的**完整绝对路径**（单独一行、可直接复制，见第零节第 4 步）、
   各段时长与句数、失败项、以及"术语未校正"的提醒。

## 七、绝对不要做

- 不要为"提高准确率"而自行改写文本内容；
- 不要把多段音频/文本拼接成一份；
- 不要删除用户已有的输出文件夹（要重做就新建一次运行，或明确征得同意）；
  （唯一例外：用户自己要求清空间时，可跑 `run.py prune`，但**默认只演练**，加 `--apply` 前必须让用户看过清单）
- 不要索要或保存用户的账号、密码、验证码；
- 不要对课件截图做"美化"：不去水印、不裁掉 IPCamera 时间戳、不重排页面——原样交付 + 索引标注；
- 不要把 OCR 文字当成课程资料或转写文本使用（它只是定位线索）；
- 不要在这个工作区里存放与"提取+转写"无关的课程资料（课件、笔记请放到对应课程工作区）。

---

## 附：与其他工作区的关系

| 位置 | 职责 |
|---|---|
| **`<仓库根>`（本工作区）** | 取资源 → 转文字 → 出三份产出；缺课件的讲次可按需抓平台课件切片 |
| `<asr_home>`（第三方） | 离线识别引擎与模型，**不属于本仓库**，见 `docs\ASR.md` |
| 各课程工作区（你自己的其它目录） | 把本工作区的产出（含 `courseware\`）复制过去，结合课件做术语校正、知识梳理、复习笔记 |
