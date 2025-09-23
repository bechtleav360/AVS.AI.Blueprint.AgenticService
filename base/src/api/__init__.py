"""FastAPI routes and dependencies."""

from .deps import get_backup_agent, get_data_gateway, get_decision_engine
from .routes import router

__all__ = [
    "router",
    "get_backup_agent",
    "get_data_gateway", 
    "get_decision_engine",
]
