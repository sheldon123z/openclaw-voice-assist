// ==UserScript==
// @name         OpenClaw Task Summary TTS
// @namespace    openclaw-local-tts
// @version      1.1.0
// @description  AI 完成任务后自动语音播报总结（仅最新一条，仅一次）
// @match        http://127.0.0.1:*/*
// @match        http://localhost:*/*
// @match        http://192.168.*:*/*
// @grant        GM_xmlhttpRequest
// @connect      192.168.110.219
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  // ====== 配置 ======
  const TTS_URL   = 'http://192.168.110.219:58201/v1/audio/speech';
  const API_KEY   = 'sk-1234';
  const TTS_MODEL = 'edge-tts';
  const TTS_VOICE = 'Serena';

  const START_MARKER = '【任务完成总结】';
  const END_MARKER   = '[[END_SUMMARY]]';

  const POLL_INTERVAL    = 3000;  // 轮询间隔 (ms)
  const MAX_SUMMARY_LEN  = 150;   // 最大播报字数
  const MIN_SUMMARY_LEN  = 4;     // 最短有效总结
  const DEBUG = true;

  // ====== 状态 ======
  const playedSet  = new Set();   // 已播放过的总结（去重用）
  let   speaking   = false;       // 正在播放中
  let   initialized = false;      // 首次扫描完成

  function log(...args) {
    if (DEBUG) console.log('[TTS]', ...args);
  }

  // ====== 文本处理 ======

  function normalize(text) {
    return (text || '').replace(/\u00A0/g, ' ').replace(/\s+/g, ' ').trim();
  }

  /** 从一段文本中提取所有 START...END 之间的总结 */
  function findAllSummaries(text) {
    const results = [];
    let pos = 0;
    while (true) {
      const s = text.indexOf(START_MARKER, pos);
      if (s === -1) break;
      const after = s + START_MARKER.length;
      const e = text.indexOf(END_MARKER, after);
      if (e === -1) break;                       // 结束标记未出现（可能还在流式中）
      let summary = normalize(text.slice(after, e));
      if (summary.length >= MIN_SUMMARY_LEN && !looksLikeCode(summary)) {
        if (summary.length > MAX_SUMMARY_LEN) {
          summary = summary.slice(0, MAX_SUMMARY_LEN).trim();
        }
        results.push(summary);
      }
      pos = e + END_MARKER.length;
    }
    return results;
  }

  /** 启发式判断：像源码就拒绝 */
  function looksLikeCode(text) {
    return [
      /\/\/\s*@\w+/,             // // @name
      /\/\/\s*==\/?UserScript/,  // ==UserScript==
      /function\s*\(/,
      /=>\s*\{/,
      /const\s+\w+\s*=/,
      /import\s+.*from\s+['"]/,
      /console\.\w+\(/,
    ].some(p => p.test(text));
  }

  // ====== TTS 播放 (Web Audio API — 绕过 CSP) ======

  // 全局 AudioContext，延迟创建（需要用户交互后才能 resume）
  let audioCtx = null;

  function getAudioContext() {
    if (!audioCtx) {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    // 如果被浏览器挂起（autoplay policy），尝试恢复
    if (audioCtx.state === 'suspended') {
      audioCtx.resume().catch(() => {});
    }
    return audioCtx;
  }

  function speak(text) {
    return new Promise((resolve, reject) => {
      log('speak:', text);
      GM_xmlhttpRequest({
        method: 'POST',
        url: TTS_URL,
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${API_KEY}`,
        },
        data: JSON.stringify({ model: TTS_MODEL, voice: TTS_VOICE, input: text }),
        responseType: 'arraybuffer',
        timeout: 120000,
        onload(resp) {
          if (resp.status < 200 || resp.status >= 300) {
            reject(new Error(`HTTP ${resp.status}`)); return;
          }
          const buf = resp.response;
          if (!buf || !buf.byteLength) { reject(new Error('empty')); return; }

          // Web Audio API: 直接从 ArrayBuffer 解码播放，不创建 blob/URL
          const ctx = getAudioContext();
          ctx.decodeAudioData(buf.slice(0),  // slice(0) 创建副本，防止 detached buffer
            (audioBuffer) => {
              const source = ctx.createBufferSource();
              source.buffer = audioBuffer;
              source.connect(ctx.destination);
              source.onended = () => {
                log('playback ended');
                resolve();
              };
              source.start(0);
              log('playing via Web Audio API');
            },
            (err) => {
              reject(new Error('decodeAudioData failed: ' + (err?.message || err)));
            }
          );
        },
        onerror()   { reject(new Error('request failed')); },
        ontimeout() { reject(new Error('timeout')); },
      });
    });
  }

  // ====== 核心轮询 ======

  function poll() {
    const pageText = document.body.innerText || '';
    const summaries = findAllSummaries(pageText);

    // ── 首次运行：把页面上已有的总结全部标记为 "已读" ──
    if (!initialized) {
      for (const s of summaries) playedSet.add(s);
      initialized = true;
      log('init: marked', summaries.length, 'existing summaries as read');
      return;
    }

    if (summaries.length === 0) return;

    // ── 只看最后一条总结 ──
    const latest = summaries[summaries.length - 1];

    if (playedSet.has(latest)) return;   // 已播放过
    if (speaking) return;                // 上一条还在播

    // ── 新总结！播放它 ──
    playedSet.add(latest);
    speaking = true;
    log('new summary detected:', latest);

    speak(latest)
      .then(() => log('playback done'))
      .catch(err => console.error('[TTS] playback error:', err))
      .finally(() => { speaking = false; });
  }

  // ====== 测试按钮 ======

  function addTestButton() {
    const btn = document.createElement('button');
    btn.textContent = 'TTS';
    Object.assign(btn.style, {
      position: 'fixed', right: '16px', bottom: '16px', zIndex: '999999',
      padding: '6px 12px', background: '#111', color: '#fff',
      border: 'none', borderRadius: '8px', cursor: 'pointer',
      fontSize: '13px', opacity: '0.6',
    });
    btn.onclick = async () => {
      try {
        getAudioContext();  // 借用户点击激活 AudioContext
        await speak('测试语音合成');
      } catch (e) { alert('TTS 失败: ' + (e?.message || e)); }
    };
    document.body.appendChild(btn);
  }

  // ====== 启动 ======

  addTestButton();
  setInterval(poll, POLL_INTERVAL);
  // 延迟 1 秒做首次扫描，等页面渲染完毕
  setTimeout(poll, 1000);
  log('v1.1.0 started (Web Audio API), polling every', POLL_INTERVAL, 'ms');
})();
