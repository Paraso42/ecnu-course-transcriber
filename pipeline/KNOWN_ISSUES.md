# KNOWN_ISSUES — 一次真实补抓任务踩到的坑（课程名与 id 已隐去）

运行对象：某门课（补两个日期、共 6 段）。
产出目录：`outputs\<课程名>_<teclId>_<运行日期>`

结论先行：**转写 6/6 成功；PPT 切片 47 张（1102-2、1102-3）；官方字幕/总结 0/6（平台确实还没有）。**
下面是过程中的真问题与已做的修改。

---

## 已修复（A–I 全部）

### A. `qr_login.js` 定位不到二维码，且静默卡住

- 现象：`run.py login`（无参）在登录态失效时会自动转扫码，然后 10+ 分钟没有输出；
  node 进程常驻，PNG 一直不生成。我先入为主以为是 Edge profile 被占用，白杀了两次浏览器
  （反过来导致会话 cookie 丢失，又得重扫）。
- 根因（实测取证）：
  1. 新版 SSO 的二维码 `img` 不再稳定是 `img[src*=qrlogin]`，实测 src 前缀为
     `https://sso.ecnu.edu.cn/api/public/qrlog…`，tab 文案变成「扫码Scan」；
  2. 更关键的是**入口选错了**：直接打开
     `…/jy-application-resourcemanage-ui/` 时，未登录不会跳 SSO，而是停在应用自己的
     `#/login`，页面上根本没有二维码 → 旧逻辑既不报错也不退出；
  3. 用 `img` 自身 `screenshot()` 会把压在下缘的「请使用微信扫描」文字一起截进去。
- 修法（`pipeline\qr_login.js`）：
  - 入口改回根域名 `https://courses.ecnu.edu.cn`（只有这里会被 CAS 拦到 SSO）；
  - 若停在应用 `#/login`，再走一次根域名；仍非 SSO 则 `QR_FAIL` 明确失败；
  - 等待 URL 安定（页面在 root → 应用 → OAuth 之间跳转时不停下结论）；
  - 二维码定位：先按 `qrlog/qrcode/qrlogin` 找，找不到再按“宽高 ≥110 且接近正方形”的最大图兜底；
  - 保存方式改为把图片本身（data:URL 或接口直链）取下来写盘 → 得到 250×250 干净二维码；
  - 生成前先删掉上次残留的 PNG，失败时不会把旧图当成本次结果；
  - 全流程加硬超时 + 显式退出码，任何异常都打印 `QR_FAIL`，不再挂死。
- 验证：用临时 profile 起了一个**未登录**浏览器（端口 9223）实测 →
  `QR_SAVED {"hint":"请使用微信扫描二维码登录…"}`，4 秒后 `QR_TIMEOUT` 正常退出，图片是干净二维码。

### B. 登录判定口径错（两类误判）

- 旧实现（`session_resolve.logged_in`）：`"sso.ecnu.edu.cn" not in 全部标签页`。
  - ① 只要有一个残留 SSO 标签页，**已登录**的浏览器会被判成未登录 → `resolve` 直接 exit 4；
  - ② 未登录时应用停在 `#/login`（不是 SSO 域名），又会被判成**已登录**。
  - 两种都实测复现过（21:43 一次、22:39 一次）。
- 修法：改成“存在一个停在业务页的标签页”，排除 `sso.ecnu.edu.cn` 与 `#/login`；
  另外在复用已有浏览器前先跑 `close_sso_tabs()` 清掉残留 SSO 页（只在还有别的页面时才关，
  避免把唯一的页面关掉导致 `goto` 无页可用）。
- 验证：4 个用例单测全过（只 SSO / SSO+业务页 / 只有 #/login / 正常业务页）。

### C. `check_login` 只看 URL、不看接口（已修）

- 旧现象：SSO `maxAge=1800`，应用级 token 半小时过期，但页面 URL 还显示已登录 →
  「刚打印 `[登录] 有效`，20 分钟后课件接口全挂」。
- 连带根因：`courseware.py` / `official_sub.py` 的平台接口用的是**相对路径**
  （`/jy-application-resourcemanage/...`）。页面一旦停在 `sso.ecnu.edu.cn`，相对路径就打到
  SSO 域名上，拿到的是 HTML → 于是出现 `课件接口返回非 JSON`、官方记录「0/6」这种假结论。
