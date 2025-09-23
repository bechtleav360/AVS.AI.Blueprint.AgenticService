"""Unit tests for decision engine and handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from src.agent.decision import (
    DecisionEngine,
    EventTypeHandler,
    HandlerRegistry,
    IdempotencyHandler,
    RelevantAssetTypeHandler,
    BackupIndicatorHandler,
    TenantHandler,
)
from src.models.asset import AssetMetadata, AssetType, CloudProvider
from src.models.events import EventEnvelopeThin, EventEnvelopeFat, EventType, create_thin_event, create_fat_event


class TestHandlerRegistry:
    """Test cases for HandlerRegistry."""
    
    def test_register_handler(self):
        """Test handler registration."""
        registry = HandlerRegistry()
        handler = EventTypeHandler()
        
        registry.register(handler)
        
        assert len(registry.get_handlers()) == 1
        assert registry.get_handlers()[0] == handler
    
    def test_handlers_sorted_by_priority(self):
        """Test that handlers are sorted by priority."""
        registry = HandlerRegistry()
        
        handler1 = EventTypeHandler(priority=100)
        handler2 = EventTypeHandler(priority=50)
        handler3 = EventTypeHandler(priority=200)
        
        registry.register(handler1)
        registry.register(handler2)
        registry.register(handler3)
        
        handlers = registry.get_handlers()
        assert handlers[0].priority == 50
        assert handlers[1].priority == 100
        assert handlers[2].priority == 200
    
    def test_unregister_handler(self):
        """Test handler unregistration."""
        registry = HandlerRegistry()
        handler = EventTypeHandler()
        
        registry.register(handler)
        assert len(registry.get_handlers()) == 1
        
        registry.unregister(handler)
        assert len(registry.get_handlers()) == 0


class TestEventTypeHandler:
    """Test cases for EventTypeHandler."""
    
    @pytest.mark.asyncio
    async def test_can_handle_relevant_event_type(self):
        """Test handling of relevant event types."""
        handler = EventTypeHandler()
        event = create_thin_event(EventType.ASSET_CREATED, "test-asset")
        
        can_handle = await handler.can_handle(event)
        
        assert can_handle is True
    
    @pytest.mark.asyncio
    async def test_can_handle_irrelevant_event_type(self):
        """Test rejection of irrelevant event types."""
        handler = EventTypeHandler({EventType.ASSET_CREATED})
        event = create_thin_event(EventType.BACKUP_CHECK_COMPLETED, "test-asset")
        
        can_handle = await handler.can_handle(event)
        
        assert can_handle is False
    
    @pytest.mark.asyncio
    async def test_handle_returns_none(self):
        """Test that EventTypeHandler doesn't process events."""
        handler = EventTypeHandler()
        event = create_thin_event(EventType.ASSET_CREATED, "test-asset")
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS
        )
        
        result = await handler.handle(event, asset)
        
        assert result is None


class TestRelevantAssetTypeHandler:
    """Test cases for RelevantAssetTypeHandler."""
    
    @pytest.mark.asyncio
    async def test_can_handle_relevant_asset_type(self):
        """Test handling of relevant asset types."""
        handler = RelevantAssetTypeHandler()
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS
        )
        event = create_thin_event(EventType.ASSET_CREATED, "test-asset")
        
        can_handle = await handler.can_handle(event, asset)
        
        assert can_handle is True
    
    @pytest.mark.asyncio
    async def test_can_handle_irrelevant_asset_type(self):
        """Test rejection of irrelevant asset types."""
        handler = RelevantAssetTypeHandler({AssetType.DATABASE})
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.APPLICATION,
            provider=CloudProvider.AWS
        )
        event = create_thin_event(EventType.ASSET_CREATED, "test-asset")
        
        can_handle = await handler.can_handle(event, asset)
        
        assert can_handle is False
    
    @pytest.mark.asyncio
    async def test_can_handle_thin_event_with_type_in_summary(self):
        """Test handling thin event with asset type in summary."""
        handler = RelevantAssetTypeHandler()
        event = create_thin_event(
            EventType.ASSET_CREATED, 
            "test-asset",
            summary={"type": "database"}
        )
        
        can_handle = await handler.can_handle(event)
        
        assert can_handle is True


class TestBackupIndicatorHandler:
    """Test cases for BackupIndicatorHandler."""
    
    @pytest.mark.asyncio
    async def test_can_handle_asset_with_backup_indicators(self):
        """Test handling of assets with backup indicators."""
        handler = BackupIndicatorHandler()
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            tags={"backup": "enabled"},
            uris=["s3://backup-bucket/db-backups/"]
        )
        event = create_thin_event(EventType.ASSET_CREATED, "test-asset")
        
        can_handle = await handler.can_handle(event, asset)
        
        assert can_handle is True
    
    @pytest.mark.asyncio
    async def test_can_handle_asset_without_backup_indicators(self):
        """Test rejection of assets without backup indicators."""
        handler = BackupIndicatorHandler()
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.APPLICATION,
            provider=CloudProvider.AWS,
            tags={"environment": "dev"},
            uris=["http://app.example.com"]
        )
        event = create_thin_event(EventType.ASSET_CREATED, "test-asset")
        
        can_handle = await handler.can_handle(event, asset)
        
        assert can_handle is False
    
    @pytest.mark.asyncio
    async def test_can_handle_thin_event_with_backup_in_summary(self):
        """Test handling thin event with backup keywords in summary."""
        handler = BackupIndicatorHandler()
        event = create_thin_event(
            EventType.ASSET_CREATED,
            "test-asset",
            summary={"backup_status": "enabled"}
        )
        
        can_handle = await handler.can_handle(event)
        
        assert can_handle is True


