# Qwen3 Voice Service

OpenAI API 兼容的多后端语音合成服务 + 管理面板 + 浏览器语音提醒脚本 + OpenClaw Skill。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│  浏览器 (油猴脚本)                                           │
│  ┌─────────────────────┐    ┌─────────────────────────────┐ │
│  │ OpenClaw / 任意 AI  │───▶│ openclaw-tts-player.user.js │ │
│  │ 聊天界面            │    │ 检测到总结 → 调用 TTS API   │ │
│  └─────────────────────┘    └──────────────┬──────────────┘ │
└─────────────────────────────────────────────┼───────────────┘
                                              │ POST /v1/audio/speech
                                              ▼
┌─────────────────────────────────────────────────────────────┐
│  TTS Server (:58201)                                        │
│  ┌─────────────┐  ┌───────────┐  ┌───────────────────────┐ │
│  │  qwen3-tts  │  │  edge-tts │  │     cosyvoice3        │ │
│  │  本地 GPU   │  │  云端极速  │  │     本地 GPU          │ │
│  │  高质量     │  │  ~2s 响应  │  │     零样本克隆        │ │
│  └─────────────┘  └───────────┘  └───────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                              ▲
┌─────────────────────────────┼───────────────────────────────┐
│  Dashboard (:8210)          │  状态监控 / TTS 试听 / 请求日志 │
└─────────────────────────────────────────────────────────────┘
```

## 组件

| 组件 | 目录 | 说明 |
|------|------|------|
| **TTS Server** | `tts-server/` | 多后端语音合成服务，OpenAI API 兼容 |
| **Dashboard** | `dashboard/` | Web 管理面板，状态监控 + TTS 试听 + 实时请求日志 |
| **Userscript** | `userscript/` | 油猴脚本，AI 完成任务后自动语音播报 |
| **OpenClaw Skill** | `openclaw-skill/` | OpenClaw 技能插件，让 AI 自动输出语音通知格式 |
| **Systemd** | `systemd/` | systemd 服务配置文件 |

## OpenClaw Skill 一键安装

如果你使用 [OpenClaw](https://openclaw.ai/)，可以直接安装技能插件，无需手动配置 AI 提示词：

```bash
# 1. 将 skill 目录复制到 OpenClaw skills 目录
cp -r openclaw-skill ~/.openclaw/workspace/skills/tts-task-notify

# 2. 设置 TTS 服务器地址
export TTS_SERVER_URL="http://你的服务器IP:58201"
# 或写入 OpenClaw 配置持久化

# 3. 验证 TTS 服务可达
bash ~/.openclaw/workspace/skills/tts-task-notify/scripts/check-tts.sh
```

安装后 OpenClaw 会自动在任务完成时输出 `【任务完成总结】...[[END_SUMMARY]]` 格式的总结，配合油猴脚本即可实现语音通知。

详见 [`openclaw-skill/SKILL.md`](openclaw-skill/SKILL.md)。

## 快速开始

### 1. 环境准备

```bash
# 创建 conda 环境
conda create -n qwen3-tts python=3.10 -y
conda activate qwen3-tts

# 安装依赖
pip install fastapi uvicorn httpx pydantic numpy soundfile pydub torch edge-tts

# MP3 编码支持
conda install -c conda-forge ffmpeg -y

# (可选) CosyVoice3 依赖
pip install matplotlib x_transformers pyarrow pyworld librosa wetext torchcodec
```

### 2. 下载模型

```python
from huggingface_hub import snapshot_download

# Qwen3-TTS (必需)
snapshot_download('FunAudioLLM/Qwen3-TTS-12Hz-1.7B-CustomVoice',
                  local_dir='models/Qwen3-TTS')

# CosyVoice3 (可选)
snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512',
                  local_dir='models/CosyVoice3-0.5B')
```

CosyVoice3 还需要克隆源码仓库：

```bash
git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git
```

### 3. 启动 TTS Server

```bash
cd tts-server

# 基本启动 (仅 Qwen3 + Edge-TTS)
python server.py --model /path/to/Qwen3-TTS --port 58201