- 修法：
  - 两个模块的 `API` 常量改成**绝对地址** `https://courses.ecnu.edu.cn/…`，不再依赖当前页面 origin；
  - 新增 `api_logged_in()`：真打一发课件接口做**保守**判定——只有“明确失效”
    （返回 HTML / 非 200 / 明确 err）才否决 URL 判定；“接口通了”不作为登录有效的证明
    （实测未登录也可能拿到 200+JSON），无法判定时仍以页面判定为准；
  - `logged_in_wait(12)`：SPA 会先渲染 `#/login` 再恢复会话，判定前等路由安定。
- 验证：`run.py login` → `[登录] 有效 / 判定依据：接口 200 + JSON（ok）`；
  单测覆盖四种响应（HTML→失效、JSON→有效、跨域失败→无法判定、check_login 联动）；
  端到端再跑一遍 `all --segs 1109-1 --no-transcribe --courseware --official-since 2026-11-09` 正常。

### D. 课件鉴权失败被误报成“这讲没课件”

- 旧现象：日志同时出现
  `1102-2 接口失败：课件接口返回非 JSON（courseId=539137）` 和
  `[注意] 这天没有课件切片（当天可能没讲课/在放片）` —— 真实原因是接口返回了登录页 HTML。
  重新登录后**同一批 courseId 抓到 47 张**。
- 修法（`courseware.py` + `run.py`）：
  - 新增 `LoginRequired`；返回体像 `<!DOCTYPE/<html` 或含 `sso.ecnu.edu.cn` 时抛它；
  - 抛它时**中止整次抓取**并以 **exit 4** 上报「需要登录」，不再写“可能没讲课”；
  - 只有“接口正常返回 0 张且当天没有失败项”才允许打印“平台本讲无切片”；
    有失败项时改打印「这天 N 个节次全部取失败，原因见上（不等于“没讲课”）」。
- 验证：单测（HTML→LoginRequired、正常 JSON 仍可解析）+ `cmd_courseware` 返回 4 的用例。

### E. `all` / `process` 抓课件时默认弹可见浏览器窗口

- 旧现象：本该无头的 `all` 运行里出现 `[浏览器] 启动可见 Edge`，窗口弹到桌面，
  并把 SSO 标签页留在 profile（进而触发 B）。
- 修法：`all` / `process` / `courseware` 三个子命令**默认无头**；要看窗口用新加的 `--show-browser`。
- 验证：用假 `resolve_course` 截获实参 —— 默认 True、`--show-browser` 为 False、`--headless` 仍 True；
  `courseware` 实跑也确认走无头并在结束时自动关闭（残留进程 0）。

### F. 补抓工作流的 sessions 文件对不上

- 旧现象：
  - `run.py courseware --sessions …` → `AttributeError: 'list' object has no attribute 'get'`
  - `official_sub.py --sessions …` → `TypeError: list indices must be integers`
  - 而全流程唯一落盘的是 `pipeline\_gen\sessions_<teclId>.out.json`，恰好是**裸数组**
    （27 项，只有 courseId/begin/end/vodStatus/transcriptTask）；
  - AGENTS.md §3-② 要求的 `sessions_<课>_<teclId>.json` 从来不会被写出来。
- 修法：
  - `load_sessions()` 两种格式都收；裸数组自动补 `date`（从 begin 截）、`index`、`segName`、`teclId`；
  - `all` 跑完自动落 `sessions_<课名>_<teclId>.json`（含 course / sessions / sourceUrl / resolvedAt）；
  - `official_sub.py` 同样兼容裸数组。
- 验证：用裸数组文件跑 `courseware` 不再崩；`all` 结束打印 `→ 会话清单：…sessions_<课名>_<teclId>.json`。

### G. `--dates` 只到“天”，补一段要重跑一整天

- 旧现象：plan 已标 `2026-11-02 done=2/3`，实际把 1102-1、1102-2 又完整重下 + 重识别
  （各 794 MB、约 5 分钟），只为补 1102-3。
