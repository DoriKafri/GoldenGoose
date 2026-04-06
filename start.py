#!/usr/bin/env python3
"""
Startup script that ensures database persistence across deploys.

For PostgreSQL (recommended):
1. Add a PostgreSQL plugin in Railway dashboard
2. Set DATABASE_URL to the PostgreSQL connection string (Railway does this automatically)
3. On first deploy, this script migrates data from the bundled SQLite seed DB

For SQLite with persistent volume:
1. Set DATABASE_URL=sqlite:////data/venture_engine.db
2. Mount a persistent volume at /data
"""
import os
import shutil
import sys


def migrate_sqlite_to_postgres():
    """One-time migration: copy data from bundled SQLite DB to PostgreSQL."""
    import sqlite3
    import json

    seed_db = os.path.join(os.path.dirname(__file__), "venture_engine.db")
    if not os.path.exists(seed_db):
        print("[start] No seed SQLite DB found, starting fresh")
        return

    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    from sqlalchemy import create_engine, text, inspect
    pg_engine = create_engine(db_url, pool_pre_ping=True)

    # Create all tables first
    from venture_engine.db.models import Base
    Base.metadata.create_all(bind=pg_engine)

    # Check if PostgreSQL already has data (skip migration if so)
    with pg_engine.connect() as conn:
        try:
            result = conn.execute(text("SELECT COUNT(*) FROM news_feed"))
            count = result.scalar()
            if count > 0:
                print(f"[start] PostgreSQL already has {count} news items, skipping migration")
                return
        except Exception:
            pass  # Table might not exist yet, continue with migration

    # Read from SQLite and insert into PostgreSQL
    sqlite_conn = sqlite3.connect(seed_db)
    sqlite_conn.row_factory = sqlite3.Row

    tables_to_migrate = [
        "ventures", "news_feed", "raw_signals", "thought_leaders",
        "tl_signals", "venture_scores", "tech_gaps", "harvest_runs",
        "votes", "annotations", "comments", "platform_users",
        "page_annotations", "page_annotation_replies", "app_settings",
        "office_hours_reviews",
    ]

    with pg_engine.connect() as conn:
        for table_name in tables_to_migrate:
            try:
                cursor = sqlite_conn.execute(f"SELECT * FROM {table_name}")
                rows = cursor.fetchall()
                if not rows:
                    continue

                columns = [desc[0] for desc in cursor.description]
                for row in rows:
                    values = dict(zip(columns, row))
                    cols = ", ".join(f'"{c}"' for c in columns)
                    placeholders = ", ".join(f":{c}" for c in columns)
                    try:
                        conn.execute(
                            text(f'INSERT INTO "{table_name}" ({cols}) VALUES ({placeholders})'),
                            values
                        )
                    except Exception as e:
                        # Skip duplicate rows
                        conn.rollback()
                        continue

                conn.commit()
                print(f"[start] Migrated {len(rows)} rows from {table_name}")
            except Exception as e:
                print(f"[start] Skipping {table_name}: {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass

    sqlite_conn.close()
    print("[start] SQLite -> PostgreSQL migration complete")


def main():
    db_url = os.environ.get("DATABASE_URL", "")

    if "postgresql" in db_url or "postgres://" in db_url:
        print("[start] PostgreSQL detected, checking migration...")
        try:
            migrate_sqlite_to_postgres()
        except Exception as e:
            print(f"[start] Migration error (non-fatal): {e}")

    elif db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "", 1)
        if db_path and not db_path.startswith("./"):
            db_dir = os.path.dirname(db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
            if not os.path.exists(db_path):
                seed_db = os.path.join(os.path.dirname(__file__), "venture_engine.db")
                if os.path.exists(seed_db):
                    print(f"[start] First deploy: copying seed DB to {db_path}")
                    shutil.copy2(seed_db, db_path)

    # Start the app
    port = os.environ.get("PORT", "8000")
    print(f"[start] Starting uvicorn on port {port}")
    os.execvp("uvicorn", [
        "uvicorn", "venture_engine.main:app",
        "--host", "0.0.0.0",
        "--port", port,
    ])


if __name__ == "__main__":
    main()
