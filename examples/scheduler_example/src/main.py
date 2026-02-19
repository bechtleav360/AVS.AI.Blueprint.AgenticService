"""Entry point for the scheduler example.

This example demonstrates:
- Two Scheduler subclasses running on different cron schedules
- A BusinessService shared between the schedulers and a REST API
- How all components are wired together via AppBuilder

Run with:
    uvicorn src.main:app --reload
"""

from pathlib import Path

from blueprint.agents.app_builder import AppBuilder
from blueprint.agents.config import Config

from .api import MetricsRestApi
from .schedulers import CleanupScheduler, MetricsCollectorScheduler
from .services import MetricsService

project_root = Path(__file__).parent.parent
settings_files = [
    project_root / "settings.toml",
    project_root / "secrets.toml",
]

# ============================================================================
# Step 1: Load Configuration
# ============================================================================

config = Config(settings_files=settings_files, root_path=project_root)

# ============================================================================
# Step 2: Instantiate components
# ============================================================================

metrics_service = MetricsService()
metrics_api = MetricsRestApi()
collector = MetricsCollectorScheduler()
cleanup = CleanupScheduler()

# ============================================================================
# Step 3: Build the app
#   - with_service()   → registers MetricsService in the ComponentRegistry
#   - with_scheduler() → registers each Scheduler; AppBuilder starts/stops them
#   - with_rest_api()  → registers the REST API; AppBuilder includes the router
# ============================================================================

app = (
    AppBuilder(config=config)
    .with_service(metrics_service)
    .with_scheduler(collector)
    .with_scheduler(cleanup)
    .with_rest_api(metrics_api)
    .build()
)
