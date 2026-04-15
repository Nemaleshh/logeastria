import urllib.request
import json

KEY = "AIzaSyDQeg2SdYhpxIMwRHbvyJGMu9dus-6U0ZM"
models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.0-flash-lite"]

for model in models:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={KEY}"
    body = json.dumps({"contents": [{"parts": [{"text": "Say OK"}]}]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        r = urllib.request.urlopen(req, timeout=10)
        d = json.loads(r.read())
        text = d["candidates"][0]["content"]["parts"][0]["text"]
        print(f"SUCCESS: {model} -> {text.strip()[:30]}")
        break
    except urllib.error.HTTPError as e:
        err = json.loads(e.read()).get("error", {})
        print(f"FAIL: {model} -> {err.get('status','?')} - {err.get('message','?')[:80]}")
    except Exception as e:
        print(f"FAIL: {model} -> {e}")
