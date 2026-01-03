import os
import time
import httpx
import urllib.parse
import json
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
from collections import defaultdict
import asyncio

# ==== CONFIG ====
RATE_LIMIT = int(os.getenv("RATE_LIMIT", "5"))
RATE_WINDOW = int(os.getenv("RATE_WINDOW", "60"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))  # 5 minutes cache

API_KEY = os.getenv("API_KEY", "fAtAyM17qm9pYmsaPlkAT8tRrDoHICBb2NnxcBPM")
USER_ID = os.getenv("USER_ID", "h2")

BASE_API_URL = "https://utdqxiuahh.execute-api.ap-south-1.amazonaws.com/pro/fetch"

# Rate limiting storage with automatic cleanup
rate_logs: Dict[str, list] = defaultdict(list)
# Simple in-memory cache
response_cache: Dict[str, Dict[str, Any]] = {}
cache_timestamps: Dict[str, float] = {}

# Rate limit cleanup task
async def cleanup_old_logs():
    """Periodically clean up old rate limit logs"""
    while True:
        await asyncio.sleep(RATE_WINDOW * 2)
        now = time.time()
        for ip in list(rate_logs.keys()):
            rate_logs[ip] = [t for t in rate_logs[ip] if (now - t) < RATE_WINDOW]
            if not rate_logs[ip]:
                del rate_logs[ip]

# Cache cleanup task
async def cleanup_old_cache():
    """Periodically clean up expired cache"""
    while True:
        await asyncio.sleep(60)
        now = time.time()
        expired_keys = [
            key for key, timestamp in cache_timestamps.items()
            if (now - timestamp) > CACHE_TTL
        ]
        for key in expired_keys:
            response_cache.pop(key, None)
            cache_timestamps.pop(key, None)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events"""
    # Startup
    cleanup_task1 = asyncio.create_task(cleanup_old_logs())
    cleanup_task2 = asyncio.create_task(cleanup_old_cache())
    
    yield
    
    # Shutdown
    cleanup_task1.cancel()
    cleanup_task2.cancel()
    try:
        await cleanup_task1
        await cleanup_task2
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="HS All Social Downloader API",
    version="2.0",
    description="An improved social media downloader API with rate limiting and caching",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def check_rate_limit(ip: str):
    """Check and enforce rate limiting"""
    now = time.time()
    
    # Clean old requests for this IP
    rate_logs[ip] = [t for t in rate_logs[ip] if (now - t) < RATE_WINDOW]
    
    if len(rate_logs[ip]) >= RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "limit": RATE_LIMIT,
                "window": RATE_WINDOW,
                "retry_after": RATE_WINDOW - int(now - rate_logs[ip][0])
            }
        )
    
    rate_logs[ip].append(now)

def get_cache_key(url: str) -> str:
    """Generate cache key from URL"""
    return urllib.parse.quote(url, safe="")

@app.get("/", response_class=JSONResponse)
async def download(
    request: Request, 
    url: str = None,
    nocache: bool = False
):
    """
    Download media from social media URLs
    
    - **url**: The social media URL to download from (required)
    - **nocache**: Bypass cache if True (optional)
    """
    client_ip = request.client.host
    check_rate_limit(client_ip)
    
    if not url:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Missing required parameter",
                "message": "The 'url' parameter is required"
            }
        )
    
    # Validate URL format
    if not url.startswith(('http://', 'https://')):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Invalid URL format",
                "message": "URL must start with http:// or https://"
            }
        )
    
    # Check cache first (if not bypassed)
    cache_key = get_cache_key(url)
    if not nocache and cache_key in response_cache:
        cache_age = time.time() - cache_timestamps.get(cache_key, 0)
        if cache_age < CACHE_TTL:
            return {
                **response_cache[cache_key],
                "_cache": {
                    "hit": True,
                    "age_seconds": int(cache_age),
                    "ttl_seconds": CACHE_TTL
                }
            }
    
    encoded_url = urllib.parse.quote(url, safe="")
    full_api_url = f"{BASE_API_URL}?url={encoded_url}&user_id={USER_ID}"

    headers = {
        "x-api-key": API_KEY,
        "User-Agent": "okhttp/4.12.0",
        "Accept-Encoding": "gzip",
        "Accept": "application/json"
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            follow_redirects=True
        ) as client:
            response = await client.get(full_api_url, headers=headers)
            response.raise_for_status()
            
            result = response.json()
            
            # Cache the successful response
            response_cache[cache_key] = result
            cache_timestamps[cache_key] = time.time()
            
            # Add cache info to response
            result["_cache"] = {
                "hit": False,
                "stored": True,
                "ttl_seconds": CACHE_TTL
            }
            
            return result
            
    except httpx.ConnectTimeout:
        raise HTTPException(
            status_code=504,
            detail={
                "error": "Gateway Timeout",
                "message": "Connection to external API timed out"
            }
        )
    except httpx.ReadTimeout:
        raise HTTPException(
            status_code=504,
            detail={
                "error": "Gateway Timeout",
                "message": "External API response timed out"
            }
        )
    except httpx.HTTPStatusError as e:
        error_detail = {
            "error": "External API Error",
            "status_code": e.response.status_code,
            "url": url
        }
        
        # Try to get error message from response
        try:
            error_detail["message"] = e.response.json().get("error", str(e))
        except:
            error_detail["message"] = e.response.text or str(e)
        
        raise HTTPException(status_code=502, detail=error_detail)
        
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Bad Gateway",
                "message": f"Failed to connect to external API: {str(e)}"
            }
        )
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "Invalid Response",
                "message": "External API returned invalid JSON"
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Internal Server Error",
                "message": str(e)
            }
        )

@app.get("/ping")
async def ping():
    """Health check endpoint"""
    return {
        "status": "ok",
        "message": "HS Downloader API running perfectly",
        "version": "2.0",
        "timestamp": time.time(),
        "rate_limit": {
            "limit": RATE_LIMIT,
            "window": RATE_WINDOW
        },
        "cache": {
            "enabled": True,
            "ttl_seconds": CACHE_TTL,
            "items": len(response_cache)
        }
    }

@app.get("/stats")
async def stats(request: Request):
    """Get API statistics"""
    now = time.time()
    active_ips = len(rate_logs)
    total_requests = sum(len(logs) for logs in rate_logs.values())
    
    return {
        "rate_limits": {
            "active_ips": active_ips,
            "total_recent_requests": total_requests,
            "limit_per_ip": RATE_LIMIT,
            "window_seconds": RATE_WINDOW
        },
        "cache": {
            "items": len(response_cache),
            "max_age": max(cache_timestamps.values()) if cache_timestamps else 0
        },
        "uptime": {
            "timestamp": now
        }
    }

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom HTTP exception handler"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": "API Error",
            "message": exc.detail if isinstance(exc.detail, str) else exc.detail,
            "status_code": exc.status_code,
            "path": request.url.path
        }
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)