# 完整启动 (三后端)
export PYTHONPATH="/path/to/CosyVoice:/path/to/CosyVoice/third_party/Matcha-TTS:$PYTHONPATH"
python server.py \
    --model /path/to/Qwen3-TTS \
    --cosyvoice3-model /path/to/CosyVoice3-0.5B \
    --port 58201 \
    --voice Serena
```

或者编辑 `tts-server/start.sh` 中的路径后直接运行：

```bash
bash tts-server/start.sh
```

### 4. 启动 Dashboard

```bash
cd dashboard
python server.py
# 访问 http://服务器IP:8210
```

### 5. 安装油猴脚本

1. 安装 [Tampermonkey](https://www.tampermonkey.net/) 浏览器扩展
2. 新建脚本，粘贴 `userscript/openclaw-tts-player.user.js` 的内容
3. 修改配置区的服务器地址（见下方 [自定义配置](#自定义配置)）
4. 保存并刷新目标页面

## API 接口

### POST /v1/audio/speech

OpenAI TTS API 兼容端点。

```bash
curl -X POST http://服务器IP:58201/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "model": "edge-tts",
    "input": "你好，这是一段测试文本。",
    "voice": "Serena"
  }' \
  --output speech.mp3
```

**请求参数：**

| 参数 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `model` | string | 否 | 后端选择：`qwen3-tts` / `edge-tts` / `cosyvoice3`，默认 `qwen3-tts` |
| `input` | string | 是 | 要合成的文本 |
| `voice` | string | 否 | 声音名称，默认 `Serena` |
| `response_format` | string | 否 | 输出格式：`mp3` / `wav` / `flac`，默认 `mp3` |
| `speed` | float | 否 | 语速，默认 `1.0` |
| `instruct` | string | 否 | 情感/风格指令（仅 qwen3-tts 和 cosyvoice3） |
| `language` | string | 否 | 语言代码，如 `zh` / `en`，留空自动检测 |

### GET /v1/voices

获取所有后端的可用声音列表。

### GET /v1/logs?since_id=0&limit=50

获取最近的请求日志（增量拉取）。

### GET /health

服务健康检查，返回各后端状态。

## 可用声音

### qwen3-tts (本地 GPU)

| 声音 | 性别/语言 | OpenAI 映射 |
|------|----------|------------|
| Serena | 女/多语种 | alloy |
| Vivian | 女/多语种 | fable |
| Dylan | 男/多语种 | echo |
| Eric | 男/多语种 | - |
| Ryan | 男/多语种 | - |
| Aiden | 男/多语种 | - |
| Uncle_Fu | 男/中文 | onyx |
| Ono_Anna | 女/日语 | nova |
| Sohee | 女/韩语 | shimmer |

### edge-tts (微软云端)

| 声音 | 微软全名 |
|------|---------|
| xiaoxiao | zh-CN-XiaoxiaoNeural |
| xiaoyi | zh-CN-XiaoyiNeural |
| yunjian | zh-CN-YunjianNeural |
| yunxi | zh-CN-YunxiNeural |
| yunxia | zh-CN-YunxiaNeural |
| yunyang | zh-CN-YunyangNeural |

也支持 OpenAI 声音名称（alloy/echo 等），会按语言自动映射到中文或英文声音。

### cosyvoice3 (本地 GPU)

| 声音 | 说明 |
|------|------|
| 中文女 | 中文女声 |
| 中文男 | 中文男声 |
| 英文女 | 英文女声 |
| 英文男 | 英文男声 |
| 日语男 | 日语男声 |
| 粤语女 | 粤语女声 |
| 韩语女 | 韩语女声 |

## 自定义配置

### TTS Server (`tts-server/start.sh`)

编辑以下变量适配你的环境：

```bash
# ── 必须修改 ──
CONDA_BASE="$HOME/miniconda3"          # Conda 安装路径
ENV_NAME="qwen3-tts"                   # Conda 环境名
QWEN3_MODEL="$HOME/exps/models/..."    # Qwen3-TTS 模型路径
COSYVOICE3_MODEL="$HOME/exps/models/..." # CosyVoice3 模型路径 (可选)

# CosyVoice3 源码路径 (如不使用可删除)
export PYTHONPATH="$HOME/exps/CosyVoice:$HOME/exps/CosyVoice/third_party/Matcha-TTS:$PYTHONPATH"

