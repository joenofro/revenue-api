#!/usr/bin/env python3
"""
AIDAN Brain API — AI Memory & Knowledge Search as a Service
Exposes brain database queries and ChromaDB semantic search via REST API.
Rate-limited: free tier (100 req/day), paid tier (unlimited).
"""

import html
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
import ipaddress
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Header, Request, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("aidan-api")
logging.basicConfig(level=logging.INFO)

BRAIN_DB = os.environ.get("BRAIN_DB_PATH", os.path.expanduser("~/clawd/data/aidan_brain.db"))
CHROMA_PATH = os.environ.get("CHROMA_PATH", os.path.expanduser("~/Desktop/aidan/data/chromadb"))
ADMIN_MASTER_KEY = os.environ.get("ADMIN_MASTER_KEY")
MAX_PDF_SIZE = 10 * 1024 * 1024  # 10 MB

IS_PRODUCTION = os.environ.get("FLY_APP_NAME") is not None

ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "").split(",") if os.environ.get("ALLOWED_ORIGINS") else [
    "https://aidan-revenue-api.fly.dev",
]
# Allow localhost in dev
if not IS_PRODUCTION:
    ALLOWED_ORIGINS.extend(["http://localhost:8100", "http://127.0.0.1:8100"])

# --- Helpers ---

def mask_key(key: str) -> str:
    if key and len(key) > 8:
        return key[:6] + "..." + key[-4:]
    return "***"


def get_db():
    conn = sqlite3.connect(BRAIN_DB, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def get_key_info(api_key: str) -> dict:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT tier, customer_email as name, daily_limit, monthly_limit, subscription_status FROM api_keys WHERE api_key = ? AND subscription_status = 'active'",
            (api_key,)
        ).fetchone()
        if row:
            return {"tier": row["tier"], "name": row["name"], "daily_limit": row["daily_limit"]}
        return None
    finally:
        conn.close()


def check_rate_limit(api_key: str, limit: int) -> bool:
    """Check rate limit using persistent database counts instead of in-memory."""
    today = time.strftime("%Y-%m-%d")
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM api_usage_log WHERE api_key = ? AND date(created_at) = ?",
            (api_key, today)
        ).fetchone()
        count = row[0] if row else 0
        return count < limit
    finally:
        conn.close()


def get_auth(x_api_key: Optional[str]) -> dict:
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    info = get_key_info(x_api_key)
    if not info:
        raise HTTPException(status_code=403, detail="Invalid API key")
    limit = info.get("daily_limit", 100)
    if not check_rate_limit(x_api_key, limit):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    return info


EMAIL_RE = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

VALID_CATEGORIES = {"api", "product", "service", "consulting"}

BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "[::1]", "metadata.google.internal"}


