"""
Qwen3-TTS Multi-Backend Server
===============================
OpenAI TTS API 兼容的多后端语音合成服务。

支持后端:
  - qwen3-tts : 本地 Qwen3-TTS 模型 (GPU, 高质量, 较慢)
  - edge-tts  : 微软 Edge 在线 TTS (云端, 极速, 免费)
  - cosyvoice3: 本地 CosyVoice3 模型 (GPU, 快速, 高质量)

用法:
    python server.py [--host 0.0.0.0] [--port 58201]
"""

import argparse
import asyncio
import collections
import io
import logging
import os
import re
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from typing import Optional

import numpy as np
import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from pydub import AudioSegment
from starlette.background import BackgroundTask

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("qwen3-tts-server")

# ---------------------------------------------------------------------------
# Global model references
# ---------------------------------------------------------------------------
qwen3_model = None
cosyvoice3_model = None

# ---------------------------------------------------------------------------
# Request log ring buffer (in-memory, max 200 entries)
# ---------------------------------------------------------------------------
_log_id_counter = 0
_request_logs: collections.deque = collections.deque(maxlen=200)

# ---------------------------------------------------------------------------
# Voice configuration
# ---------------------------------------------------------------------------

# Qwen3-TTS 预置声音
QWEN3_VOICES = [
    "Vivian", "Serena", "Uncle_Fu", "Dylan",
    "Eric", "Ryan", "Aiden", "Ono_Anna", "Sohee",
]

# OpenAI voice name → Qwen3 voice name
QWEN3_VOICE_MAP = {
    "alloy": "Serena",
    "echo": "Dylan",
    "fable": "Vivian",
    "onyx": "Uncle_Fu",
    "nova": "Ono_Anna",
    "shimmer": "Sohee",
}

# Edge-TTS 中文声音
EDGE_VOICES = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",
    "xiaoyi": "zh-CN-XiaoyiNeural",
    "yunjian": "zh-CN-YunjianNeural",
    "yunxi": "zh-CN-YunxiNeural",
    "yunxia": "zh-CN-YunxiaNeural",
    "yunyang": "zh-CN-YunyangNeural",
}

# OpenAI voice → Edge-TTS voice (auto-select by language)
EDGE_VOICE_MAP = {
    "alloy": {"zh": "zh-CN-XiaoxiaoNeural", "en": "en-US-AriaNeural"},
    "echo": {"zh": "zh-CN-YunxiNeural", "en": "en-US-GuyNeural"},
    "fable": {"zh": "zh-CN-XiaoyiNeural", "en": "en-US-JennyNeural"},
    "onyx": {"zh": "zh-CN-YunjianNeural", "en": "en-US-DavisNeural"},
    "nova": {"zh": "zh-CN-XiaoxiaoNeural", "en": "en-US-AriaNeural"},
    "shimmer": {"zh": "zh-CN-XiaoyiNeural", "en": "en-US-JennyNeural"},
    # Qwen3 voice names → Edge defaults
    "serena": {"zh": "zh-CN-XiaoxiaoNeural", "en": "en-US-AriaNeural"},
    "dylan": {"zh": "zh-CN-YunxiNeural", "en": "en-US-GuyNeural"},
    "vivian": {"zh": "zh-CN-XiaoyiNeural", "en": "en-US-JennyNeural"},
}

# CosyVoice3 预置声音 (SFT模式)
COSYVOICE3_VOICES = ["中文女", "中文男", "日语男", "粤语女", "英文女", "英文男", "韩语女"]

COSYVOICE3_VOICE_MAP = {
    "alloy": "中文女",
    "echo": "中文男",
    "fable": "英文女",
    "onyx": "中文男",
    "nova": "中文女",
    "shimmer": "英文女",
    "serena": "中文女",
    "dylan": "中文男",
}

# ---------------------------------------------------------------------------
# Language utilities
# ---------------------------------------------------------------------------

LANG_CODE_MAP = {
    "zh": "Chinese", "cn": "Chinese", "chinese": "Chinese",
    "en": "English", "english": "English",
    "ja": "Japanese", "japanese": "Japanese",
    "ko": "Korean", "korean": "Korean",
    "de": "German", "german": "German",
    "fr": "French", "french": "French",
    "ru": "Russian", "russian": "Russian",
    "pt": "Portuguese", "portuguese": "Portuguese",
    "es": "Spanish", "spanish": "Spanish",
    "it": "Italian", "italian": "Italian",
}


def normalize_language(language: str | None) -> str | None:
    if not language or not language.strip():
        return None
    lang = language.strip()
    mapped = LANG_CODE_MAP.get(lang.lower())
    if mapped:
        return mapped
    capitalized = lang.capitalize()
    if capitalized in LANG_CODE_MAP.values():
        return capitalized
    return None


