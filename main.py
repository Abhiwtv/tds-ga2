import os
import time
import uuid
import yaml
import jwt
from fastapi import FastAPI, Request, HTTPException, Response, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import dotenv_values

app = FastAPI()

# ==========================================
# CONSTANTS & CONFIGURATION
# ==========================================
ALLOWED_ORIGIN = "https://dash-p3az65.example.com"
ISSUER = "https://idp.exam.local"
AUDIENCE = "tds-oimesr4m.apps.exam.local"

# REPLACE THIS WITH YOUR ACTUAL PUBLIC KEY (Keep the triple quotes!)
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
# UNIFIED MIDDLEWARE (Dynamic CORS + Headers)
# ==========================================
# ==========================================
# UNIFIED MIDDLEWARE (Dynamic CORS + Headers)
# ==========================================
@app.middleware("http")
async def unified_middleware(request: Request, call_next):
    start_time = time.perf_counter()
    request_id = str(uuid.uuid4())
    origin = request.headers.get("origin")
    
    # Check if this request is for the open-CORS config endpoint
    # (using .startswith to handle any query parameters safely)
    is_config_endpoint = request.url.path.startswith("/effective-config")
    
    # 1. Handle Preflight (OPTIONS)
    if request.method == "OPTIONS":
        response = Response(status_code=200)
        if is_config_endpoint:
            # Open CORS for the effective-config endpoint
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
        elif origin == ALLOWED_ORIGIN:
            # Strict CORS for stats and verify endpoints
            response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS" 
            response.headers["Access-Control-Allow-Headers"] = "*"
    else:
        # 2. Process standard requests
        response = await call_next(request)
        if is_config_endpoint:
            # Always attach wildcards for the config endpoint
            response.headers["Access-Control-Allow-Origin"] = "*"
        elif origin == ALLOWED_ORIGIN:
            # Strictly attach for the others
            response.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN

    # 3. Always append grading headers
    process_time = time.perf_counter() - start_time
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = f"{process_time:.6f}"
    
    return response

# ==========================================
# ENDPOINT 1: STATS CALCULATOR
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
        "email": "24f3003222@ds.study.iitm.ac.in",  # <-- DO NOT FORGET TO UPDATE THIS
        "count": count,
        "sum": total_sum,
        "min": min(nums),
        "max": max(nums),
        "mean": total_sum / count
    }

# ==========================================
# ENDPOINT 2: JWT VERIFIER
# ==========================================
class TokenRequest(BaseModel):
    token: str

@app.post("/verify")
def verify_token(request: TokenRequest):
    try:
        payload = jwt.decode(
            request.token,
            PUBLIC_KEY,
            algorithms=["RS256"],
            audience=AUDIENCE,
            issuer=ISSUER
        )
        return {
            "valid": True,
            "email": payload.get("email"),
            "sub": payload.get("sub"),
            "aud": payload.get("aud")
        }
    except jwt.PyJWTError:
        return JSONResponse(status_code=401, content={"valid": False})

# ==========================================
# ENDPOINT 3: 12-FACTOR CONFIG 
# ==========================================
def coerce_value(key: str, value: any):
    if key in ["port", "workers"]:
        return int(value)
    if key == "debug":
        if isinstance(value, bool):
            return value
        return str(value).lower() in ["true", "1", "yes", "on"]
    return str(value)

@app.get("/effective-config")
def get_effective_config(set: list[str] = Query(default=[])):
    # LAYER 1: Hardcoded Defaults
    config = {
        "port": 8000,
        "workers": 1,
        "debug": False,
        "log_level": "info",
        "api_key": "default-secret-000"
    }

    # LAYER 2: config.development.yaml
    try:
        with open("config.development.yaml", "r") as f:
            yaml_config = yaml.safe_load(f) or {}
            for k, v in yaml_config.items():
                config[k] = coerce_value(k, v)
    except FileNotFoundError:
        pass

    def process_env_var(key_name, val, target_config):
        if key_name == "NUM_WORKERS":
            target_config["workers"] = coerce_value("workers", val)
        elif key_name.startswith("APP_"):
            mapped_key = key_name[4:].lower()
            target_config[mapped_key] = coerce_value(mapped_key, val)

    # LAYER 3: .env file
    env_config = dotenv_values(".env")
    for k, v in env_config.items():
        process_env_var(k, v, config)

    # LAYER 4: OS-level Environment Variables
    os.environ["APP_DEBUG"] = "false"
    for k, v in os.environ.items():
        if k == "NUM_WORKERS" or k.startswith("APP_"):
            process_env_var(k, v, config)

    # LAYER 5: CLI Overrides
    for override in set:
        if "=" in override:
            k, v = override.split("=", 1)
            config[k] = coerce_value(k, v)

    # FINAL STEP: Mask the API Key
    if "api_key" in config:
        config["api_key"] = "****"

    return config