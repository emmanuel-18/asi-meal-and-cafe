"""Database metadata only; importing this package never opens a connection."""

from asi_meal_api.db.base import Base
from asi_meal_api.db import models as models

__all__ = ["Base", "models"]
