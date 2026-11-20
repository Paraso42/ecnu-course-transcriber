# 安全说明

## 这个工具会接触什么

| 数据 | 位置 | 是否入库 |
|---|---|---|
| 浏览器登录态（cookie、Edge 保存的密码） | `edge-profile/` | **绝不**，已在 `.gitignore` |
| 登录态快照（cookie 明文 JSON） | `pipeline/_gen/cookies_<端口>.json` | **绝不**，已在 `.gitignore` |
| 课程录音 / 转写 / 官方字幕 / 课件截图 | `outputs/`、`courseware/` | **绝不** |
| 含签名直链的会话清单 | `sessions*.json` | **绝不** |
| 本机路径与端口 | `config.json` | **绝不**（仓库只有 `config.example.json`） |

## 账号安全边界

- 本工具**不读取、不输入、不保存**你的密码与短信验证码；
- 登录**只能由你本人**在浏览器里完成（推荐扫码）；
- 只复用你在 `edge-profile/` 里已有的登录态，登录态过期就重新扫一次；
- **不做**会话保活、自动续期、定时刷新——过期是预期行为；
- 没有任何网络请求会把本地文件上传到第三方服务（识别完全在本机离线进行）。

## 提交前的自查

```powershell
git status --porcelain            # 不该出现 edge-profile / outputs / config.json
git grep --cached -n -Ei 'cookie|token|passwd|secret' -- ':(exclude)pipeline/cookies.js'
```

若不小心把 `edge-profile/` 或快照提交过，**改密码 + 在 Edge 里注销该站点的登录**，
而不是只删文件——历史里仍然留着它。

## 报告问题

发现安全相关问题（例如某条路径会把 cookie 写到不该去的地方），请开 issue 描述复现步骤，
不要在 issue 里贴真实的 cookie、token、学号或姓名。