class TestIdempotencyHandler:
    """Test cases for IdempotencyHandler."""
    
    @pytest.mark.asyncio
    async def test_can_handle_new_event(self):
        """Test handling of new events."""
        handler = IdempotencyHandler()
        event = create_thin_event(EventType.ASSET_CREATED, "test-asset")
        
        can_handle = await handler.can_handle(event)
        
        assert can_handle is True
    
    @pytest.mark.asyncio
    async def test_can_handle_duplicate_event(self):
        """Test rejection of duplicate events."""
        handler = IdempotencyHandler()
        event = create_thin_event(EventType.ASSET_CREATED, "test-asset")
        
        # First time should be handled
        can_handle1 = await handler.can_handle(event)
        assert can_handle1 is True
        
        # Second time should be rejected
        can_handle2 = await handler.can_handle(event)
        assert can_handle2 is False


class TestTenantHandler:
    """Test cases for TenantHandler."""
    
    @pytest.mark.asyncio
    async def test_can_handle_allowed_tenant(self):
        """Test handling of allowed tenants."""
        handler = TenantHandler({"tenant1", "tenant2"})
        event = create_thin_event(EventType.ASSET_CREATED, "test-asset", tenant_id="tenant1")
        
        can_handle = await handler.can_handle(event)
        
        assert can_handle is True
    
    @pytest.mark.asyncio
    async def test_can_handle_disallowed_tenant(self):
        """Test rejection of disallowed tenants."""
        handler = TenantHandler({"tenant1", "tenant2"})
        event = create_thin_event(EventType.ASSET_CREATED, "test-asset", tenant_id="tenant3")
        
        can_handle = await handler.can_handle(event)
        
        assert can_handle is False
    
    @pytest.mark.asyncio
    async def test_can_handle_no_tenant_restrictions(self):
        """Test handling when no tenant restrictions are set."""
        handler = TenantHandler(None)  # No restrictions
        event = create_thin_event(EventType.ASSET_CREATED, "test-asset", tenant_id="any-tenant")
        
        can_handle = await handler.can_handle(event)
        
        assert can_handle is True
    
    @pytest.mark.asyncio
    async def test_can_handle_no_tenant_id(self):
        """Test rejection when no tenant ID is provided but restrictions exist."""
        handler = TenantHandler({"tenant1"})
        event = create_thin_event(EventType.ASSET_CREATED, "test-asset")  # No tenant_id
        
        can_handle = await handler.can_handle(event)
        
        assert can_handle is False


class TestDecisionEngine:
    """Test cases for DecisionEngine."""
    
    @pytest.mark.asyncio
    async def test_process_event_handled(self):
        """Test successful event processing."""
        # Create mock backup agent
        mock_agent = AsyncMock()
        mock_result = MagicMock()
        mock_result.backup_status = "enabled"
        mock_result.confidence = 0.9
        mock_agent.run_check.return_value = mock_result
        
        # Create decision engine
        engine = DecisionEngine()
        engine.setup_default_handlers(mock_agent)
        
        # Create test event and asset
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            tags={"backup": "enabled"}
        )
        event = create_fat_event(EventType.ASSET_CREATED, asset)
        
        # Process event
        result = await engine.process_event(event, asset)
        
        assert result is not None
        assert result == mock_result
        mock_agent.run_check.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_process_event_ignored_by_event_type(self):
        """Test event ignored by event type filter."""
        mock_agent = AsyncMock()
        
        engine = DecisionEngine()
        engine.setup_default_handlers(mock_agent, relevant_event_types={EventType.ASSET_CREATED})
        
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS
        )
        event = create_fat_event(EventType.BACKUP_CHECK_COMPLETED, asset)
        
        result = await engine.process_event(event, asset)
        
        assert result is None
        mock_agent.run_check.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_process_event_ignored_by_asset_type(self):
        """Test event ignored by asset type filter."""
        mock_agent = AsyncMock()
        
        engine = DecisionEngine()
        engine.setup_default_handlers(mock_agent, relevant_asset_types={AssetType.DATABASE})
        
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.APPLICATION,
            provider=CloudProvider.AWS
        )
        event = create_fat_event(EventType.ASSET_CREATED, asset)
        
        result = await engine.process_event(event, asset)
        
        assert result is None
        mock_agent.run_check.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_process_event_ignored_by_backup_indicators(self):
        """Test event ignored by backup indicator filter."""
        mock_agent = AsyncMock()
        
        engine = DecisionEngine()
        engine.setup_default_handlers(mock_agent)
        
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            tags={"environment": "dev"},  # No backup indicators
            uris=["http://app.example.com"]
        )
        event = create_fat_event(EventType.ASSET_CREATED, asset)
        
        result = await engine.process_event(event, asset)
        
        assert result is None
        mock_agent.run_check.assert_not_called()
    
    def test_get_stats(self):
        """Test statistics collection."""
        engine = DecisionEngine()
        
        stats = engine.get_stats()
        
        assert "events_processed" in stats
        assert "events_handled" in stats
        assert "events_ignored" in stats
        assert "handler_stats" in stats
    
    def test_reset_stats(self):
        """Test statistics reset."""
        engine = DecisionEngine()
        engine.stats["events_processed"] = 10
        
        engine.reset_stats()
        
        assert engine.stats["events_processed"] == 0