def detect_language(text: str) -> str:
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if chinese_chars > len(text) * 0.1:
        return "Chinese"
    return "English"


def lang_to_short(lang: str) -> str:
    """Chinese → zh, English → en, etc."""
    rev = {v: k for k, v in LANG_CODE_MAP.items() if len(k) == 2}
    return rev.get(lang, "zh")

# ---------------------------------------------------------------------------
# Voice resolution per backend
# ---------------------------------------------------------------------------

def resolve_qwen3_voice(voice: str) -> str:
    mapped = QWEN3_VOICE_MAP.get(voice.lower())
    if mapped:
        return mapped
    for v in QWEN3_VOICES:
        if v.lower() == voice.lower():
            return v
    return "Serena"


def resolve_edge_voice(voice: str, lang: str) -> str:
    short_lang = lang_to_short(lang)
    # Direct edge voice name
    if voice.lower() in EDGE_VOICES:
        return EDGE_VOICES[voice.lower()]
    # Full edge voice name (e.g., zh-CN-XiaoxiaoNeural)
    if "Neural" in voice:
        return voice
    # Map from OpenAI/Qwen3 voice names
    lang_map = EDGE_VOICE_MAP.get(voice.lower())
    if lang_map:
        return lang_map.get(short_lang, lang_map.get("zh", "zh-CN-XiaoxiaoNeural"))
    return "zh-CN-XiaoxiaoNeural"


def resolve_cosyvoice3_voice(voice: str) -> str:
    mapped = COSYVOICE3_VOICE_MAP.get(voice.lower())
    if mapped:
        return mapped
    if voice in COSYVOICE3_VOICES:
        return voice
    return "中文女"

# ---------------------------------------------------------------------------
# Audio encoding
# ---------------------------------------------------------------------------

def encode_audio(samples: np.ndarray, sr: int, fmt: str, tmp_dir: str) -> tuple[str, str]:
    """Encode audio samples to a temp file. Returns (file_path, media_type)."""
    if fmt == "mp3":
        wav_buf = io.BytesIO()
        sf.write(wav_buf, samples, sr, format="WAV")
        wav_buf.seek(0)
        seg = AudioSegment.from_wav(wav_buf)
        tmp_path = os.path.join(tmp_dir, f"tts_{int(time.time()*1000)}.mp3")
        seg.export(tmp_path, format="mp3", bitrate="192k")
        return tmp_path, "audio/mpeg"
    elif fmt == "flac":
        tmp_path = os.path.join(tmp_dir, f"tts_{int(time.time()*1000)}.flac")
        sf.write(tmp_path, samples, sr, format="FLAC")
        return tmp_path, "audio/flac"
    else:
        tmp_path = os.path.join(tmp_dir, f"tts_{int(time.time()*1000)}.wav")
        sf.write(tmp_path, samples, sr, format="WAV")
        return tmp_path, "audio/wav"

# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------

def load_qwen3_model(model_path: str):
    from qwen_tts import Qwen3TTSModel
    logger.info(f"Loading Qwen3-TTS from {model_path}...")
    start = time.time()
    model = Qwen3TTSModel.from_pretrained(
        model_path, device_map="cuda:0", dtype=torch.bfloat16,
    )
    logger.info(f"Qwen3-TTS loaded in {time.time() - start:.1f}s")
    return model


def load_cosyvoice3_model(model_path: str):
    # Add CosyVoice source to path
    cv_root = os.path.expanduser("~/exps/CosyVoice")
    for p in [cv_root, os.path.join(cv_root, "third_party/Matcha-TTS")]:
        if p not in sys.path:
            sys.path.insert(0, p)

    from cosyvoice.cli.cosyvoice import CosyVoice3
    logger.info(f"Loading CosyVoice3 from {model_path}...")
    start = time.time()
    model = CosyVoice3(
        model_path,
        fp16=torch.cuda.is_available(),
    )
    logger.info(f"CosyVoice3 loaded in {time.time() - start:.1f}s, "
                f"sample_rate={model.sample_rate}")
    return model

# ---------------------------------------------------------------------------
# Synthesis backends
# ---------------------------------------------------------------------------

async def synthesize_qwen3(text: str, voice: str, lang: str, instruct: str, speed: float):
    """Returns (samples, sample_rate)."""
    v = resolve_qwen3_voice(voice)
    wavs, sr = await asyncio.to_thread(
        qwen3_model.generate_custom_voice,
        text=text, language=lang, speaker=v, instruct=instruct,
    )
    return wavs[0], sr


