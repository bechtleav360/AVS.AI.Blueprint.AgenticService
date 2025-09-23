"""Integration tests for pub/sub event flow."""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from src.app import create_app
from src.models.asset import AssetMetadata, AssetType, CloudProvider
from src.models.events import EventType, create_thin_event, create_fat_event
from src.models.result import BackupStatus


class TestPubSubFlow:
    """Integration tests for the complete pub/sub event processing flow."""
    
    @pytest.fixture
    def app(self):
        """Create test FastAPI app."""
        return create_app()
    
    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)
    
    @pytest.fixture
    def sample_asset(self):
        """Create sample asset for testing."""
        return AssetMetadata(
            id="test-asset-1",
            name="Test Production Database",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            region="us-east-1",
            environment="production",
            tags={
                "backup": "enabled",
                "backup-schedule": "daily",
                "environment": "production"
            },
            uris=[
                "s3://backup-bucket/database-backups/test-db/",
                "rds://test-db.cluster-xyz.us-east-1.rds.amazonaws.com"
            ],
            owner="database-team",
            cost_center="engineering"
        )
    
    def test_health_endpoints(self, client):
        """Test health check endpoints."""
        # Test root endpoint
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "asset-backup-checker"
        
        # Test liveness probe
        response = client.get("/actuators/livez")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"
    
    @patch('src.agent.runtime.BackupAgent.run_check')
    def test_direct_backup_check_success(self, mock_run_check, client, sample_asset):
        """Test direct backup check endpoint with successful result."""
        # Mock the agent response
        from src.models.result import AgentOutput, Evidence
        
        mock_result = AgentOutput(
            asset_id=sample_asset.id,
            backup_status=BackupStatus.ENABLED,
            confidence=0.9,
            evidence=[
                Evidence(
                    type="tag",
                    source="asset_metadata",
                    value="backup=enabled",
                    confidence=0.9,
                    description="Backup explicitly enabled in tags"
                )
            ],
            reasoning="Asset has explicit backup configuration with daily schedule",
            backup_locations=["s3://backup-bucket/database-backups/test-db/"],
            recommendations=["Monitor backup success rates", "Test restoration procedures"],
            risk_level="low",
            processing_time_ms=250
        )
        mock_run_check.return_value = mock_result
        
        # Make request
        response = client.post("/check-backup", json={
            "asset": sample_asset.dict()
        })
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        
        assert data["success"] is True
        assert data["result"]["asset_id"] == sample_asset.id
        assert data["result"]["backup_status"] == "enabled"
        assert data["result"]["confidence"] == 0.9
        assert data["result"]["risk_level"] == "low"
        assert len(data["result"]["evidence"]) == 1
        assert len(data["result"]["backup_locations"]) == 1
        
        # Verify agent was called
        mock_run_check.assert_called_once()
    
    def test_direct_backup_check_invalid_request(self, client):
        """Test direct backup check with invalid request."""
        # Missing both asset_id and asset
        response = client.post("/check-backup", json={})
        assert response.status_code == 400
        assert "Either asset_id or asset must be provided" in response.json()["detail"]
        
        # Both asset_id and asset provided
        response = client.post("/check-backup", json={
            "asset_id": "test-asset",
            "asset": {"id": "test-asset", "name": "Test", "type": "database", "provider": "aws"}
        })
        assert response.status_code == 400
        assert "Provide either asset_id or asset, not both" in response.json()["detail"]
    
    @patch('src.gateways.data_gateway.DataGatewayClient.get_asset')
    @patch('src.agent.runtime.BackupAgent.run_check')
    def test_thin_event_processing_success(self, mock_run_check, mock_get_asset, client, sample_asset):
        """Test processing of thin events with successful asset fetch."""
        # Mock data gateway response
        mock_get_asset.return_value = sample_asset
        
        # Mock agent response
        from src.models.result import AgentOutput, Evidence
        
        mock_result = AgentOutput(
            asset_id=sample_asset.id,
            backup_status=BackupStatus.ENABLED,
            confidence=0.85,
            evidence=[
                Evidence(type="tag", source="metadata", value="backup=enabled", confidence=0.9)
            ],
            risk_level="low",
            processing_time_ms=300
        )
        mock_run_check.return_value = mock_result
        
        # Create thin event
        thin_event = create_thin_event(
            EventType.ASSET_CREATED,
            sample_asset.id,
            asset_url=f"http://gateway/assets/{sample_asset.id}",
            summary={"type": "database", "environment": "production"},
            tenant_id="org-123"
        )
        
        # Make request
        response = client.post("/events/assets", json=thin_event.dict())
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "processed"
        assert data["result"]["asset_id"] == sample_asset.id
        assert data["result"]["backup_status"] == "enabled"
        assert data["result"]["confidence"] == 0.85
        
        # Verify calls
        mock_get_asset.assert_called_once()
        mock_run_check.assert_called_once()
    
    @patch('src.agent.runtime.BackupAgent.run_check')
    def test_fat_event_processing_success(self, mock_run_check, client, sample_asset):
        """Test processing of fat events (no gateway fetch needed)."""
        # Mock agent response
        from src.models.result import AgentOutput, Evidence
        
        mock_result = AgentOutput(
            asset_id=sample_asset.id,
            backup_status=BackupStatus.ENABLED,
            confidence=0.9,
            evidence=[
                Evidence(type="tag", source="metadata", value="backup=enabled", confidence=0.9)
            ],
            risk_level="low",
            processing_time_ms=200
        )
        mock_run_check.return_value = mock_result
        
        # Create fat event
        fat_event = create_fat_event(
            EventType.ASSET_UPDATED,
            sample_asset,
            tenant_id="org-123"
        )
        
        # Make request
        response = client.post("/events/assets", json=fat_event.dict())
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "processed"
        assert data["result"]["asset_id"] == sample_asset.id
        assert data["result"]["backup_status"] == "enabled"
        
        # Verify agent was called (no gateway call needed for fat events)
        mock_run_check.assert_called_once()
    
    def test_event_processing_ignored_irrelevant_type(self, client, sample_asset):
        """Test that irrelevant event types are ignored."""
        # Create event with irrelevant type
        event = create_fat_event(EventType.BACKUP_CHECK_COMPLETED, sample_asset)
        
        # Make request
        response = client.post("/events/assets", json=event.dict())
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "ignored"
        assert "did not match any processing criteria" in data["message"]
    
    def test_event_processing_ignored_no_backup_indicators(self, client):
        """Test that assets without backup indicators are ignored."""
        # Create asset without backup indicators
        asset = AssetMetadata(
            id="test-asset-no-backup",
            name="Test Application",
            type=AssetType.APPLICATION,
            provider=CloudProvider.AWS,
            tags={"environment": "dev"},
            uris=["http://app.example.com"]
        )
        
        # Create event
        event = create_fat_event(EventType.ASSET_CREATED, asset)
        
        # Make request
        response = client.post("/events/assets", json=event.dict())
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "ignored"
    
    @patch('src.gateways.data_gateway.DataGatewayClient.get_asset')
    def test_thin_event_gateway_error_transient(self, mock_get_asset, client):
        """Test handling of transient gateway errors."""
        from src.gateways.data_gateway import DataGatewayError
        
        # Mock transient gateway error
        mock_get_asset.side_effect = DataGatewayError(
            "Connection timeout", 
            status_code=503, 
            is_transient=True
        )
        
        # Create thin event
        thin_event = create_thin_event(
            EventType.ASSET_CREATED,
            "test-asset",
            asset_url="http://gateway/assets/test-asset"
        )
        
        # Make request
        response = client.post("/events/assets", json=thin_event.dict())
        
        # Should return 502 for transient errors (to trigger retry)
        assert response.status_code == 502
        assert "Failed to fetch asset data" in response.json()["detail"]
    
    @patch('src.gateways.data_gateway.DataGatewayClient.get_asset')
    def test_thin_event_gateway_error_permanent(self, mock_get_asset, client):
        """Test handling of permanent gateway errors."""
        from src.gateways.data_gateway import DataGatewayError
        
        # Mock permanent gateway error
        mock_get_asset.side_effect = DataGatewayError(
            "Asset not found", 
            status_code=404, 
            is_transient=False
        )
        
        # Create thin event
        thin_event = create_thin_event(
            EventType.ASSET_CREATED,
            "nonexistent-asset",
            asset_url="http://gateway/assets/nonexistent-asset"
        )
        
        # Make request
        response = client.post("/events/assets", json=thin_event.dict())
        
        # Should acknowledge permanent errors
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "acknowledged"
        assert "not found or inaccessible" in data["message"]
    
    def test_idempotency_duplicate_events(self, client, sample_asset):
        """Test that duplicate events are handled correctly."""
        # Create event with specific ID
        event = create_fat_event(EventType.ASSET_CREATED, sample_asset)
        
        # First request should be processed
        response1 = client.post("/events/assets", json=event.dict())
        assert response1.status_code == 200
        
        # Second request with same event ID should be ignored
        response2 = client.post("/events/assets", json=event.dict())
        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["status"] == "ignored"
    
    @patch('src.agent.runtime.BackupAgent.health_check')
    @patch('src.gateways.data_gateway.DataGatewayClient.health_check')
    def test_comprehensive_health_check(self, mock_gateway_health, mock_agent_health, client):
        """Test comprehensive health check with all components."""
        # Mock component health responses
        mock_agent_health.return_value = {
            "status": "healthy",
            "processing_time_ms": 150,
            "model": "gpt-4",
            "provider": "openai"
        }
        
        mock_gateway_health.return_value = {
            "status": "healthy",
            "response_time_ms": 50,
            "circuit_breaker_state": "closed"
        }
        
        # Make request
        response = client.get("/actuators/health")
        
        # Verify response
        assert response.status_code == 200
        data = response.json()
        
        assert data["status"] == "UP"
        assert "components" in data
        assert data["components"]["backup_agent"]["status"] == "healthy"
        assert data["components"]["data_gateway"]["status"] == "healthy"
    
    @patch('src.agent.runtime.BackupAgent.health_check')
    def test_readiness_probe_ready(self, mock_agent_health, client):
        """Test readiness probe when service is ready."""
        mock_agent_health.return_value = {"status": "healthy"}
        
        response = client.get("/actuators/readyz")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
    
    @patch('src.agent.runtime.BackupAgent.health_check')
    def test_readiness_probe_not_ready(self, mock_agent_health, client):
        """Test readiness probe when service is not ready."""
        mock_agent_health.return_value = {"status": "unhealthy"}
        
        response = client.get("/actuators/readyz")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_ready"
    
    def test_metrics_endpoint(self, client):
        """Test metrics collection endpoint."""
        response = client.get("/actuators/metrics")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "decision_engine" in data
        assert "events_processed" in data["decision_engine"]
        assert "events_handled" in data["decision_engine"]
        assert "events_ignored" in data["decision_engine"]
        assert "handler_stats" in data["decision_engine"]


