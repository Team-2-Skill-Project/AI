"""Compatibility export for the canonical CV router.

The CV extraction implementation intentionally lives in ``src.cv_extractor``
and ``src.api.routers.cv_router``.  Keeping this small export avoids a second
CV pipeline while preserving the feature-oriented API layout.
"""

from src.api.routers.cv_router import router

__all__ = ["router"]
