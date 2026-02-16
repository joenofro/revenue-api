#!/usr/bin/env python3
"""
Migration script for AIDAN Brain API v2.
Adds api_keys table and usage tracking.
"""
import sqlite3
import os
import sys

BRAIN_DB = os.path.expanduser("~/clawd/data/aidan_brain.db")

def migrate():
    conn = sqlite3.connect(BRAIN_DB)
    c = conn.cursor()
    
    # Create api_keys table
    c.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT UNIQUE NOT NULL,
            tier TEXT NOT NULL DEFAULT 'free',
            customer_email TEXT,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            subscription_status TEXT DEFAULT 'active',
            daily_limit INTEGER DEFAULT 100,
            monthly_limit INTEGER DEFAULT 3000,
            requests_today INTEGER DEFAULT 0,
            requests_this_month INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Create index on api_key
    c.execute("CREATE INDEX IF NOT EXISTS idx_api_key ON api_keys (api_key)")
    
    # Create usage_log table for detailed tracking
    c.execute("""
        CREATE TABLE IF NOT EXISTS api_usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            response_time_ms INTEGER,
            status_code INTEGER
        )
    """)
    
    # Insert default free tier demo key (if not exists)
    c.execute("SELECT COUNT(*) FROM api_keys WHERE api_key = 'demo-free-key'")
    if c.fetchone()[0] == 0:
        c.execute("""
            INSERT INTO api_keys (api_key, tier, customer_email, daily_limit, monthly_limit)
            VALUES ('demo-free-key', 'free', 'demo@example.com', 100, 3000)
        """)
    
    conn.commit()
    conn.close()
    print("Migration completed successfully.")

if __name__ == "__main__":
    migrate()