@pytest.mark.asyncio
class TestAsyncIntegration:
    """Async integration tests."""
    
    async def test_decision_engine_full_flow(self):
        """Test the complete decision engine flow asynchronously."""
        from src.agent.decision import DecisionEngine
        from src.agent.runtime import BackupAgent
        from unittest.mock import AsyncMock
        
        # Create mock backup agent
        mock_agent = AsyncMock()
        mock_result = AsyncMock()
        mock_result.backup_status = BackupStatus.ENABLED
        mock_result.confidence = 0.9
        mock_agent.run_check.return_value = mock_result
        
        # Create decision engine with default handlers
        engine = DecisionEngine()
        engine.setup_default_handlers(mock_agent)
        
        # Create test asset and event
        asset = AssetMetadata(
            id="test-asset",
            name="Test Database",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            tags={"backup": "enabled"},
            uris=["s3://backup-bucket/"]
        )
        
        event = create_fat_event(EventType.ASSET_CREATED, asset)
        
        # Process event
        result = await engine.process_event(event, asset)
        
        # Verify result
        assert result is not None
        assert result.backup_status == BackupStatus.ENABLED
        assert result.confidence == 0.9
        
        # Verify agent was called
        mock_agent.run_check.assert_called_once()
        
        # Check statistics
        stats = engine.get_stats()
        assert stats["events_processed"] == 1
        assert stats["events_handled"] == 1
        assert stats["events_ignored"] == 0
