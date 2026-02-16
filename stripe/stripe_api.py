#!/usr/bin/env python3
"""
Stripe Monetization API for AIDAN Revenue Streams.
Provides payment intents, product listing, and webhook handling.
"""

import os
import json
import sqlite3
import logging
from typing import Optional

import stripe
from fastapi import FastAPI, HTTPException, Header, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Stripe configuration
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_placeholder")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
STRIPE_CURRENCY = "gbp"

stripe.api_key = STRIPE_SECRET_KEY

# Brain database path
BRAIN_DB = os.path.expanduser("~/clawd/data/aidan_brain.db")

# FastAPI app
app = FastAPI(
    title="AIDAN Stripe Monetization API",
    description="Handle payments for AI services, data products, and subscriptions.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
class CreatePaymentIntentRequest(BaseModel):
    """Request to create a payment intent."""
    amount_pence: int = Field(..., gt=0, description="Amount in pence (e.g., 1000 = £10)")
    description: Optional[str] = "AIDAN AI Service"
    metadata: Optional[dict] = {}
    customer_email: Optional[str] = None

class ProductListing(BaseModel):
    """Product listing."""
    id: str
    name: str
    description: Optional[str]
    amount_pence: int
    currency: str = "gbp"

# Database helpers
def log_payment(payment_intent_id: str, amount_pence: int, currency: str, status: str, metadata: dict):
    """Log payment to brain database."""
    conn = sqlite3.connect(BRAIN_DB)
    try:
        conn.execute("""
            INSERT INTO payments (
                payment_intent_id, amount_pence, currency, status, metadata,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """, (payment_intent_id, amount_pence, currency, status, json.dumps(metadata)))
        conn.commit()
        logger.info(f"Logged payment {payment_intent_id}: {amount_pence} {currency} ({status})")
    except Exception as e:
        logger.error(f"Failed to log payment: {e}")
        # Try creating table if missing
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payment_intent_id TEXT UNIQUE,
                    amount_pence INTEGER,
                    currency TEXT,
                    status TEXT,
                    metadata TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            conn.commit()
            # Retry insert
            conn.execute("""
                INSERT INTO payments (
                    payment_intent_id, amount_pence, currency, status, metadata,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """, (payment_intent_id, amount_pence, currency, status, json.dumps(metadata)))
            conn.commit()
        except Exception as e2:
            logger.error(f"Failed to create payments table: {e2}")
    finally:
        conn.close()

# Routes
@app.get("/")
async def root():
    """Health check."""
    return {"status": "ok", "service": "stripe-monetization", "version": "0.1.0"}

@app.get("/products")
async def list_products():
    """List available products (static for now)."""
    products = [
        ProductListing(
            id="aidan_basic",
            name="AIDAN Basic API Access",
            description="1000 requests/month to AIDAN Brain API",
            amount_pence=1000,
        ),
        ProductListing(
            id="aidan_premium",
            name="AIDAN Premium API Access",
            description="Unlimited requests, priority support",
            amount_pence=5000,
        ),
        ProductListing(
            id="marketplace_listing",
            name="AI Service Marketplace Listing",
            description="List your AI service on AIDAN marketplace for 1 month",
            amount_pence=2000,
        ),
    ]
    return products

@app.post("/create-payment-intent")
async def create_payment_intent(request: CreatePaymentIntentRequest):
    """Create a Stripe PaymentIntent."""
    try:
        # Create PaymentIntent
        intent = stripe.PaymentIntent.create(
            amount=request.amount_pence,
            currency=STRIPE_CURRENCY,
            description=request.description,
            metadata=request.metadata,
            receipt_email=request.customer_email,
        )
        
        # Log to brain DB
        log_payment(
            payment_intent_id=intent.id,
            amount_pence=request.amount_pence,
            currency=STRIPE_CURRENCY,
            status=intent.status,
            metadata=request.metadata
        )
        
        return {
            "client_secret": intent.client_secret,
            "payment_intent_id": intent.id,
            "amount_pence": request.amount_pence,
            "currency": STRIPE_CURRENCY,
            "status": intent.status,
        }
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None),
    background_tasks: BackgroundTasks = None
):
    """Handle Stripe webhook events."""
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
    
    payload = await request.body()
    
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        logger.error(f"Invalid payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid signature: {e}")
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Handle event
    event_type = event["type"]
    data = event["data"]["object"]
    
    logger.info(f"Received Stripe webhook: {event_type}")
    
    if event_type == "payment_intent.succeeded":
        payment_intent = data
        # Update payment status in brain DB
        conn = sqlite3.connect(BRAIN_DB)
        try:
            conn.execute("""
                UPDATE payments SET status = 'succeeded', updated_at = datetime('now')
                WHERE payment_intent_id = ?
            """, (payment_intent["id"],))
            conn.commit()
            logger.info(f"Payment {payment_intent['id']} marked as succeeded")
        except Exception as e:
            logger.error(f"Failed to update payment status: {e}")
        finally:
            conn.close()
        
        # TODO: trigger service activation, email receipt, etc.
        
    elif event_type == "payment_intent.payment_failed":
        payment_intent = data
        conn = sqlite3.connect(BRAIN_DB)
        try:
            conn.execute("""
                UPDATE payments SET status = 'failed', updated_at = datetime('now')
                WHERE payment_intent_id = ?
            """, (payment_intent["id"],))
            conn.commit()
            logger.info(f"Payment {payment_intent['id']} marked as failed")
        except Exception as e:
            logger.error(f"Failed to update payment status: {e}")
        finally:
            conn.close()
    
    return JSONResponse({"received": True})

@app.get("/payment/{payment_intent_id}")
async def get_payment_status(payment_intent_id: str):
    """Retrieve payment status from brain DB."""
    conn = sqlite3.connect(BRAIN_DB)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM payments WHERE payment_intent_id = ?",
            (payment_intent_id,)
        ).fetchone()
        if row:
            return dict(row)
        else:
            raise HTTPException(status_code=404, detail="Payment not found")
    finally:
        conn.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8101, log_level="info")