async def synthesize_edge_tts(text: str, voice: str, lang: str, tmp_dir: str) -> tuple[str, str]:
    """Returns (mp3_file_path, media_type) directly — no PCM step."""
    import edge_tts
    v = resolve_edge_voice(voice, lang)
    tmp_path = os.path.join(tmp_dir, f"tts_{int(time.time()*1000)}_edge.mp3")
    communicate = edge_tts.Communicate(text, v)
    await communicate.save(tmp_path)
    return tmp_path, "audio/mpeg"


COSYVOICE3_PROMPT_WAV = os.path.expanduser("~/exps/CosyVoice/asset/zero_shot_prompt.wav")
COSYVOICE3_DEFAULT_INSTRUCT = "You are a helpful assistant.<|endofprompt|>"


async def synthesize_cosyvoice3(text: str, voice: str, lang: str, instruct: str, speed: float):
    """Returns (samples, sample_rate). Uses instruct2 mode with reference audio."""
    # Build instruct with required <|endofprompt|> token
    if instruct:
        inst = f"You are a helpful assistant. {instruct}<|endofprompt|>"
    else:
        inst = COSYVOICE3_DEFAULT_INSTRUCT

    def _generate():
        gen = cosyvoice3_model.inference_instruct2(
            text, inst, COSYVOICE3_PROMPT_WAV,
            stream=False, speed=speed,
        )
        result = next(gen)
        return result["tts_speech"].numpy().squeeze(), cosyvoice3_model.sample_rate

    samples, sr = await asyncio.to_thread(_generate)
    return samples, sr

# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------

class SpeechRequest(BaseModel):
    model: str = "qwen3-tts"
    input: str
    voice: str = "Serena"
    response_format: str = "mp3"
    speed: float = 1.0
    language: str | None = None
    instruct: str | None = None

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

SUPPORTED_MODELS = ["qwen3-tts", "edge-tts", "cosyvoice3"]

