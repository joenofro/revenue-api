#!/usr/bin/env python3
"""Initialize the SQLite database with required tables for the Revenue API."""

import sqlite3
import os

BRAIN_DB = os.environ.get("BRAIN_DB_PATH", os.path.expanduser("~/clawd/data/aidan_brain.db"))

def init_db():
    os.makedirs(os.path.dirname(BRAIN_DB), exist_ok=True)
    conn = sqlite3.connect(BRAIN_DB)
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT UNIQUE NOT NULL,
            tier TEXT NOT NULL DEFAULT 'free',
            customer_email TEXT,
            daily_limit INTEGER DEFAULT 100,
            monthly_limit INTEGER DEFAULT 3000,
            subscription_status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS api_usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT,
            endpoint TEXT,
            response_time_ms INTEGER,
            status_code INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            progress_pct REAL DEFAULT 0.0,
            status TEXT DEFAULT 'active',
            category TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS learning_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            lesson TEXT,
            category TEXT,
            confidence REAL DEFAULT 0.5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS procedures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_type TEXT,
            strategy TEXT,
            tools_sequence TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            tasks_completed INTEGER DEFAULT 0,
            tasks_failed INTEGER DEFAULT 0,
            exec_allowed INTEGER DEFAULT 0,
            exec_blocked INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER,
            description TEXT,
            status TEXT DEFAULT 'pending',
            priority INTEGER DEFAULT 0,
            result TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS self_model (
            attribute TEXT PRIMARY KEY,
            value TEXT,
            confidence REAL DEFAULT 0.5
        );

        CREATE TABLE IF NOT EXISTS revenue_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            amount REAL,
            currency TEXT DEFAULT 'GBP',
            date TEXT DEFAULT (date('now')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS revenue_streams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            monthly_revenue REAL DEFAULT 0.0,
            potential_monthly REAL NOT NULL,
            growth_rate REAL DEFAULT 0.0,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS dashboard_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_email TEXT,
            price_id TEXT,
            stripe_session_id TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS polymarket_markets (
            id TEXT PRIMARY KEY,
            question TEXT,
            category TEXT,
            volume24h REAL DEFAULT 0,
            active INTEGER DEFAULT 1,
            outcomes TEXT,
            raw_data TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS price_monitor_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_url TEXT NOT NULL,
            email TEXT NOT NULL,
            interval_hours INTEGER DEFAULT 24,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    conn.close()
    print(f"Database initialized at {BRAIN_DB}")

if __name__ == "__main__":
    init_db()
