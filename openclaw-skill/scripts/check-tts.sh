#!/bin/bash
# TTS Server health check and quick test
# Usage: bash check-tts.sh [server_url]

SERVER="${TTS_SERVER_URL:-${1:-http://127.0.0.1:58201}}"

echo "=== TTS Server Health Check ==="
echo "Server: $SERVER"
echo

# Health check
echo "--- Health ---"
health=$(curl -s "$SERVER/health" 2>/dev/null)
if [ $? -ne 0 ]; then
    echo "ERROR: Cannot connect to $SERVER"
    exit 1
fi
echo "$health" | python3 -m json.tool 2>/dev/null || echo "$health"

# Voices
echo
echo "--- Available Voices ---"
curl -s "$SERVER/v1/voices" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for backend, info in data.items():
    voices = info.get('voices', [])
    print(f'  {backend}: {', '.join(voices)}')
" 2>/dev/null

# Quick synthesis test
echo
echo "--- Quick Test (edge-tts) ---"
tmpfile="/tmp/tts_test_$$.mp3"
start=$(date +%s%N)
code=$(curl -s -o "$tmpfile" -w "%{http_code}" -X POST "$SERVER/v1/audio/speech" \
    -H "Content-Type: application/json" \
    -d '{"model":"edge-tts","input":"测试成功","voice":"xiaoxiao"}')
end=$(date +%s%N)
elapsed=$(( (end - start) / 1000000 ))

if [ "$code" = "200" ]; then
    size=$(stat -c%s "$tmpfile" 2>/dev/null || stat -f%z "$tmpfile" 2>/dev/null)
    echo "OK: HTTP $code, ${size} bytes, ${elapsed}ms"
else
    echo "FAIL: HTTP $code"
fi
rm -f "$tmpfile"