- 修法：`all` / `process` / `courseware` 新增 `--segs 1102-3,1109-1`。
- 验证：`process --segs 1109-1 --no-transcribe` 只处理该段；`all --segs 1109-1 --no-transcribe` 同样只跑一段。

### H. 会话 cookie 只在“假设的”优雅关闭时落盘（已修）

- 旧现象：排障时手工 `Stop-Process` 掉 `edge-profile` 的 Edge，登录态立刻消失（本次复现三次，
  白扫两次码）。当时的说法是“cookie 只在优雅关闭时落盘，别手动 kill”。
- 深挖后发现更糟：**那个“优雅关闭”其实从来没生效过**。
  `close_browser()` 调的是 Playwright 的 `browser.close()`，而对 `connectOverCDP` 连接来说，
  它只断开连接、不会关掉浏览器 → CDP 一直活着 → 每次都被 `_kill_profile_procs()` 强杀。
  所谓“优雅关闭后仍残留的，精确清掉”其实是“每次都是强杀”。
- 修法：
  - 新增 `pipeline\close_browser.js`：显式发 CDP 的 `Browser.close`，Edge 才会正常退出并落盘；
    `close_browser()` 改成“先存 cookie 快照 → 发 Browser.close → 等 CDP 断开 → 真不退才强杀，
    并在日志里明说这次是强杀”；
  - 新增 `pipeline\cookies.js` + `session_resolve.sync_cookies()`：每次接触浏览器时把
    `ecnu.edu.cn` 域的 cookie（含 `SESSION` / `SOURCEID_TGC` / `__access_token` 这些会话 cookie）
    存到 `pipeline\_gen\cookies_<port>.json`，下次启动先把 12 小时内的快照灌回去。
- 验证（真杀真测）：先 dump 出 13 个 cookie → `Stop-Process` 杀掉全部 11 个 profile Edge 进程 →
  `run.py login` → `[登录] 已从快照灌回 13 个 cookie（省一次扫码）` + `[登录] 有效`，
  **没有要求重新扫码**；正常关闭路径也确认变成 `GRACEFUL_OK` / `已关闭后台浏览器`，无残留进程。

### I. 0 张切片也会建目录、留 0 字节 ocr.txt（已修）

- 旧现象：`courseware\<日期>\<段名>\ocr.txt` 是 0 字节文件，和“失败”长得一样；
  整讲 0 张时还会留一个空日期文件夹。
- 修法：`grab_segment()` 在 `docs` 为空时**不建目录**；`_write_ocr_txt()` 在无图无失败时直接返回；
  整讲一张都没有时连讲次目录、`索引.md`、PDF 都不生成（只在控制台和 `_课件清单.json` 里记账）。
- 验证：0 张的 2026-11-09 → 输出目录只剩 `README.md` + `_课件清单.json`，无任何空目录/空文件；
  有图的 2026-11-02 仍正常产出 47 张 + 索引 + 9.2 MB PDF，且只有出图的段才有 `ocr.txt`。

### 附：顺带修掉的一个瞬时错误

`ERR page.evaluate: Execution context was destroyed`（页面正在跳转时 evaluate）以前会直接算成
“这段取课件失败”——本次就因此白丢过 1109-2。现在 `_node()` 对这条错误自动重试 3 次，其余错误照旧抛出。
验证：同一命令从「1 段失败」变成「3 段都是 0 张、0 失败」。

---

## 给下一次的提醒

- 补 PPT / 官方记录：`python pipeline\run.py courseware --sessions sessions_<课>_<id>.json --dates <日期> --into <运行目录>`
- 只补官方记录 + Word：`python pipeline\official_sub.py --sessions … --run-dir … --since <日期> --docx`
- 官方记录为 0 时**不要**怀疑自己：先看 `official\official_subtitles.json`，`[无] 平台没有该节次的识别记录（http 200）`
  是平台的真实答复；同一门课早几讲有记录、最近一两讲没有，通常是平台还没处理完。
- 排障时**不要**手动 kill `edge-profile` 的 Edge 进程：用 `run.py login` 收尾即可。
  真要强杀也不至于丢登录态了（有 cookie 快照兜底），但没必要多冒一次险。
