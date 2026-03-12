"""
Qwen3 ASR/TTS Dashboard
========================
统一管理面板，聚合 ASR (8200) 和 TTS (58201) 两个服务。
支持多后端 TTS: qwen3-tts / edge-tts / cosyvoice3
端口: 8210
"""

import asyncio
import logging
import os
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dashboard")

ASR_BASE = os.getenv("ASR_BASE", "http://127.0.0.1:8200")
TTS_BASE = os.getenv("TTS_BASE", "http://127.0.0.1:58201")

app = FastAPI(title="Qwen3 Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

client = httpx.AsyncClient(timeout=60.0)


# ── API Aggregation ──────────────────────────────────────────

@app.get("/api/status")
async def status():
    """聚合两个服务的健康状态。"""
    async def check(name, url):
        try:
            r = await client.get(f"{url}/health", timeout=5.0)
            data = r.json()
            data["status"] = "running"
            return {name: data}
        except Exception as e:
            return {name: {"status": "offline", "error": str(e)}}

    results = await asyncio.gather(check("asr", ASR_BASE), check("tts", TTS_BASE))
    merged = {}
    for r in results:
        merged.update(r)
    return merged


@app.get("/api/asr/prompt")
async def asr_prompt():
    try:
        r = await client.get(f"{ASR_BASE}/prompt")
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/tts/voices")
async def tts_voices():
    try:
        r = await client.get(f"{TTS_BASE}/v1/voices")
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/asr/transcribe")
async def asr_transcribe(file: UploadFile = File(...), language: str = Form(default="")):
    """代理 ASR 请求。"""
    data = await file.read()
    files = {"file": (file.filename, data, file.content_type or "audio/wav")}
    form = {"model": "qwen3-asr-1.7b"}
    if language.strip():
        form["language"] = language.strip()
    r = await client.post(f"{ASR_BASE}/v1/audio/transcriptions", files=files, data=form)
    return r.json()


@app.get("/api/tts/logs")
async def tts_logs(since_id: int = 0, limit: int = 50):
    try:
        r = await client.get(f"{TTS_BASE}/v1/logs", params={"since_id": since_id, "limit": limit})
        return r.json()
    except Exception as e:
        return {"error": str(e), "logs": [], "total": 0}


@app.post("/api/tts/synthesize")
async def tts_synthesize(request: Request):
    """代理 TTS 请求，返回音频。"""
    body = await request.json()
    r = await client.post(f"{TTS_BASE}/v1/audio/speech", json=body)
    return Response(content=r.content, media_type=r.headers.get("content-type", "audio/wav"))


# ── Dashboard HTML ───────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD_HTML


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Qwen3 语音服务管理面板</title>
<style>
  :root {
    --bg: #0f172a; --card: #1e293b; --border: #334155;
    --text: #e2e8f0; --muted: #94a3b8; --accent: #38bdf8;
    --green: #22c55e; --red: #ef4444; --orange: #f59e0b;
    --purple: #a78bfa; --cyan: #22d3ee;
    --radius: 12px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }
  .container { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
  h1 { font-size: 1.5rem; font-weight: 700; margin-bottom: 24px; display: flex; align-items: center; gap: 10px; }
  h1 span { font-size: 0.75rem; color: var(--muted); font-weight: 400; background: var(--card); padding: 4px 10px; border-radius: 20px; }

  /* Status Cards */
  .status-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }
  .status-card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; }
  .status-card h3 { font-size: 0.9rem; color: var(--muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.5px; }
  .status-card .status-line { display: flex; align-items: center; gap: 8px; font-size: 1.1rem; font-weight: 600; }
  .dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  .dot-sm { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; display: inline-block; }
  .dot.on, .dot-sm.on { background: var(--green); box-shadow: 0 0 8px var(--green); }
  .dot.off, .dot-sm.off { background: var(--red); box-shadow: 0 0 8px var(--red); }
  .dot.loading, .dot-sm.loading { background: var(--orange); animation: pulse 1s infinite; }
  @keyframes pulse { 50% { opacity: 0.4; } }
  .status-meta { font-size: 0.8rem; color: var(--muted); margin-top: 8px; }
  .backend-list { margin-top: 10px; display: flex; flex-direction: column; gap: 4px; }
  .backend-item { display: flex; align-items: center; gap: 6px; font-size: 0.8rem; color: var(--muted); }
  .backend-item .name { color: var(--text); font-weight: 500; min-width: 80px; }

  /* Tabs */
  .tabs { display: flex; gap: 4px; margin-bottom: 20px; background: var(--card); border-radius: var(--radius); padding: 4px; }
  .tab { flex: 1; text-align: center; padding: 10px; cursor: pointer; border-radius: 8px; font-size: 0.9rem; font-weight: 500; color: var(--muted); transition: all 0.2s; }
  .tab.active { background: var(--accent); color: #0f172a; }
  .tab:hover:not(.active) { color: var(--text); }

  /* Panels */
  .panel { display: none; background: var(--card); border: 1px solid var(--border); border-radius: var(--radius); padding: 24px; }
  .panel.active { display: block; }

  /* Form elements */
  label { font-size: 0.85rem; color: var(--muted); display: block; margin-bottom: 6px; }
  textarea, input[type=text], select {
    width: 100%; padding: 10px 14px; background: var(--bg); border: 1px solid var(--border);
    border-radius: 8px; color: var(--text); font-size: 0.9rem; resize: vertical;
  }
  textarea:focus, input:focus, select:focus { outline: none; border-color: var(--accent); }
  select { appearance: none; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='%2394a3b8' viewBox='0 0 16 16'%3E%3Cpath d='M8 11L3 6h10z'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 12px center; }
  .form-row { margin-bottom: 16px; }
  .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .form-grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }

  /* Buttons */
  .btn {
    display: inline-flex; align-items: center; gap: 6px; padding: 10px 20px;
    border: none; border-radius: 8px; font-size: 0.9rem; font-weight: 600;
    cursor: pointer; transition: all 0.15s;
  }
  .btn-primary { background: var(--accent); color: #0f172a; }
  .btn-primary:hover { filter: brightness(1.1); }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
  .btn-sm { padding: 6px 14px; font-size: 0.8rem; }

  /* Model badge */
  .model-badge {
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;
  }
  .model-badge.local { background: rgba(139,92,246,0.2); color: var(--purple); }
  .model-badge.cloud { background: rgba(34,211,238,0.2); color: var(--cyan); }

  /* Upload area */
  .upload-area {
    border: 2px dashed var(--border); border-radius: var(--radius); padding: 32px;
    text-align: center; cursor: pointer; transition: border-color 0.2s; position: relative;
  }
  .upload-area:hover, .upload-area.dragover { border-color: var(--accent); }
  .upload-area input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
  .upload-area .icon { font-size: 2rem; margin-bottom: 8px; }
  .upload-area .hint { font-size: 0.8rem; color: var(--muted); }
  .file-name { font-size: 0.85rem; color: var(--accent); margin-top: 8px; }

  /* Result */
  .result-box {
    margin-top: 16px; padding: 16px; background: var(--bg); border-radius: 8px;
    border: 1px solid var(--border); min-height: 48px; font-size: 0.95rem; line-height: 1.6;
    white-space: pre-wrap; word-break: break-all;
  }
  .result-box.empty { color: var(--muted); font-style: italic; }

  /* Audio player */
  audio { width: 100%; margin-top: 12px; border-radius: 8px; }
  .time-badge { font-size: 0.75rem; color: var(--muted); margin-top: 6px; }

  /* Info box */
  .info-box { background: var(--bg); border-radius: 8px; padding: 14px; font-size: 0.8rem; color: var(--muted); line-height: 1.6; margin-top: 16px; }
  .info-box code { background: var(--card); padding: 2px 6px; border-radius: 4px; font-size: 0.8rem; color: var(--accent); }

  /* Voice section in info */
  .voice-section { margin-bottom: 12px; }
  .voice-section h4 { font-size: 0.85rem; color: var(--accent); margin-bottom: 4px; }
  .voice-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
  .voice-tag { background: var(--card); padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; color: var(--text); }

  /* Backend hint */
  .backend-hint { font-size: 0.75rem; color: var(--muted); margin-top: 4px; font-style: italic; }

  /* Log table */
  .log-toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px; }
  .log-toolbar .stats { font-size: 0.8rem; color: var(--muted); }
  .log-toolbar .controls { display: flex; gap: 8px; align-items: center; }
  .log-toolbar .controls label { margin-bottom: 0; font-size: 0.8rem; }
  .log-table-wrap { overflow-x: auto; max-height: 520px; overflow-y: auto; border-radius: 8px; border: 1px solid var(--border); }
  .log-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  .log-table th { position: sticky; top: 0; background: var(--bg); color: var(--muted); font-weight: 600; text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; z-index: 1; }
  .log-table td { padding: 6px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
  .log-table tr:hover td { background: rgba(56,189,248,0.05); }
  .log-table .text-col { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .log-table .ok { color: var(--green); }
  .log-table .error { color: var(--red); }
  .live-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--green); margin-right: 4px; animation: pulse 1.5s infinite; }
  .log-empty { text-align: center; padding: 40px; color: var(--muted); font-style: italic; }

  @media (max-width: 640px) {
    .status-row { grid-template-columns: 1fr; }
    .form-grid { grid-template-columns: 1fr; }
    .form-grid-3 { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>
<div class="container">
  <h1>Qwen3 语音服务 <span>管理面板 v2.0</span></h1>

  <!-- Status Cards -->
  <div class="status-row">
    <div class="status-card">
      <h3>ASR 语音识别</h3>
      <div class="status-line"><span class="dot loading" id="asr-dot"></span><span id="asr-status">检查中...</span></div>
      <div class="status-meta" id="asr-meta">端口 8200</div>
    </div>
    <div class="status-card">
      <h3>TTS 语音合成</h3>
      <div class="status-line"><span class="dot loading" id="tts-dot"></span><span id="tts-status">检查中...</span></div>
      <div class="status-meta" id="tts-meta">端口 58201</div>
      <div class="backend-list" id="tts-backends">
        <div class="backend-item"><span class="dot-sm loading"></span><span class="name">qwen3-tts</span> <span class="model-badge local">本地</span></div>
        <div class="backend-item"><span class="dot-sm loading"></span><span class="name">edge-tts</span> <span class="model-badge cloud">云端</span></div>
        <div class="backend-item"><span class="dot-sm loading"></span><span class="name">cosyvoice3</span> <span class="model-badge local">本地</span></div>
      </div>
    </div>
  </div>

  <!-- Tabs -->
  <div class="tabs">
    <div class="tab active" onclick="switchTab('asr')">语音识别 (ASR)</div>
    <div class="tab" onclick="switchTab('tts')">语音合成 (TTS)</div>
    <div class="tab" onclick="switchTab('logs')">请求日志</div>
    <div class="tab" onclick="switchTab('info')">服务信息</div>
  </div>

  <!-- ASR Panel -->
  <div class="panel active" id="panel-asr">
    <div class="form-row">
      <label>上传音频文件</label>
      <div class="upload-area" id="upload-area">
        <input type="file" id="asr-file" accept="audio/*">
        <div class="icon">🎙️</div>
        <div>点击或拖拽上传音频文件</div>
        <div class="hint">支持 WAV, MP3, M4A, WEBM 等格式</div>
      </div>
      <div class="file-name" id="file-name"></div>
    </div>
    <div class="form-grid">
      <div class="form-row">
        <label>语言（可选，留空自动检测）</label>
        <select id="asr-lang">
          <option value="">自动检测</option>
          <option value="zh">中文</option>
          <option value="en">English</option>
          <option value="ja">日本語</option>
          <option value="ko">한국어</option>
          <option value="de">Deutsch</option>
          <option value="fr">Français</option>
          <option value="es">Español</option>
          <option value="ru">Русский</option>
        </select>
      </div>
      <div class="form-row" style="display:flex;align-items:flex-end;">
        <button class="btn btn-primary" id="asr-btn" onclick="doASR()" disabled>开始识别</button>
      </div>
    </div>
    <label>识别结果</label>
    <div class="result-box empty" id="asr-result">等待上传音频...</div>
  </div>

  <!-- TTS Panel -->
  <div class="panel" id="panel-tts">
    <div class="form-row">
      <label>输入文本</label>
      <textarea id="tts-text" rows="4" placeholder="输入要合成语音的文本..."></textarea>
    </div>
    <div class="form-grid-3">
      <div class="form-row">
        <label>模型 / 后端</label>
        <select id="tts-model" onchange="onModelChange()">
          <option value="qwen3-tts">Qwen3-TTS (本地)</option>
          <option value="edge-tts">Edge-TTS (云端极速)</option>
          <option value="cosyvoice3">CosyVoice3 (本地)</option>
        </select>
        <div class="backend-hint" id="model-hint">GPU 推理，高质量多语种</div>
      </div>
      <div class="form-row">
        <label>声音</label>
        <select id="tts-voice"></select>
      </div>
      <div class="form-row" id="instruct-row">
        <label>情感指令（可选）</label>
        <input type="text" id="tts-instruct" placeholder="如：用温柔的语气说">
      </div>
    </div>
    <button class="btn btn-primary" id="tts-btn" onclick="doTTS()">合成语音</button>
    <div id="tts-output"></div>
  </div>

  <!-- Logs Panel -->
  <div class="panel" id="panel-logs">
    <div class="log-toolbar">
      <div class="stats"><span class="live-dot"></span>实时日志 · <span id="log-total">0</span> 条记录</div>
      <div class="controls">
        <label><input type="checkbox" id="log-auto" checked> 自动刷新</label>
        <select id="log-filter" style="width:auto;padding:4px 24px 4px 8px;font-size:0.8rem;">
          <option value="">全部后端</option>
          <option value="qwen3-tts">qwen3-tts</option>
          <option value="edge-tts">edge-tts</option>
          <option value="cosyvoice3">cosyvoice3</option>
        </select>
        <button class="btn btn-sm btn-primary" onclick="fetchLogs(true)">刷新</button>
      </div>
    </div>
    <div class="log-table-wrap">
      <table class="log-table">
        <thead><tr>
          <th>时间</th><th>后端</th><th>声音</th><th>语言</th><th>文本</th><th>字数</th><th>耗时</th><th>大小</th><th>来源</th><th>状态</th>
        </tr></thead>
        <tbody id="log-body">
          <tr><td colspan="10" class="log-empty">加载中...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- Info Panel -->
  <div class="panel" id="panel-info">
    <div class="form-row">
      <label>ASR 当前 Prompt</label>
      <div class="result-box" id="info-prompt" style="max-height:200px;overflow-y:auto;">加载中...</div>
    </div>
    <div class="form-row">
      <label>TTS 多后端声音列表</label>
      <div class="result-box" id="info-voices" style="max-height:400px;overflow-y:auto;">加载中...</div>
    </div>
    <div class="info-box">
      <strong>API 端点</strong><br>
      ASR: <code>POST /v1/audio/transcriptions</code> → <code>http://服务器IP:8200</code><br>
      TTS: <code>POST /v1/audio/speech</code> → <code>http://服务器IP:58201</code><br>
      &nbsp;&nbsp;&nbsp;&nbsp;请求体 <code>model</code> 字段: <code>qwen3-tts</code> | <code>edge-tts</code> | <code>cosyvoice3</code><br>
      Dashboard: <code>http://服务器IP:8210</code><br><br>
      <strong>管理命令</strong><br>
      <code>sudo systemctl restart qwen3-asr</code><br>
      <code>sudo systemctl restart qwen3-tts</code><br>
      <code>sudo systemctl restart qwen3-dashboard</code>
    </div>
  </div>
</div>

<script>
const BASE = location.origin;

// ── Voice data cache ──
let voiceData = {};
const MODEL_HINTS = {
  'qwen3-tts': 'GPU 推理，高质量多语种',
  'edge-tts': '微软云端，极速响应 (~2s)',
  'cosyvoice3': 'GPU 推理，零样本克隆',
};

// ── Tabs ──
const TAB_NAMES = ['asr', 'tts', 'logs', 'info'];
let activeTab = 'asr';
function switchTab(name) {
  activeTab = name;
  document.querySelectorAll('.tab').forEach((t, i) => {
    const isActive = TAB_NAMES[i] === name;
    t.classList.toggle('active', isActive);
    document.getElementById('panel-' + TAB_NAMES[i]).classList.toggle('active', isActive);
  });
  if (name === 'info') loadInfo();
  if (name === 'logs') fetchLogs(true);
}

// ── Status check ──
async function checkStatus() {
  try {
    const r = await fetch(BASE + '/api/status');
    const d = await r.json();
    updateDot('asr', d.asr);
    updateTTSStatus(d.tts);
  } catch(e) {
    document.getElementById('asr-dot').className = 'dot off';
    document.getElementById('asr-status').textContent = '无法连接';
    document.getElementById('tts-dot').className = 'dot off';
    document.getElementById('tts-status').textContent = '无法连接';
    document.querySelectorAll('#tts-backends .dot-sm').forEach(d => d.className = 'dot-sm off');
  }
}

function updateDot(name, info) {
  const dot = document.getElementById(name+'-dot');
  const status = document.getElementById(name+'-status');
  const meta = document.getElementById(name+'-meta');
  if (info.status === 'running') {
    dot.className = 'dot on';
    status.textContent = '运行中';
    if (name === 'asr') meta.textContent = `端口 8200 · prompt ${info.prompt_loaded ? '已加载' : '未加载'}`;
  } else {
    dot.className = 'dot off';
    status.textContent = '离线';
    meta.textContent = info.error || '';
  }
}

function updateTTSStatus(info) {
  const dot = document.getElementById('tts-dot');
  const status = document.getElementById('tts-status');
  const meta = document.getElementById('tts-meta');
  if (info.status === 'running') {
    dot.className = 'dot on';
    status.textContent = '运行中';
    const backends = info.backends || {};
    const count = Object.keys(backends).length;
    meta.textContent = `端口 58201 · ${count} 个后端 · 默认 ${info.default_voice || 'Serena'}`;
    // Update per-backend dots
    const container = document.getElementById('tts-backends');
    container.innerHTML = '';
    const labels = {'qwen3-tts': ['Qwen3-TTS', 'local'], 'edge-tts': ['Edge-TTS', 'cloud'], 'cosyvoice3': ['CosyVoice3', 'local']};
    for (const [key, st] of Object.entries(backends)) {
      const label = labels[key] || [key, 'local'];
      const dotCls = st === 'ok' ? 'on' : 'off';
      container.innerHTML += `<div class="backend-item"><span class="dot-sm ${dotCls}"></span><span class="name">${label[0]}</span> <span class="model-badge ${label[1]}">${label[1] === 'cloud' ? '云端' : '本地'}</span></div>`;
    }
  } else {
    dot.className = 'dot off';
    status.textContent = '离线';
    meta.textContent = info.error || '';
    document.querySelectorAll('#tts-backends .dot-sm').forEach(d => d.className = 'dot-sm off');
  }
}

// ── ASR ──
const fileInput = document.getElementById('asr-file');
const uploadArea = document.getElementById('upload-area');

fileInput.addEventListener('change', () => {
  if (fileInput.files.length) {
    document.getElementById('file-name').textContent = '📄 ' + fileInput.files[0].name;
    document.getElementById('asr-btn').disabled = false;
  }
});
uploadArea.addEventListener('dragover', e => { e.preventDefault(); uploadArea.classList.add('dragover'); });
uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('dragover'));
uploadArea.addEventListener('drop', e => {
  e.preventDefault(); uploadArea.classList.remove('dragover');
  fileInput.files = e.dataTransfer.files;
  fileInput.dispatchEvent(new Event('change'));
});

async function doASR() {
  const btn = document.getElementById('asr-btn');
  const resultBox = document.getElementById('asr-result');
  btn.disabled = true; btn.textContent = '识别中...';
  resultBox.className = 'result-box empty'; resultBox.textContent = '正在识别...';

  const fd = new FormData();
  fd.append('file', fileInput.files[0]);
  fd.append('language', document.getElementById('asr-lang').value);

  const t0 = Date.now();
  try {
    const r = await fetch(BASE + '/api/asr/transcribe', { method: 'POST', body: fd });
    const d = await r.json();
    const ms = Date.now() - t0;
    resultBox.className = 'result-box';
    resultBox.textContent = d.text || '(空结果)';
    resultBox.innerHTML += `<div class="time-badge">耗时 ${(ms/1000).toFixed(2)}s</div>`;
  } catch(e) {
    resultBox.className = 'result-box empty';
    resultBox.textContent = '识别失败: ' + e.message;
  }
  btn.disabled = false; btn.textContent = '开始识别';
}

// ── TTS ──
function onModelChange() {
  const model = document.getElementById('tts-model').value;
  // Update hint
  document.getElementById('model-hint').textContent = MODEL_HINTS[model] || '';
  // Update voice dropdown
  updateVoiceDropdown(model);
  // Show/hide instruct row (only for qwen3-tts and cosyvoice3)
  document.getElementById('instruct-row').style.display = (model === 'edge-tts') ? 'none' : '';
}

function updateVoiceDropdown(model) {
  const sel = document.getElementById('tts-voice');
  sel.innerHTML = '';
  const data = voiceData[model];
  if (data && data.voices) {
    data.voices.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = v;
      if (data.default && v === data.default) opt.selected = true;
      sel.appendChild(opt);
    });
  } else {
    // Fallback defaults
    const defaults = {
      'qwen3-tts': ['Serena','Vivian','Dylan','Eric','Ryan','Aiden','Uncle_Fu','Ono_Anna','Sohee'],
      'edge-tts': ['xiaoxiao','xiaoyi','yunjian','yunxi','yunxia','yunyang'],
      'cosyvoice3': ['中文女','中文男','日语男','粤语女','英文女','英文男','韩语女'],
    };
    (defaults[model] || []).forEach(v => {
      const opt = document.createElement('option');
      opt.value = v; opt.textContent = v;
      sel.appendChild(opt);
    });
  }
}

