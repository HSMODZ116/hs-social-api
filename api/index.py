import os
import time
import httpx
import urllib.parse
from fastapi import FastAPI, Request, HTTPException

# ==== CONFIG ====
RATE_LIMIT = 5
RATE_WINDOW = 60
rate_logs = {}

API_KEY = os.getenv("API_KEY", "fAtAyM17qm9pYmsaPlkAT8tRrDoHICBb2NnxcBPM")
USER_ID = os.getenv("USER_ID", "h2")

BASE_API_URL = "https://utdqxiuahh.execute-api.ap-south-1.amazonaws.com/pro/fetch"

app = FastAPI(title="HS All Social Downloader API", version="1.0")

def check_rate_limit(ip: str):
    now = time.time()
    if ip not in rate_logs:
        rate_logs[ip] = []
    rate_logs[ip] = [t for t in rate_logs[ip] if (now - t) < RATE_WINDOW]
    if len(rate_logs[ip]) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
    rate_logs[ip].append(now)

@app.get("/")
async def download(request: Request, url: str = None):
    client_ip = request.client.host
    check_rate_limit(client_ip)
    
    if not url:
        raise HTTPException(status_code=400, detail="Missing 'url' parameter")

    encoded_url = urllib.parse.quote(url, safe="")
    full_api_url = f"{BASE_API_URL}?url={encoded_url}&user_id={USER_ID}"

    headers = {
        "x-api-key": API_KEY,
        "User-Agent": "okhttp/4.12.0",
        "Accept-Encoding": "gzip"
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(full_api_url, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"External API error: {e.response.text}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

@app.get("/ping")
async def ping():
    return {"status": "ok", "message": "HS Downloader API running perfectly"}