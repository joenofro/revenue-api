#!/usr/bin/env python3
"""
Polymarket API — FastAPI server for Polymarket prediction markets data.
Runs on port 8101 to avoid conflict with main revenue API (8100).
"""

import json
import os
import sqlite3
import datetime
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

BRAIN_DB = os.path.expanduser("~/clawd/data/aidan_brain.db")

app = FastAPI(
    title="Polymarket API",
    description="Prediction markets data for Polymarket analytics dashboard",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS for GitHub Pages and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your GitHub Pages domain
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "service": "Polymarket API",
        "version": "0.1.0",
        "endpoints": {
            "/markets": "GET markets with optional limit, category, active_only",
            "/market/{id}": "GET single market by ID",
        }
    }

@app.get("/markets")
async def get_markets(
    limit: int = 50,
    category: Optional[str] = None,
    active_only: bool = True
):
    """Get Polymarket prediction markets data"""
    conn = sqlite3.connect(BRAIN_DB)
    conn.row_factory = sqlite3.Row
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
        params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        markets = []
        for row in rows:
            market = dict(row)
            # Parse JSON fields
            outcomes = market.get('outcomes')
            if outcomes:
                if isinstance(outcomes, str):
                    try:
                        market['outcomes'] = json.loads(outcomes)
                    except json.JSONDecodeError:
                        market['outcomes'] = []
                # else already parsed
            raw_data = market.get('raw_data')
            if raw_data:
                if isinstance(raw_data, str):
                    try:
                        market['raw_data'] = json.loads(raw_data)
                    except json.JSONDecodeError:
                        market['raw_data'] = {}
            markets.append(market)
        return {
            "markets": markets,
            "count": len(markets),
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "data_updated": markets[0]["updated_at"] if markets else None
        }
    finally:
        conn.close()

@app.get("/market/{market_id}")
async def get_market(market_id: str):
    """Get a single Polymarket market by ID"""
    conn = sqlite3.connect(BRAIN_DB)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM polymarket_markets WHERE id = ?",
            (market_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {"error": "Market not found"}
        market = dict(row)
        # Parse JSON fields
        if market.get('outcomes'):
            try:
                market['outcomes'] = json.loads(market['outcomes'])
            except:
                market['outcomes'] = []
        if market.get('raw_data'):
            try:
                market['raw_data'] = json.loads(market['raw_data'])
            except:
                market['raw_data'] = {}
        return {"market": market}
    finally:
        conn.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8101, log_level="info")