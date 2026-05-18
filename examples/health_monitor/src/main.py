"""Application entry point for the Health Monitor."""

from blueprint.agents import AppBuilder, Config

from src.api.routes import MonitorApi
from src.schedulers.health_check_scheduler import HealthCheckScheduler
from src.schedulers.report_scheduler import ReportScheduler
from src.services.monitor_service import MonitorService

config = Config(settings_files=["settings.toml"])

app = (
    AppBuilder(config)
    .with_service(MonitorService)
    .with_rest_api(MonitorApi())
    .with_scheduler(HealthCheckScheduler())
    .with_scheduler(ReportScheduler())
    .with_cache()
    .build()
)
