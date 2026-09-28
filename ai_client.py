"""
ai_client.py — Unified AI wrapper (Google Gemini — FREE)
Uses requests directly to call Gemini REST API — no SDK version issues.
Get free key: aistudio.google.com
"""

import os
import json
import re
import time
import requests
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# REST API endpoint — most stable approach
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

MODELS_TO_TRY = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
]

# Global call counter for rate limiting
_last_call_time = 0

def call_ai(prompt: str, max_tokens: int = 2000) -> str:
    """Call Gemini REST API directly — no SDK model version issues."""
    global _last_call_time

    # Enforce minimum 4 seconds between calls (free tier = 15 RPM max)
    elapsed = time.time() - _last_call_time
    if elapsed < 4:
        wait = 4 - elapsed
        time.sleep(wait)
    _last_call_time = time.time()

    if not GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY not set.\n"
            "Get free key: aistudio.google.com\n"
            "Run: set GEMINI_API_KEY=your-key"
        )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": max_tokens,
            "temperature": 0.7
        }
    }

    last_error = None
    for model in MODELS_TO_TRY:
        url = GEMINI_API_URL.format(model=model, key=GEMINI_API_KEY)
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            elif resp.status_code == 404:
                last_error = f"Model {model} not found"
                continue
            elif resp.status_code in (429, 503):
                # Rate limit or server overload — wait and retry
                wait = 20 if resp.status_code == 429 else 10
                print(f"[WAIT] HTTP {resp.status_code} — waiting {wait}s then retrying...")
                time.sleep(wait)
                resp2 = requests.post(url, json=payload, timeout=30)
                if resp2.status_code == 200:
                    data = resp2.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
                last_error = f"HTTP {resp.status_code} persists after retry"
                continue
            else:
                raise Exception(f"API error {resp.status_code}: {resp.text}")
        except requests.RequestException as e:
            last_error = str(e)
            continue

    raise Exception(f"All models failed. Last: {last_error}")


def call_ai_json(prompt: str, max_tokens: int = 2000) -> dict:
    """Call AI and parse JSON response — robust cleaning with retry."""
    for attempt in range(3):
        try:
            raw = call_ai(prompt, max_tokens)
            # Strip markdown fences
            raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            raw = re.sub(r"\s*```$", "", raw).strip()
            # Find first { and last } to extract JSON object
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start != -1 and end > start:
                raw = raw[start:end]
            # Remove control characters that break JSON parsing
            raw = re.sub(r"[\x00-\x1f\x7f]", " ", raw)
            return json.loads(raw)
        except json.JSONDecodeError:
            if attempt < 2:
                print(f"[WAIT] JSON parse failed, retrying ({attempt+1}/3)...")
                time.sleep(3)
                continue
            raise


if __name__ == "__main__":
    print("Testing Gemini connection...")
    if not GEMINI_API_KEY:
        print("[ERR] No API key set. Run: set GEMINI_API_KEY=your-key")
    else:
        try:
            # First list available models
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                print("[OK] Available models:")
                for m in models[:8]:
                    print(f"   - {m['name']}")
            
            result = call_ai("Say exactly this word: CONNECTED")
            print(f"\n[OK] Gemini working! Response: {result}")
        except Exception as e:
            print(f"[ERR] Error: {e}")