def validate_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if not parsed.hostname:
            return False
        if parsed.hostname in BLOCKED_HOSTS:
            return False
        try:
            ip = ipaddress.ip_address(parsed.hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return False
        except ValueError:
            pass
        return True
    except Exception:
        return False


# --- ChromaDB lazy init ---
_chroma_client = None


def get_chroma():
    global _chroma_client
    if _chroma_client is None:
        try:
            import chromadb
            _chroma_client = chromadb.PersistentClient(path=CHROMA_PATH)
        except Exception:
            return None
    return _chroma_client


# --- Security Headers Middleware ---
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        return response


# --- App ---
app = FastAPI(
    title="AIDAN Brain API",
    description="AI-powered memory and knowledge search.",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT"],
    allow_headers=["X-API-Key", "Content-Type", "Stripe-Signature"],
)

app.mount("/static", StaticFiles(directory="/app/static"), name="static")

# --- API usage logging middleware ---
@app.middleware("http")
async def log_api_usage(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration_ms = int((time.time() - start_time) * 1000)

    api_key = request.headers.get("x-api-key") or request.headers.get("X-API-Key")

    if api_key:
        endpoint = request.url.path
        status_code = response.status_code
        try:
            conn = get_db()
            try:
                conn.execute(
                    "INSERT INTO api_usage_log (api_key, endpoint, response_time_ms, status_code) VALUES (?, ?, ?, ?)",
                    (api_key, endpoint, duration_ms, status_code)
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to log API usage: {e}")

    return response


# --- IP-based rate limiting for registration ---
_registration_attempts = {}  # {ip: [timestamps]}
MAX_REGISTRATIONS_PER_IP = 3
REGISTRATION_WINDOW_SECONDS = 3600  # 1 hour


def check_registration_rate(ip: str) -> bool:
    now = time.time()
    if ip not in _registration_attempts:
        _registration_attempts[ip] = []
    # Clean old entries
    _registration_attempts[ip] = [t for t in _registration_attempts[ip] if now - t < REGISTRATION_WINDOW_SECONDS]
    if len(_registration_attempts[ip]) >= MAX_REGISTRATIONS_PER_IP:
        return False
    _registration_attempts[ip].append(now)
    return True


# --- Models ---
class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Search query text")
    collection: str = Field("aidan_memory", description="ChromaDB collection to search")
    limit: int = Field(5, ge=1, le=20, description="Number of results")


class BrainQueryRequest(BaseModel):
    query_type: str = Field(..., description="Type: goals, learnings, procedures, metrics, tasks, self_model")
    limit: int = Field(10, ge=1, le=50)
    status_filter: Optional[str] = Field(None, max_length=50, description="Filter by status")


class RegistrationRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255, description="Customer email")


class AdminCreateKeyRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=255, description="Customer email")
    tier: str = Field("basic", description="Tier: free, basic, pro")
    daily_limit: Optional[int] = Field(None, ge=1, le=100000, description="Override daily limit")


class PriceMonitorRequest(BaseModel):
    product_url: str = Field(..., max_length=2000, description="URL of product to monitor")
    email: str = Field(..., min_length=5, max_length=255, description="Customer email for alerts")
    interval_hours: int = Field(24, ge=1, le=720, description="Check interval in hours")


class RevenueStream(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Name of the revenue stream")
    category: str = Field(..., max_length=50, description="Category (api, product, service, consulting)")
    monthly_revenue: float = Field(0.0, ge=0, le=1000000, description="Current monthly revenue in GBP")
    potential_monthly: float = Field(..., ge=0, le=1000000, description="Potential monthly revenue in GBP")
    growth_rate: float = Field(0.0, ge=-100, le=10000, description="Monthly growth rate percentage")
    notes: Optional[str] = Field(None, max_length=1000, description="Additional notes")


class RevenueStreamUpdate(BaseModel):
    monthly_revenue: Optional[float] = Field(None, ge=0, le=1000000)
    potential_monthly: Optional[float] = Field(None, ge=0, le=1000000)
    growth_rate: Optional[float] = Field(None, ge=-100, le=10000)
    notes: Optional[str] = Field(None, max_length=1000)


# --- Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def root():
    try:
        with open("static/index.html", "r") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>AIDAN Brain API</h1><p>API is running.</p>")


@app.get("/api")
async def api_info():
    return {
        "service": "AIDAN Brain API",
        "version": "0.2.0",
        "endpoints": {
            "GET /health": "Service health check",
            "GET /brain/status": "Brain database overview (requires API key)",
            "POST /brain/query": "Query structured brain data (requires API key)",
            "POST /search": "Semantic search (requires API key)",
            "POST /api/register": "Register for free API key",
        },
    }


@app.get("/health")
async def health():
    db_ok = os.path.exists(BRAIN_DB)
    return {"status": "healthy" if db_ok else "degraded"}


@app.get("/brain/status")
async def brain_status(x_api_key: Optional[str] = Header(None)):
    auth = get_auth(x_api_key)
    conn = get_db()
    try:
        goals = conn.execute("SELECT COUNT(*) FROM goals WHERE status='active'").fetchone()[0]
        learnings = conn.execute("SELECT COUNT(*) FROM learning_log").fetchone()[0]
        procedures = conn.execute("SELECT COUNT(*) FROM procedures").fetchone()[0]
        tasks_total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        top_goal = conn.execute(
            "SELECT title, progress_pct FROM goals WHERE status='active' ORDER BY priority DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    chroma_count = 0
    client = get_chroma()
    if client:
        try:
            chroma_count = sum(c.count() for c in client.list_collections())
        except Exception:
            pass

    return {
        "active_goals": goals,
        "total_learnings": learnings,
        "procedures": procedures,
        "tasks": tasks_total,
        "top_goal": {"title": top_goal[0], "progress": top_goal[1]} if top_goal else None,
        "vector_memory_entries": chroma_count,
        "tier": auth["tier"],
    }


@app.get("/brain/goals")
async def brain_goals(x_api_key: Optional[str] = Header(None)):
    auth = get_auth(x_api_key)
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, title, priority, progress_pct, status, category FROM goals ORDER BY priority DESC"
        ).fetchall()
    finally:
        conn.close()
    return {"goals": [dict(r) for r in rows]}


@app.get("/brain/learnings")
async def brain_learnings(
    limit: int = 10,
    category: Optional[str] = None,
    x_api_key: Optional[str] = Header(None),
):
    auth = get_auth(x_api_key)
    conn = get_db()
    try:
        if category:
            rows = conn.execute(
                "SELECT id, source, lesson, category, confidence, created_at FROM learning_log WHERE category=? ORDER BY created_at DESC LIMIT ?",
                (category, min(limit, 50)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, source, lesson, category, confidence, created_at FROM learning_log ORDER BY created_at DESC LIMIT ?",
                (min(limit, 50),),
            ).fetchall()
    finally:
        conn.close()
    return {"learnings": [dict(r) for r in rows], "count": len(rows)}


@app.post("/brain/query")
async def brain_query(req: BrainQueryRequest, x_api_key: Optional[str] = Header(None)):
    auth = get_auth(x_api_key)

    tables = {
        "goals": ("goals", "id, title, priority, progress_pct, status, category", "priority DESC"),
        "learnings": ("learning_log", "id, source, lesson, category, confidence, created_at", "created_at DESC"),
        "procedures": ("procedures", "id, task_type, strategy, tools_sequence, created_at", "created_at DESC"),
        "metrics": ("metrics", "date, tasks_completed, tasks_failed, exec_allowed, exec_blocked", "date DESC"),
        "tasks": ("tasks", "id, goal_id, description, status, priority, result, created_at", "created_at DESC"),
        "self_model": ("self_model", "attribute, value, confidence", "attribute"),
    }

    if req.query_type not in tables:
        raise HTTPException(status_code=400, detail=f"Invalid query_type. Use: {list(tables.keys())}")

    table, cols, order = tables[req.query_type]
    sql = f"SELECT {cols} FROM {table}"
    params = []

    if req.status_filter:
        sql += " WHERE status = ?"
        params.append(req.status_filter)

    sql += f" ORDER BY {order} LIMIT ?"
    params.append(req.limit)

    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    return {"query_type": req.query_type, "count": len(rows), "results": [dict(r) for r in rows]}


@app.post("/search")
async def semantic_search(req: SearchRequest, x_api_key: Optional[str] = Header(None)):
    auth = get_auth(x_api_key)

    client = get_chroma()
    if not client:
        raise HTTPException(status_code=503, detail="Search service not available")

    valid_collections = ["aidan_memory", "aidan_procedures", "aidan_reflections"]
    if req.collection not in valid_collections:
        raise HTTPException(status_code=400, detail=f"Invalid collection. Use: {valid_collections}")

    try:
        collection = client.get_collection(req.collection)
        results = collection.query(query_texts=[req.query], n_results=req.limit)
    except Exception as e:
        logger.error(f"ChromaDB search failed: {e}")
        raise HTTPException(status_code=500, detail="Search failed")

    items = []
    if results["documents"] and results["documents"][0]:
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0] if results["metadatas"] else [{}] * len(results["documents"][0]),
            results["distances"][0] if results["distances"] else [0] * len(results["documents"][0]),
        ):
            items.append({"document": doc, "metadata": meta, "distance": dist})

    return {
        "collection": req.collection,
        "query": req.query,
        "count": len(items),
        "results": items,
    }


@app.post("/api/register")
async def register(req: RegistrationRequest, request: Request):
    # Validate email format
    if not EMAIL_RE.match(req.email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    # IP-based rate limit on registration
    client_ip = request.client.host if request.client else "unknown"
    if not check_registration_rate(client_ip):
        raise HTTPException(status_code=429, detail="Too many registrations. Try again later.")

    # Only free tier via self-registration — paid tiers via Stripe webhook only
    tier = "free"
    daily_limit = 100
    monthly_limit = 3000

    api_key = "sk_" + secrets.token_urlsafe(32)
    conn = get_db()
    try:
        # Check if email already has an active key
        existing = conn.execute(
            "SELECT api_key FROM api_keys WHERE customer_email = ? AND subscription_status = 'active' LIMIT 1",
            (req.email,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="An API key already exists for this email. Contact support if you need a new key.")

        conn.execute(
            "INSERT INTO api_keys (api_key, tier, customer_email, daily_limit, monthly_limit, subscription_status, email_sent, email_sent_at) VALUES (?, ?, ?, ?, ?, 'active', 0, NULL)",
            (api_key, tier, req.email, daily_limit, monthly_limit)
        )
        conn.commit()
    except HTTPException:
        raise
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=500, detail="Registration failed. Please try again.")
    finally:
        conn.close()

    logger.info(f"Registered free key {mask_key(api_key)} for {req.email}")
    return {"api_key": api_key, "tier": tier, "daily_limit": daily_limit, "message": "Keep this key secure."}


@app.post("/api/admin/create_key")
async def admin_create_key(req: AdminCreateKeyRequest, x_master_key: Optional[str] = Header(None)):
    # Admin key from environment — endpoint disabled if not configured
    if not ADMIN_MASTER_KEY:
        raise HTTPException(status_code=503, detail="Admin endpoint not configured")
    if not x_master_key or not hmac.compare_digest(x_master_key, ADMIN_MASTER_KEY):
        raise HTTPException(status_code=403, detail="Unauthorized")

    if not EMAIL_RE.match(req.email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    valid_tiers = {"free", "basic", "pro", "revenue_api"}
    if req.tier not in valid_tiers:
        raise HTTPException(status_code=400, detail=f"Invalid tier. Use: {list(valid_tiers)}")

    limits = {"free": 100, "basic": 1000, "pro": 10000, "revenue_api": 5000}
    daily_limit = req.daily_limit if req.daily_limit is not None else limits.get(req.tier, 100)
    monthly_limit = daily_limit * 30

    api_key = "sk_" + secrets.token_urlsafe(32)
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO api_keys (api_key, tier, customer_email, daily_limit, monthly_limit, subscription_status, email_sent, email_sent_at) VALUES (?, ?, ?, ?, ?, 'active', 0, NULL)",
            (api_key, req.tier, req.email, daily_limit, monthly_limit)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=500, detail="Key generation failed. Retry.")
    finally:
        conn.close()

    logger.info(f"Admin created {req.tier} key {mask_key(api_key)} for {req.email}")
    return {"api_key": api_key, "tier": req.tier, "daily_limit": daily_limit}


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    import stripe

    stripe_secret = os.environ.get("STRIPE_SECRET_KEY")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

    if not stripe_secret or not webhook_secret:
        raise HTTPException(status_code=503, detail="Payment processing not configured")

    stripe.api_key = stripe_secret
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_email", "")
        line_items = session.get("line_items", {}).get("data", [])
        price_id = None
        if line_items:
            price_id = line_items[0].get("price", {}).get("id")
        if not price_id:
            price_id = session.get("metadata", {}).get("price_id")

        # Price-to-tier mapping from environment or defaults
        DASHBOARD_PRICE = os.environ.get("STRIPE_DASHBOARD_PRICE", "price_1T1MFxLnWY7IoSqmd8R3pGJV")
        if price_id == DASHBOARD_PRICE:
            conn = get_db()
            try:
                conn.execute(
                    "INSERT INTO dashboard_subscriptions (customer_email, price_id, stripe_session_id, status) VALUES (?, ?, ?, 'active')",
                    (customer_email, price_id, session.get("id"))
                )
                conn.commit()
                logger.info(f"Dashboard subscription created for {customer_email}")
            finally:
                conn.close()
            return {"status": "dashboard_subscription_created"}

        price_to_tier = {
            os.environ.get("STRIPE_BASIC_PRICE", "price_1SzPt7LnWY7IoSqm5YXJEHwy"): "basic",
            os.environ.get("STRIPE_PRO_PRICE", "price_1SzPtMLnWY7IoSqm83uF3GM0"): "pro",
            os.environ.get("STRIPE_REVENUE_PRICE", "price_1T0LN1LnWY7IoSqmOIELPsqF"): "revenue_api",
        }
        tier = price_to_tier.get(price_id, "basic")
        limits = {"basic": 1000, "pro": 10000, "revenue_api": 5000}
        daily_limit = limits.get(tier, 1000)

        api_key = "sk_" + secrets.token_urlsafe(32)
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO api_keys (api_key, tier, customer_email, daily_limit, monthly_limit, subscription_status, email_sent, email_sent_at) VALUES (?, ?, ?, ?, ?, 'active', 0, NULL)",
                (api_key, tier, customer_email, daily_limit, daily_limit * 30)
            )
            conn.commit()
            logger.info(f"Stripe key created for {customer_email} tier {tier}")
        except sqlite3.IntegrityError:
            api_key = "sk_" + secrets.token_urlsafe(32)
            conn.execute(
                "INSERT INTO api_keys (api_key, tier, customer_email, daily_limit, monthly_limit, subscription_status, email_sent, email_sent_at) VALUES (?, ?, ?, ?, ?, 'active', 0, NULL)",
                (api_key, tier, customer_email, daily_limit, daily_limit * 30)
            )
            conn.commit()
        finally:
            conn.close()

    return {"status": "received"}


@app.post("/pdf/extract")
async def pdf_extract(file: UploadFile = File(...), x_api_key: Optional[str] = Header(None)):
    auth = get_auth(x_api_key)

    # Read with size limit
    contents = await file.read(MAX_PDF_SIZE + 1)
    if len(contents) > MAX_PDF_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 10MB)")

    # Validate PDF magic bytes, not client-supplied content-type
    if not contents.startswith(b'%PDF'):
        raise HTTPException(status_code=400, detail="File must be a valid PDF")

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name
    try:
        from pypdf import PdfReader
        reader = PdfReader(tmp_path)
        text = ""
        for page in reader.pages[:100]:  # Cap at 100 pages
            text += page.extract_text() or ""
        return {"filename": file.filename, "pages": len(reader.pages), "text": text[:50000]}  # Cap text output
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        raise HTTPException(status_code=500, detail="PDF extraction failed")
    finally:
        os.unlink(tmp_path)


