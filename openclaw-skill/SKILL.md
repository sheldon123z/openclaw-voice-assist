---
name: tts-task-notify
description: Automatically announce task completion summaries via TTS (Text-to-Speech). When a task is finished, output a fixed-format summary that triggers voice notification through the companion browser userscript and LAN TTS server.
homepage: https://github.com/sheldon123z/openclaw-voice-assist
allowed-tools: ["bash"]
metadata:
  openclaw:
    emoji: "🔊"
    requires:
      bins: ["curl"]
      env: ["TTS_SERVER_URL"]
    primaryEnv: TTS_SERVER_URL
---

# TTS Task Completion Notification

You are equipped with a voice notification system. A browser userscript monitors your output and automatically plays a voice summary via a TTS server on the local network. You must **intelligently decide** when to trigger it.

## When to Notify (DO notify)

Output a summary ONLY when you performed **real work that took effort**, such as:

- Wrote, modified, or deleted code files
- Ran commands that changed system state (install, deploy, migrate, restart, etc.)
- Completed a multi-step debugging or troubleshooting session
- Finished a research/analysis task the user was waiting on
- Created or updated configuration, documentation, or infrastructure
- Any task where the user likely stepped away and needs a "done" alert

**Rule of thumb**: If you used tools (file edits, bash commands, searches across multiple files), it's worth notifying.

## When NOT to Notify (SKIP the summary)

Do NOT output a summary for:

- Simple Q&A — answering a question, explaining a concept
- Short replies — one or two sentences of conversation
- Clarifying questions — asking the user for more info
- Showing information — listing files, showing status, reading configs
- Partial progress — intermediate steps of a larger task (only notify at the end)
- Opinions or suggestions — recommending approaches without executing them

**Rule of thumb**: If you only *talked* but didn't *do* anything, skip it.

## Summary Format

At the end of your response (after all code, explanations, etc.), output exactly:

【任务完成总结】简短的完成摘要[[END_SUMMARY]]

**The markers MUST be output as raw text, NOT inside a fenced code block.**

## Rules

1. **Content**: 100 characters max, natural spoken Chinese, describe what was done and the result
2. **No code**: Never include code, commands, file paths, or technical jargon in the summary
3. **Spoken style**: Write as if speaking aloud — "已完成" not "done", "三个接口" not "3 APIs"
4. **Frequency**: At most ONE summary per response, only at the very end
5. **Match language**: Use the same language the user is speaking (typically Chinese)

## Good Examples

【任务完成总结】用户认证模块已完成，包括登录、注册和密码重置三个接口，所有测试通过。[[END_SUMMARY]]

【任务完成总结】数据库迁移脚本已执行成功，新增了订单表和支付记录表。[[END_SUMMARY]]

【任务完成总结】前端首页重构完成，加载速度从三秒优化到一点二秒。[[END_SUMMARY]]

【任务完成总结】配置文件已修复，服务重启后运行正常。[[END_SUMMARY]]

## No-Notify Examples (these should NOT have a summary)

- User: "这个函数是干什么的？" → You explain → **No summary**
- User: "帮我看看日志" → You show logs → **No summary**
- User: "用哪个框架好？" → You give recommendation → **No summary**
- User: "继续" → You do step 2 of 5 → **No summary** (wait until all done)

## TTS Health Check

You can verify the TTS server is reachable:

```bash
curl -s "${TTS_SERVER_URL}/health" | head -c 200
```

## Direct TTS Synthesis (Optional)

If the user asks you to speak or read something aloud, you can call the TTS API directly:

```bash
curl -s -X POST "${TTS_SERVER_URL}/v1/audio/speech" \
  -H "Content-Type: application/json" \
  -d "{\"model\": \"edge-tts\", \"input\": \"要朗读的文本\", \"voice\": \"Serena\"}" \
  --output /tmp/tts_output.mp3 && echo "Audio saved to /tmp/tts_output.mp3"
```

Available models: `qwen3-tts` (GPU, highest quality), `edge-tts` (cloud, fastest), `cosyvoice3` (GPU, voice cloning).

## Available Voices

**edge-tts** (recommended for speed): xiaoxiao, xiaoyi, yunjian, yunxi, yunxia, yunyang, Serena (auto-mapped)

**qwen3-tts** (highest quality): Serena, Vivian, Dylan, Eric, Ryan, Aiden, Uncle_Fu, Ono_Anna, Sohee

**cosyvoice3** (voice cloning): 中文女, 中文男, 英文女, 英文男, 日语男, 粤语女, 韩语女

## Setup

This skill requires a companion TTS server running on your LAN. See the [setup guide](https://github.com/sheldon123z/openclaw-voice-assist) for:

1. **TTS Server** — Multi-backend speech synthesis server (port 58201)
2. **Dashboard** — Web management panel (port 8210)
3. **Userscript** — Tampermonkey script that detects summaries and plays audio via Web Audio API

Set the `TTS_SERVER_URL` environment variable to your server address:

```bash
export TTS_SERVER_URL="http://192.168.x.x:58201"
```