async function loadVoices() {
  try {
    const r = await fetch(BASE + '/api/tts/voices');
    voiceData = await r.json();
    if (voiceData.error) voiceData = {};
  } catch(e) { voiceData = {}; }
  onModelChange();
}

async function doTTS() {
  const btn = document.getElementById('tts-btn');
  const output = document.getElementById('tts-output');
  const text = document.getElementById('tts-text').value.trim();
  if (!text) { alert('请输入文本'); return; }

  const model = document.getElementById('tts-model').value;
  btn.disabled = true; btn.textContent = '合成中...';
  output.innerHTML = `<div class="result-box empty">正在通过 ${model} 合成...</div>`;

  const body = {
    model: model,
    input: text,
    voice: document.getElementById('tts-voice').value,
  };
  const instruct = document.getElementById('tts-instruct').value.trim();
  if (instruct && model !== 'edge-tts') body.instruct = instruct;

  const t0 = Date.now();
  try {
    const r = await fetch(BASE + '/api/tts/synthesize', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    if (!r.ok) {
      const err = await r.text();
      throw new Error(`HTTP ${r.status}: ${err}`);
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    const ms = Date.now() - t0;
    output.innerHTML = `<audio controls autoplay src="${url}"></audio><div class="time-badge">${model} · 耗时 ${(ms/1000).toFixed(2)}s · ${(blob.size/1024).toFixed(0)} KB</div>`;
  } catch(e) {
    output.innerHTML = `<div class="result-box empty">合成失败: ${e.message}</div>`;
  }
  btn.disabled = false; btn.textContent = '合成语音';
}

// ── Info ──
async function loadInfo() {
  try {
    const [p, v] = await Promise.all([
      fetch(BASE + '/api/asr/prompt').then(r => r.json()),
      fetch(BASE + '/api/tts/voices').then(r => r.json()),
    ]);
    document.getElementById('info-prompt').textContent = p.prompt || '(未配置)';
    // Build per-backend voice info
    const box = document.getElementById('info-voices');
    if (v.error) { box.textContent = '加载失败: ' + v.error; return; }
    let html = '';
    const labels = {'qwen3-tts': 'Qwen3-TTS (本地 GPU)', 'edge-tts': 'Edge-TTS (微软云端)', 'cosyvoice3': 'CosyVoice3 (本地 GPU)'};
    for (const [backend, data] of Object.entries(v)) {
      const voices = data.voices || [];
      const defVoice = data.default ? ` · 默认: ${data.default}` : '';
      html += `<div class="voice-section"><h4>${labels[backend] || backend}${defVoice}</h4><div class="voice-tags">`;
      voices.forEach(voice => { html += `<span class="voice-tag">${voice}</span>`; });
      html += '</div></div>';
    }
    box.innerHTML = html;
  } catch(e) {
    document.getElementById('info-prompt').textContent = '加载失败';
    document.getElementById('info-voices').textContent = '加载失败';
  }
}

// ── Logs ──
let lastLogId = 0;
let allLogs = [];
let logTimer = null;

async function fetchLogs(full) {
  try {
    const sid = full ? 0 : lastLogId;
    const r = await fetch(BASE + `/api/tts/logs?since_id=${sid}&limit=200`);
    const d = await r.json();
    if (d.error) return;
    document.getElementById('log-total').textContent = d.total;
    if (full) {
      allLogs = d.logs || [];
    } else {
      const newLogs = (d.logs || []).filter(l => l.id > lastLogId);
      if (newLogs.length > 0) allLogs = allLogs.concat(newLogs);
    }
    if (allLogs.length > 0) lastLogId = allLogs[allLogs.length - 1].id;
    renderLogs();
  } catch(e) { /* silent */ }
}

function renderLogs() {
  const filter = document.getElementById('log-filter').value;
  const filtered = filter ? allLogs.filter(l => l.backend === filter) : allLogs;
  const body = document.getElementById('log-body');
  if (filtered.length === 0) {
    body.innerHTML = '<tr><td colspan="10" class="log-empty">暂无请求记录</td></tr>';
    return;
  }
  // Show newest first
  const rows = filtered.slice().reverse().map(l => {
    const st = l.status === 'ok'
      ? '<span class="ok">OK</span>'
      : `<span class="error" title="${(l.error||'').replace(/"/g,'&quot;')}">ERR</span>`;
    const sz = l.size > 0 ? (l.size / 1024).toFixed(0) + ' KB' : '-';
    const text = l.text.length >= 100 ? l.text + '...' : l.text;
    return `<tr>
      <td>${l.time.split(' ')[1] || l.time}</td>
      <td>${l.backend}</td>
      <td>${l.voice}</td>
      <td>${l.lang || '-'}</td>
      <td class="text-col" title="${text.replace(/"/g,'&quot;')}">${text}</td>
      <td>${l.text_len}</td>
      <td>${l.elapsed}s</td>
      <td>${sz}</td>
      <td>${l.client || '-'}</td>
      <td>${st}</td>
    </tr>`;
  });
  body.innerHTML = rows.join('');
}

document.getElementById('log-filter').addEventListener('change', renderLogs);

function startLogPolling() {
  if (logTimer) clearInterval(logTimer);
  logTimer = setInterval(() => {
    if (activeTab === 'logs' && document.getElementById('log-auto').checked) {
      fetchLogs(false);
    }
  }, 3000);
}

// ── Init ──
checkStatus();
setInterval(checkStatus, 15000);
loadVoices();
startLogPolling();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8210, log_level="info")