@app.post("/monitor/price")
async def price_monitor(req: PriceMonitorRequest, x_api_key: Optional[str] = Header(None)):
    auth = get_auth(x_api_key)

    if not EMAIL_RE.match(req.email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    if not validate_url(req.product_url):
        raise HTTPException(status_code=400, detail="Invalid or blocked URL")

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO price_monitor_jobs (product_url, email, interval_hours, status) VALUES (?, ?, ?, 'pending')",
            (req.product_url, req.email, req.interval_hours)
        )
        job_id = cursor.lastrowid
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Price monitor DB error: {e}")
        raise HTTPException(status_code=500, detail="Failed to create monitoring job")
    finally:
        conn.close()
    return {"job_id": job_id, "message": "Price monitoring job created."}


@app.post("/revenue/streams")
async def create_revenue_stream(stream: RevenueStream, x_api_key: Optional[str] = Header(None)):
    auth = get_auth(x_api_key)

    if stream.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Use: {list(VALID_CATEGORIES)}")

    # Sanitize text fields
    safe_name = html.escape(stream.name)
    safe_notes = html.escape(stream.notes) if stream.notes else None

    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO revenue_streams (name, category, monthly_revenue, potential_monthly, growth_rate, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (safe_name, stream.category, stream.monthly_revenue, stream.potential_monthly, stream.growth_rate, safe_notes))
        stream_id = cursor.lastrowid
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Revenue stream DB error: {e}")
        raise HTTPException(status_code=500, detail="Failed to create revenue stream")
    finally:
        conn.close()
    return {"stream_id": stream_id, "message": "Revenue stream created successfully"}