def create_app(
    qwen3_model_path: str,
    cosyvoice3_model_path: str | None,
    default_voice: str,
    default_instruct: str | None,
) -> FastAPI:

    tmp_dir = tempfile.mkdtemp(prefix="tts_audio_")
    logger.info(f"Audio temp dir: {tmp_dir}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        global qwen3_model, cosyvoice3_model

        # Load Qwen3-TTS
        qwen3_model = load_qwen3_model(qwen3_model_path)

        # Load CosyVoice3 (optional)
        if cosyvoice3_model_path and os.path.exists(cosyvoice3_model_path):
            try:
                cosyvoice3_model = load_cosyvoice3_model(cosyvoice3_model_path)
            except Exception as e:
                logger.warning(f"CosyVoice3 load failed: {e}. Backend disabled.")
                cosyvoice3_model = None
        else:
            logger.info("CosyVoice3 model not found, backend disabled.")

        logger.info(f"Server ready. Default voice: {default_voice}")
        avail = ["qwen3-tts", "edge-tts"]
        if cosyvoice3_model:
            avail.append("cosyvoice3")
        logger.info(f"Available backends: {avail}")
        yield
        # Cleanup temp files
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
        logger.info("Shutting down...")

    app = FastAPI(
        title="Qwen3-TTS Server",
        description="Multi-backend OpenAI TTS API compatible server",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Generation-Time"],
    )

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get("/v1/models")
    async def list_models():
        models = [
            {"id": "qwen3-tts", "object": "model", "created": 1700000000, "owned_by": "qwen"},
            {"id": "edge-tts", "object": "model", "created": 1700000000, "owned_by": "microsoft"},
        ]
        if cosyvoice3_model:
            models.append({"id": "cosyvoice3", "object": "model", "created": 1700000000, "owned_by": "alibaba"})
        return {"object": "list", "data": models}

    @app.post("/v1/audio/speech")
    async def synthesize(request: SpeechRequest, raw_request: Request):
        global _log_id_counter
        start = time.time()
        voice = request.voice or default_voice
        lang = normalize_language(request.language) or detect_language(request.input)
        instruct = request.instruct or default_instruct or ""
        fmt = request.response_format.lower()
        backend = request.model.lower().strip()
        client_ip = raw_request.client.host if raw_request.client else "unknown"

        logger.info(
            f"TTS [{backend}] voice={voice}, lang={lang}, "
            f"fmt={fmt}, text_len={len(request.input)}"
        )

        try:
            if backend == "edge-tts":
                # edge-tts outputs MP3 directly — no PCM intermediary
                file_path, media_type = await synthesize_edge_tts(
                    request.input, voice, lang, tmp_dir,
                )
            elif backend in ("cosyvoice3", "cosyvoice2"):
                if cosyvoice3_model is None:
                    _log_id_counter += 1
                    _request_logs.append({
                        "id": _log_id_counter,
                        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "backend": backend, "voice": voice, "lang": lang,
                        "text": request.input[:100],
                        "text_len": len(request.input),
                        "status": "error", "error": "CosyVoice3 backend not available",
                        "elapsed": 0, "size": 0, "client": client_ip,
                    })
                    return JSONResponse(
                        status_code=400,
                        content={"error": "CosyVoice3 backend not available"},
                    )
                samples, sr = await synthesize_cosyvoice3(
                    request.input, voice, lang, instruct, request.speed,
                )
                file_path, media_type = encode_audio(samples, sr, fmt, tmp_dir)
            else:
                # Default: qwen3-tts
                samples, sr = await synthesize_qwen3(
                    request.input, voice, lang, instruct, request.speed,
                )
                file_path, media_type = encode_audio(samples, sr, fmt, tmp_dir)

        except Exception as e:
            elapsed_err = time.time() - start
            logger.error(f"TTS synthesis failed: {e}", exc_info=True)
            _log_id_counter += 1
            _request_logs.append({
                "id": _log_id_counter,
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "backend": backend, "voice": voice, "lang": lang,
                "text": request.input[:100],
                "text_len": len(request.input),
                "status": "error", "error": str(e)[:200],
                "elapsed": round(elapsed_err, 2), "size": 0, "client": client_ip,
            })
            return JSONResponse(
                status_code=500,
                content={"error": f"Synthesis failed: {str(e)}"},
            )

        elapsed = time.time() - start
        file_size = os.path.getsize(file_path)
        logger.info(f"TTS [{backend}] completed in {elapsed:.2f}s, "
                     f"file={file_size} bytes")

        # Record to request log
        _log_id_counter += 1
        _request_logs.append({
            "id": _log_id_counter,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "backend": backend, "voice": voice, "lang": lang,
            "text": request.input[:100],
            "text_len": len(request.input),
            "status": "ok",
            "elapsed": round(elapsed, 2),
            "size": file_size,
            "client": client_ip,
        })

        def cleanup():
            try:
                os.unlink(file_path)
            except OSError:
                pass

        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=f"speech.{fmt if fmt != 'mp3' else 'mp3'}",
            headers={"X-Generation-Time": f"{elapsed:.2f}s"},
            background=BackgroundTask(cleanup),
        )

    @app.get("/v1")
    async def v1_root():
        return await list_models()

    @app.get("/v1/voices")
    async def list_voices():
        result = {
            "qwen3-tts": {
                "voices": QWEN3_VOICES,
                "default": default_voice,
                "openai_mapping": QWEN3_VOICE_MAP,
            },
            "edge-tts": {
                "voices": list(EDGE_VOICES.keys()),
                "voices_full": EDGE_VOICES,
                "openai_mapping": {k: v.get("zh", "") for k, v in EDGE_VOICE_MAP.items()},
            },
        }
        if cosyvoice3_model:
            result["cosyvoice3"] = {
                "voices": COSYVOICE3_VOICES,
                "openai_mapping": COSYVOICE3_VOICE_MAP,
            }
        return result

    @app.get("/v1/logs")
    async def get_logs(since_id: int = 0, limit: int = 50):
        """返回最近的请求日志，支持增量拉取。"""
        logs = [e for e in _request_logs if e["id"] > since_id]
        return {"logs": logs[-limit:], "total": len(_request_logs)}

    @app.get("/health")
    async def health():
        backends = {"qwen3-tts": "ok", "edge-tts": "ok"}
        if cosyvoice3_model:
            backends["cosyvoice3"] = "ok"
        return {
            "status": "ok",
            "backends": backends,
            "default_voice": default_voice,
        }

    @app.get("/")
    async def root():
        return {
            "service": "Qwen3-TTS Multi-Backend Server",
            "version": "2.0.0",
            "endpoints": {
                "speech": "POST /v1/audio/speech",
                "voices": "GET /v1/voices",
                "models": "GET /v1/models",
                "health": "GET /health",
            },
        }

    return app


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Qwen3-TTS Multi-Backend Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=58201)
    parser.add_argument(
        "--model",
        default=os.path.expanduser("~/exps/models/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
        help="Qwen3-TTS model path",
    )
    parser.add_argument(
        "--cosyvoice3-model",
        default=os.path.expanduser("~/exps/models/CosyVoice3-0.5B"),
        help="CosyVoice3 model path (optional)",
    )
    parser.add_argument("--voice", default="Serena", help="Default voice")
    parser.add_argument("--instruct", default=None, help="Default style instruction")
    args = parser.parse_args()

    app = create_app(
        qwen3_model_path=args.model,
        cosyvoice3_model_path=getattr(args, 'cosyvoice3_model'),
        default_voice=args.voice,
        default_instruct=args.instruct,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
