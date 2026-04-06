#!/usr/bin/env python3
"""
Startup script that ensures database persistence across deploys.

On Railway (or any platform with a persistent volume):
1. Set env var DATABASE_URL=sqlite:////data/venture_engine.db
2. Mount a persistent volume at /data

On first deploy, this script copies the seed DB from the repo to the volume.
On subsequent deploys, the volume DB is preserved and used as-is.
"""
import os
import shutil
import subprocess
import sys


def main():
    db_url = os.environ.get("DATABASE_URL", "")

    # If DATABASE_URL points to a volume path, ensure the DB file exists there
    if db_url.startswith("sqlite:///"):
        # sqlite:////data/venture_engine.db -> /data/venture_engine.db
        db_path = db_url.replace("sqlite:///", "", 1)

        if db_path and not db_path.startswith("./"):
            # This is an absolute path (e.g., /data/venture_engine.db) — a volume
            db_dir = os.path.dirname(db_path)

            if db_dir and not os.path.exists(db_dir):
                print(f"[start] Creating directory: {db_dir}")
                os.makedirs(db_dir, exist_ok=True)

            if not os.path.exists(db_path):
                # First deploy: copy the seed DB from the repo
                seed_db = os.path.join(os.path.dirname(__file__), "venture_engine.db")
                if os.path.exists(seed_db):
                    print(f"[start] First deploy: copying seed DB to {db_path}")
                    shutil.copy2(seed_db, db_path)
                else:
                    print(f"[start] No seed DB found, will create fresh at {db_path}")
            else:
                print(f"[start] Using existing volume DB at {db_path}")
        else:
            print(f"[start] Using local DB: {db_path}")
    else:
        print(f"[start] Non-SQLite DATABASE_URL, skipping DB file setup")

    # Start the app
    port = os.environ.get("PORT", "8000")
    cmd = f"uvicorn venture_engine.main:app --host 0.0.0.0 --port {port}"
    print(f"[start] Starting: {cmd}")
    os.execvp("uvicorn", [
        "uvicorn", "venture_engine.main:app",
        "--host", "0.0.0.0",
        "--port", port,
    ])


if __name__ == "__main__":
    main()
