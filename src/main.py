"""Convenient application entry point.

The implementation remains in ``src.api.main`` so the original AI-Serv5
import path stays stable.
"""

from src.api.main import app

__all__ = ["app"]
