"""Vercel entrypoint - Vercel's Python runtime serves the ASGI `app` it finds
here as a single serverless function (see vercel.json). Locally and in
Docker the app is still started with `uvicorn main:app` instead.
"""
import sys
from pathlib import Path

# main.py imports its sibling modules (db, auth, ...) by bare name
sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import app  # noqa: E402,F401
