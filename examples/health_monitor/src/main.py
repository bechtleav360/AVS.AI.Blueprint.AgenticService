"""Declaration of the Health Monitor agent.

``agent`` records what the agent is made of; nothing is constructed until it is built.
``create_app()`` builds it as an application of its own::

    uvicorn src.main:create_app --factory
"""

from pathlib import Path

from blueprint.agents import AppBuilder, Config

from src.api.routes import MonitorApi
from src.schedulers.health_check_scheduler import HealthCheckScheduler
from src.schedulers.report_scheduler import ReportScheduler
from src.services.monitor_service import MonitorService

agent = (
    AppBuilder()
    .with_service(MonitorService)
    .with_rest_api(MonitorApi)
    .with_scheduler(HealthCheckScheduler)
    .with_scheduler(ReportScheduler)
    .with_cache()
)


def create_app():
    """Build this agent as an application of its own."""
    return agent.build(Config(settings_files=["settings.toml"], root_path=str(Path(__file__).parent.parent)))
