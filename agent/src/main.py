"""
Main entry point for the agent service.

This file constructs the FastAPI application from the base framework and wires in
custom routes/components. This way, the base framework has NO dependencies on the
custom agent code, but most logic remains in `base`.
"""

from base.src.app import create_app

# Uvicorn entrypoint: base app already includes generic REST/events/Dapr routers.
app = create_app()

__all__ = ["app"]
