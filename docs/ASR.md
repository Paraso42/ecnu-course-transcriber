# 语音识别（ASR）：外部依赖，不属于本仓库

本仓库**只负责“取到音频 + 编排转写 + 浅层整理”**。真正的语音识别交给第三方开源项目：

| 组件 | 项目 | 作用 | 许可 |
|---|---|---|---|
| 推理运行时 | [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)（k2-fsa） | 离线 ONNX 推理，提供 `sherpa-onnx-offline` 可执行文件 | Apache-2.0 |
| 识别模型 | [SenseVoice](https://github.com/FunAudioLLM/SenseVoice)（阿里通义） | 中/英/日/韩/粤多语种识别，带 token 级时间戳 | 见模型仓库许可 |
| 打包好的模型 | `sherpa-onnx-sense-voice-*` | sherpa 团队转好的 ONNX 权重 | 见模型发布页 |

之所以拆开：ASR 引擎体积大（模型数百 MB）、更新节奏与业务逻辑无关、许可是别人的。
把它们塞进本仓库既不合规也不方便替换。

---

## 一、安装（Windows，10 分钟）

### 1. 放运行时

1. 打开 https://github.com/k2-fsa/sherpa-onnx/releases ，找 `sherpa-onnx-v<版本>-win-x64-shared.tar.bz2`（或 `-static`）下载解压；
2. 建议放在**不带中文和空格**的目录，例如 `D:\tools\sherpa-onnx`；
3. 确认目录里有：`bin\sherpa-onnx-offline.exe`。

### 2. 放模型

1. 在同一 releases 页面找 SenseVoice 模型包，命名类似
   `sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2`（后面可能更新日期）；
2. 解压后把 **`model.int8.onnx` 与 `tokens.txt`** 放进统一目录，例如 `D:\tools\sherpa-onnx\model\`。

最终结构（示例）：

```
D:\tools\sherpa-onnx\
    bin\sherpa-onnx-offline.exe
    model\model.int8.onnx
    model\tokens.txt
    temp\                      ← 可选，引擎临时目录
```

### 3. 填进 config.json

仓库根目录的 `config.json`（从 `config.example.json` 复制）：

```json
{
  "asr_home": "D:/tools/sherpa-onnx",
  "asr_bin": "bin/sherpa-onnx-offline.exe",
  "asr_model": "model/model.int8.onnx",
  "asr_tokens": "model/tokens.txt",
  "asr_language": "zh"
}
```

- `asr_home` 也可用环境变量 `ASR_HOME` 覆盖；
- 三个子路径**可以是相对 `asr_home` 的相对路径，也可以写绝对路径**——照你解压出来的结构填即可。

### 4. 自检

```powershell
python pipeline\run.py check
```

看到这三行都是 `OK` 就通了：

```
  OK   ASR 引擎           D:\tools\sherpa-onnx\bin\sherpa-onnx-offline.exe
  OK   SenseVoice 模型    D:\tools\sherpa-onnx\model\model.int8.onnx
  OK   词表 tokens.txt    D:\tools\sherpa-onnx\model\tokens.txt
```

### 5. 单独试一句

```powershell
D:\tools\sherpa-onnx\bin\sherpa-onnx-offline.exe `
  --tokens=D:\tools\sherpa-onnx\model\tokens.txt `
  --sense-voice-model=D:\tools\sherpa-onnx\model\model.int8.onnx `
  --sense-voice-language=zh `
  某个30秒以内的.wav
```

能打出 `{"text": "...", "tokens": [...], "timestamps": [...]}` 就说明引擎与模型匹配。

---

## 二、本仓库是怎么调用它的

`pipeline/asr_file.py` 做三件事：

1. 用 ffmpeg 把音频切成 **30 秒块**（SenseVoice 单次输入上限）；
2. 每 12 块一批调用一次 `sherpa-onnx-offline`，要求返回 `text + tokens + timestamps`；
3. 按标点把 token 流重组成句子，用 token 时间给每句起点 → 得到**句级时间戳**。

命令行形状（改引擎时对齐这个即可）：

```
sherpa-onnx-offline --tokens=<tokens.txt> --sense-voice-model=<model.onnx>
                    --sense-voice-language=zh --sense-voice-use-itn=true
                    --num-threads=8 chunk_0000.wav chunk_0001.wav ...
```

`--num-threads` 在 `pipeline/asr_file.py` 里，按你的 CPU 核数调（8 核以上一般 8～12）。

---

## 三、换别的引擎

只要满足“**输入 wav 列表，输出每块的 text/tokens/timestamps**”，就能替换：

1. 改 `config.json` 的 `asr_bin`（可执行文件）、`asr_model`、`asr_tokens`；
2. 若参数形态不同，改 `pipeline/asr_file.py` 里 `asr_files()` 拼命令的那几行；
3. `to_sentences()` 依赖 `tokens` 与 `timestamps` 两个字段——只要引擎能给出 token 级时间，
   时间戳质量就能保持；给不出 token 时间的话，句子时间只能退化为“块起点”。

推荐候选（都支持 ONNX 或带时间戳）：

- sherpa-onnx + Paraformer / Whisper 模型（换 `--sense-voice-model` 为对应参数）
- faster-whisper（Python 包，需自己写一层适配，能给词级时间）

---

## 四、常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `tokens ... does not exist` | 模型与 `tokens.txt` 不配套，或路径含中文。**引擎读不了中文路径**，把它放到纯 ASCII 目录 |
| 识别结果为空 | wav 采样率不是 16 kHz 单声道，或块长度超过 30 秒 |
| 极慢 | `--num-threads` 太小；或磁盘在机械盘上（切块 IO 瓶颈） |
| 中文乱码 | Windows 控制台代码页问题：`chcp 65001`，或设 `PYTHONUTF8=1` |
| 时间戳整体偏移 | 切块时用了 `-ss` 重编码；本仓库用 ffmpeg segment，块起点严格累加，正常不会偏 |