@app.get("/revenue/streams")
async def get_revenue_streams(x_api_key: Optional[str] = Header(None)):
    auth = get_auth(x_api_key)
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM revenue_streams ORDER BY created_at DESC")
        streams = cursor.fetchall()
        return [dict(stream) for stream in streams]
    except sqlite3.Error as e:
        logger.error(f"Revenue streams query error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve revenue streams")
    finally:
        conn.close()


@app.get("/revenue/streams/{stream_id}")
async def get_revenue_stream(stream_id: int, x_api_key: Optional[str] = Header(None)):
    auth = get_auth(x_api_key)
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM revenue_streams WHERE id = ?", (stream_id,))
        stream = cursor.fetchone()
        if not stream:
            raise HTTPException(status_code=404, detail="Revenue stream not found")
        return dict(stream)
    except sqlite3.Error as e:
        logger.error(f"Revenue stream query error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve revenue stream")
    finally:
        conn.close()


@app.put("/revenue/streams/{stream_id}")
async def update_revenue_stream(stream_id: int, update: RevenueStreamUpdate, x_api_key: Optional[str] = Header(None)):
    auth = get_auth(x_api_key)
    conn = get_db()
    try:
        cursor = conn.cursor()
        updates = []
        params = []
        if update.monthly_revenue is not None:
            updates.append("monthly_revenue = ?")
            params.append(update.monthly_revenue)
        if update.potential_monthly is not None:
            updates.append("potential_monthly = ?")
            params.append(update.potential_monthly)
        if update.growth_rate is not None:
            updates.append("growth_rate = ?")
            params.append(update.growth_rate)
        if update.notes is not None:
            updates.append("notes = ?")
            params.append(html.escape(update.notes))

        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        updates.append("updated_at = CURRENT_TIMESTAMP")
        query = f"UPDATE revenue_streams SET {', '.join(updates)} WHERE id = ?"
        params.append(stream_id)

        cursor.execute(query, params)
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Revenue stream not found")
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Revenue stream update error: {e}")
        raise HTTPException(status_code=500, detail="Failed to update revenue stream")
    finally:
        conn.close()
    return {"message": "Revenue stream updated successfully"}