# ── 可选修改 ──
HOST="0.0.0.0"         # 监听地址
PORT=58201              # 监听端口
DEFAULT_VOICE="Serena"  # 默认声音
```

### Dashboard (`dashboard/server.py`)

环境变量控制连接地址：

```bash
export ASR_BASE="http://127.0.0.1:8200"   # ASR 服务地址
export TTS_BASE="http://127.0.0.1:58201"  # TTS 服务地址
```

Dashboard 默认监听 `0.0.0.0:8210`。

### 油猴脚本 (`userscript/openclaw-tts-player.user.js`)

打开脚本编辑器，修改顶部配置区：

```javascript
// ====== 配置 ======
const TTS_URL   = 'http://192.168.110.219:58201/v1/audio/speech';  // ← 改成你的服务器 IP
const API_KEY   = 'sk-1234';       // API Key（占位，服务端不校验）
const TTS_MODEL = 'edge-tts';      // 默认后端: qwen3-tts / edge-tts / cosyvoice3
const TTS_VOICE = 'Serena';        // 默认声音

const START_MARKER = '【任务完成总结】';  // 开始标记
const END_MARKER   = '[[END_SUMMARY]]';   // 结束标记

const POLL_INTERVAL    = 3000;   // 轮询间隔 (毫秒)
const MAX_SUMMARY_LEN  = 150;    // 最大播报字数
```

**关键修改项：**

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `TTS_URL` | TTS 服务器完整地址 | `http://你的IP:58201/v1/audio/speech` |
| `TTS_MODEL` | 选择哪个后端 | `edge-tts`（最快）/ `qwen3-tts`（最高质量） |
| `TTS_VOICE` | 声音名称 | 参考上方声音列表 |
| `START_MARKER` | 总结开始标记 | 可自定义，需和 AI 提示词一致 |
| `END_MARKER` | 总结结束标记 | 可自定义，需和 AI 提示词一致 |

### 页面匹配规则

脚本默认只在局域网页面上运行：

```javascript
// @match  http://127.0.0.1:*/*
// @match  http://localhost:*/*
// @match  http://192.168.*:*/*
```

如需在其他页面使用，添加对应的 `@match` 规则，例如：

```javascript
// @match  https://chat.example.com/*
```

## AI 提示词配置

将以下内容添加到你的 AI 助手的 System Prompt 中，让它在完成任务时输出固定格式的总结：

```
## 任务完成语音提醒

当你完成一个任务或阶段性工作后，请在回复末尾附上一段固定格式的总结，
用于触发语音播报提醒我。

格式：
【任务完成总结】简短的完成摘要[[END_SUMMARY]]

规则：
1. 总结内容控制在 100 字以内，用自然口语化的中文
2. 只说"做了什么、结果如何"，不要说技术细节
3. 标记不要放在代码块里
4. 只在任务真正完成时才输出，中间过程不要输出
5. 每次回复最多输出一条总结
```

**示例输出：**

```
【任务完成总结】数据库迁移已完成，新增了三张业务表，所有测试通过。[[END_SUMMARY]]
```

```
【任务完成总结】首页加载优化完成，速度从3秒提升到1.2秒。[[END_SUMMARY]]
```

如果你修改了标记格式，记得同时修改油猴脚本中的 `START_MARKER` 和 `END_MARKER`。

## Systemd 部署

```bash
# 复制服务文件（需要先编辑路径）
sudo cp systemd/qwen3-tts.service /etc/systemd/system/
sudo cp systemd/qwen3-dashboard.service /etc/systemd/system/

# 启用并启动
sudo systemctl daemon-reload
sudo systemctl enable --now qwen3-tts
sudo systemctl enable --now qwen3-dashboard

# 查看状态
sudo systemctl status qwen3-tts
sudo systemctl status qwen3-dashboard

# 查看日志
sudo journalctl -u qwen3-tts -f
```

## 端口说明

| 端口 | 服务 | 用途 |
|------|------|------|
| 58201 | TTS Server | 语音合成 API |
| 8210 | Dashboard | Web 管理面板 |
| 8200 | ASR Server | 语音识别（独立部署，非本仓库） |

## License

MIT
