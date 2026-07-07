import os
import time
import uuid
import yaml
import jwt
from typing import List, Optional
from collections import defaultdict, deque
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException, Response, Query, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import dotenv_values

app = FastAPI()

# ==========================================
# GLOBALS FOR Q5 (Metrics & Logs)
# ==========================================
START_TIME = time.time()
REQUEST_COUNT = 0
LOGS = deque(maxlen=1000)

# ==========================================
# CONSTANTS & CONFIGURATION
# ==========================================
ALLOWED_ORIGIN = "https://dash-p3az65.example.com"
ISSUER = "https://idp.exam.local"
AUDIENCE = "tds-oimesr4m.apps.exam.local"

# REPLACE THIS WITH YOUR ACTUAL PUBLIC KEY 
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA2okOHspNjgA+2rTLbeuY
cxiP/hG8C6Sb9iwg3yiLAA4HCnpITcbWCSelbvbYGuc3EbNy4xFyf5Cbj5DHJMID
EkryOgyd2giIIIBOUBj8S63uGcnRpOBh9NFatfNwheKuzsPuVNldu6A9cNteNpXc
WyJjG2axVfmq7i6SuKr1JoWYG7xTTAvKPujSl4OtsQfO3h5NepzdfXpr28oNnzfW
ed+zclR6BcmNNo/WVfJ4xyCLSf0BCOgdTgW6PdaChd1l9VDetJZVEgC5tkyvXsfI
SI6iyrYbKR0NEBSqq4XkadEjsCs4F1RncsS4LlgniT7GlkL9Mce3b0wGLs9/7ZIX
dQIDAQAB
-----END PUBLIC KEY-----"""

# ==========================================
# UNIFIED MIDDLEWARE (CORS + Tracking)
# ==========================================
@app.middleware("http")
async def unified_middleware(request: Request, call_next):
    global REQUEST_COUNT
    REQUEST_COUNT += 1
    
    start_time = time.perf_counter()
    request_id = str(uuid.uuid4())
    origin = request.headers.get("origin")
    
    # 1. Store Structured Log Entry
    log_entry = {
        "level": "INFO",
        "ts": datetime.now(timezone.utc).isoformat(),
        "path": request.url.path,
        "request_id": request_id
    }
    LOGS.append(log_entry)
    
    # 2. Open CORS for new endpoints
    open_endpoints = ("/effective-config", "/analytics", "/work", "/metrics", "/healthz", "/logs")
    is_open_endpoint = request.url.path.startswith(open_endpoints)
    
    if request.method == "OPTIONS":
        response = Response(status_code=200)
        if is_open_endpoint:
            response.headers["Access-Control-Allow-Origin"] = origin if origin else "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            req_headers = request.headers.get("Access-Control-Request-Headers", "Content-Type, Authorization, Accept, X-API-Key")
            response.headers["Access-Control-Allow-Headers"] = req_headers
            response.headers["Access-Control-Allow-Credentials"] = "true"
        elif origin == ALLOWED_ORIGIN:
            response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS" 
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, Accept"
            
        process_time = time.perf_counter() - start_time
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = f"{process_time:.6f}"
        return response

    try:
        response = await call_next(request)
    except Exception as e:
        response = JSONResponse(status_code=500, content={"detail": str(e)})

    if is_open_endpoint:
        response.headers["Access-Control-Allow-Origin"] = origin if origin else "*"
        response.headers["Access-Control-Allow-Credentials"] = "true"
    elif origin == ALLOWED_ORIGIN:
        response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN

    process_time = time.perf_counter() - start_time
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{process_time:.6f}"
    
    return response


# ==========================================
# EARLIER ENDPOINTS (Stats, Verify, Config, Analytics)
# ==========================================
@app.get("/stats")
def compute_stats(values: str):
    try:
        nums = [int(x.strip()) for x in values.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="Values must be comma-separated integers.")
    count = len(nums)
    if count == 0:
        raise HTTPException(status_code=400, detail="No values provided.")
    total_sum = sum(nums)
    return {
        "email": "24f3003222@ds.study.iitm.ac.in",
        "count": count, "sum": total_sum,
        "min": min(nums), "max": max(nums), "mean": total_sum / count
    }

class TokenRequest(BaseModel):
    token: str

@app.post("/verify")
def verify_token(request: TokenRequest):
    try:
        payload = jwt.decode(
            request.token, PUBLIC_KEY, algorithms=["RS256"], audience=AUDIENCE, issuer=ISSUER
        )
        return {"valid": True, "email": payload.get("email"), "sub": payload.get("sub"), "aud": payload.get("aud")}
    except jwt.PyJWTError:
        return JSONResponse(status_code=401, content={"valid": False})

def coerce_value(key: str, value: any):
    if key in ["port", "workers"]: return int(value)
    if key == "debug":
        if isinstance(value, bool): return value
        return str(value).lower() in ["true", "1", "yes", "on"]
    return str(value)

@app.get("/effective-config")
def get_effective_config(set: List[str] = Query(default=[])):
    config = {"port": 8000, "workers": 1, "debug": False, "log_level": "info", "api_key": "default-secret-000"}
    try:
        with open("config.development.yaml", "r") as f:
            yaml_config = yaml.safe_load(f) or {}
            for k, v in yaml_config.items(): config[k] = coerce_value(k, v)
    except Exception: pass
    def process_env_var(key_name, val, target_config):
        if key_name == "NUM_WORKERS": target_config["workers"] = coerce_value("workers", val)
        elif key_name.startswith("APP_"):
            mapped_key = key_name[4:].lower()
            target_config[mapped_key] = coerce_value(mapped_key, val)
    env_config = dotenv_values(".env")
    for k, v in env_config.items(): process_env_var(k, v, config)
    os.environ["APP_DEBUG"] = "false"
    for k, v in os.environ.items():
        if k == "NUM_WORKERS" or k.startswith("APP_"): process_env_var(k, v, config)
    for override in set:
        if "=" in override:
            k, v = override.split("=", 1)
            config[k] = coerce_value(k, v)
    if "api_key" in config: config["api_key"] = "****"
    return config

class Event(BaseModel):
    user: str
    amount: float
    ts: int

class AnalyticsPayload(BaseModel):
    events: List[Event]

@app.post("/analytics")
def process_analytics(payload: AnalyticsPayload, x_api_key: Optional[str] = Header(None)):
    if x_api_key != "ak_62cy6l6i2cg5katg3mos1gmu":
        raise HTTPException(status_code=401, detail="Unauthorized")
    events = payload.events
    unique_users = set()
    user_revenue = defaultdict(float)
    revenue = 0.0
    for event in events:
        unique_users.add(event.user)
        if event.amount > 0:
            revenue += event.amount
            user_revenue[event.user] += event.amount
    top_user = max(user_revenue, key=user_revenue.get) if user_revenue else ""
    return {
        "email": "24f3003222@ds.study.iitm.ac.in",
        "total_events": len(events), "unique_users": len(unique_users),
        "revenue": revenue, "top_user": top_user
    }


# ==========================================
# FINAL CHALLENGE ENDPOINTS (Metrics & Logs)
# ==========================================
@app.get("/work")
def do_work(n: int = Query(default=0)):
    return {"email": "24f3003222@ds.study.iitm.ac.in", "done": n}

@app.get("/metrics")
def get_metrics():
    # Format required by Prometheus text specification
    text = f"# HELP http_requests_total Total number of HTTP requests\n# TYPE http_requests_total counter\nhttp_requests_total {REQUEST_COUNT}\n"
    return Response(content=text, media_type="text/plain")

@app.get("/healthz")
def health_check():
    uptime = time.time() - START_TIME
    return {"status": "ok", "uptime_s": uptime}

@app.get("/logs/tail")
def get_logs(limit: int = Query(default=10)):
    # Convert our rolling deque to a standard list and return the requested number
    all_logs = list(LOGS)
    return all_logs[-limit:] if limit > 0 else all_logs