@app.get("/revenue/summary")
async def get_revenue_summary(x_api_key: Optional[str] = Header(None)):
    auth = get_auth(x_api_key)
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) as total_streams,
                COALESCE(SUM(monthly_revenue), 0) as total_monthly_revenue,
                COALESCE(SUM(potential_monthly), 0) as total_potential_revenue,
                COALESCE(AVG(growth_rate), 0) as avg_growth_rate
            FROM revenue_streams
        """)
        summary = cursor.fetchone()
        return {
            "total_streams": summary[0],
            "total_monthly_revenue": summary[1],
            "total_potential_revenue": summary[2],
            "avg_growth_rate": summary[3],
            "revenue_gap": summary[2] - summary[1]
        }
    except sqlite3.Error as e:
        logger.error(f"Revenue summary error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve revenue summary")
    finally:
        conn.close()


@app.get("/revenue/transactions")
async def get_revenue_transactions(x_api_key: Optional[str] = Header(None)):
    auth = get_auth(x_api_key)
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(amount) FROM revenue_log")
        count, total = cursor.fetchone()
        if total is None:
            total = 0.0

        cursor.execute("""
            SELECT source, COUNT(*), SUM(amount)
            FROM revenue_log
            GROUP BY source
            ORDER BY SUM(amount) DESC
        """)
        by_source = [
            {"source": row[0], "transactions": row[1], "amount": row[2]}
            for row in cursor.fetchall()
        ]

        from datetime import datetime, timedelta
        thirty_days_ago = (datetime.now() - timedelta(days=30)).date().isoformat()
        cursor.execute("SELECT SUM(amount) FROM revenue_log WHERE date >= ?", (thirty_days_ago,))
        recent_total = cursor.fetchone()[0] or 0.0

        return {
            "total_transactions": count,
            "total_revenue": total,
            "recent_30d_revenue": recent_total,
            "by_source": by_source
        }
    except sqlite3.Error as e:
        logger.error(f"Revenue transactions error: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve transactions")
    finally:
        conn.close()


@app.get("/revenue/dashboard")
async def get_revenue_dashboard(x_api_key: Optional[str] = Header(None)):
    auth = get_auth(x_api_key)

    total_streams = 0
    streams_monthly = 0.0
    streams_potential = 0.0
    transactions_total = 0.0
    conn_brain = get_db()
    try:
        cursor = conn_brain.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='revenue_streams'")
        if cursor.fetchone():
            cursor.execute("""
                SELECT
                    COUNT(*),
                    COALESCE(SUM(monthly_revenue), 0),
                    COALESCE(SUM(potential_monthly), 0)
                FROM revenue_streams
            """)
            streams_row = cursor.fetchone()
            if streams_row:
                total_streams = streams_row[0]
                streams_monthly = streams_row[1]
                streams_potential = streams_row[2]

        cursor.execute("SELECT SUM(amount) FROM revenue_log")
        total_row = cursor.fetchone()
        transactions_total = total_row[0] or 0.0 if total_row else 0.0
    except sqlite3.Error as e:
        logger.warning(f"Revenue dashboard DB error: {e}")
    finally:
        conn_brain.close()

    aggregated_db = os.environ.get("AGGREGATED_DB_PATH", os.path.expanduser("~/clawd/data/revenue_aggregated.db"))
    daily_stripe = 0.0
    daily_usdc = 0.0
    daily_count = 0
    if os.path.exists(aggregated_db):
        conn_agg = sqlite3.connect(aggregated_db, timeout=10)
        try:
            cursor = conn_agg.cursor()
            cursor.execute("SELECT SUM(stripe_gbp), SUM(usdc), COUNT(*) FROM daily_revenue")
            row = cursor.fetchone()
            if row:
                daily_stripe = row[0] or 0.0
                daily_usdc = row[1] or 0.0
                daily_count = row[2] or 0
        except sqlite3.Error:
            pass
        finally:
            conn_agg.close()

    combined_total = streams_monthly + transactions_total + daily_stripe + daily_usdc

    return {
        "revenue_streams": {
            "total_streams": total_streams,
            "monthly_revenue": streams_monthly,
            "potential_monthly": streams_potential,
            "revenue_gap": streams_potential - streams_monthly
        },
        "transactions_total": transactions_total,
        "daily_aggregated": {
            "stripe_gbp": daily_stripe,
            "usdc": daily_usdc,
            "total_gbp": daily_stripe + daily_usdc,
            "days_recorded": daily_count
        },
        "combined_total_revenue": combined_total,
    }


@app.get("/polymarket/markets")
async def get_polymarket_markets(
    limit: int = 50,
    category: Optional[str] = None,
    active_only: bool = True,
    x_api_key: Optional[str] = Header(None),
):
    auth = get_auth(x_api_key)
    conn = get_db()
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM polymarket_markets"
        params = []
        if active_only:
            query += " WHERE active = 1"
        if category:
            if active_only:
                query += " AND category = ?"
            else:
                query += " WHERE category = ?"
            params.append(category)
        query += " ORDER BY volume24h DESC LIMIT ?"
        params.append(min(limit, 100))

        cursor.execute(query, params)
        rows = cursor.fetchall()
        markets = []
        for row in rows:
            market = dict(row)
            if market.get('outcomes'):
                try:
                    market['outcomes'] = json.loads(market['outcomes'])
                except (json.JSONDecodeError, TypeError):
                    market['outcomes'] = []
            if market.get('raw_data'):
                try:
                    market['raw_data'] = json.loads(market['raw_data'])
                except (json.JSONDecodeError, TypeError):
                    market['raw_data'] = {}
            markets.append(market)
        return {"markets": markets, "count": len(markets)}
    finally:
        conn.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8100, log_level="info", reload=True)
