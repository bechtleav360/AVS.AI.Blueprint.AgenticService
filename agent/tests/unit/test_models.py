"""Unit tests for data models."""

import pytest
from datetime import datetime
from uuid import uuid4

from src.models.asset import AssetMetadata, AssetType, CloudProvider
from src.models.events import EventEnvelopeThin, EventEnvelopeFat, EventType, create_thin_event, create_fat_event
from src.models.result import AgentOutput, BackupStatus, Evidence


class TestAssetMetadata:
    """Test cases for AssetMetadata model."""
    
    def test_create_valid_asset(self):
        """Test creating a valid asset."""
        asset = AssetMetadata(
            id="test-asset-1",
            name="Test Database",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            tags={"environment": "production"},
            uris=["s3://backup-bucket/db-backups/"]
        )
        
        assert asset.id == "test-asset-1"
        assert asset.name == "Test Database"
        assert asset.type == AssetType.DATABASE
        assert asset.provider == CloudProvider.AWS
        assert asset.tags["environment"] == "production"
        assert len(asset.uris) == 1
    
    def test_has_backup_indicators_with_tags(self):
        """Test backup indicator detection in tags."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            tags={"backup": "enabled", "backup-schedule": "daily"}
        )
        
        assert asset.has_backup_indicators() is True
    
    def test_has_backup_indicators_with_uris(self):
        """Test backup indicator detection in URIs."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            uris=["s3://backup-bucket/snapshots/", "rds://db.amazonaws.com"]
        )
        
        assert asset.has_backup_indicators() is True
    
    def test_has_backup_indicators_none(self):
        """Test no backup indicators."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.APPLICATION,
            provider=CloudProvider.AWS,
            tags={"environment": "dev"},
            uris=["http://app.example.com"]
        )
        
        assert asset.has_backup_indicators() is False
    
    def test_get_backup_uris(self):
        """Test extraction of backup URIs."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            uris=[
                "s3://backup-bucket/snapshots/",
                "http://app.example.com",
                "archive://vault/backups/"
            ]
        )
        
        backup_uris = asset.get_backup_uris()
        
        assert len(backup_uris) == 2
        assert "s3://backup-bucket/snapshots/" in backup_uris
        assert "archive://vault/backups/" in backup_uris
        assert "http://app.example.com" not in backup_uris
    
    def test_get_tenant_id_from_tags(self):
        """Test tenant ID extraction from tags."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            tags={"tenant_id": "org-123", "environment": "prod"}
        )
        
        tenant_id = asset.get_tenant_id()
        
        assert tenant_id == "org-123"
    
    def test_get_tenant_id_from_cost_center(self):
        """Test tenant ID extraction from cost center."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            cost_center="engineering-team"
        )
        
        tenant_id = asset.get_tenant_id()
        
        assert tenant_id == "engineering-team"
    
    def test_validate_uris_invalid(self):
        """Test URI validation with invalid URIs."""
        with pytest.raises(ValueError, match="Invalid URI"):
            AssetMetadata(
                id="test-asset",
                name="Test Asset",
                type=AssetType.DATABASE,
                provider=CloudProvider.AWS,
                uris=["", "  ", "valid-uri"]
            )
    
    def test_validate_tags_sensitive_data(self):
        """Test tag validation rejects sensitive data."""
        with pytest.raises(ValueError, match="Sensitive data not allowed"):
            AssetMetadata(
                id="test-asset",
                name="Test Asset",
                type=AssetType.DATABASE,
                provider=CloudProvider.AWS,
                tags={"password": "secret123"}
            )


class TestEventEnvelopes:
    """Test cases for event envelope models."""
    
    def test_create_thin_event(self):
        """Test creating a thin event."""
        event = create_thin_event(
            EventType.ASSET_CREATED,
            "test-asset",
            asset_url="http://gateway/assets/test-asset",
            summary={"type": "database"},
            tenant_id="org-123"
        )
        
        assert isinstance(event, EventEnvelopeThin)
        assert event.event_type == EventType.ASSET_CREATED
        assert event.get_asset_id() == "test-asset"
        assert event.get_asset_url() == "http://gateway/assets/test-asset"
        assert event.get_summary()["type"] == "database"
        assert event.tenant_id == "org-123"
    
    def test_create_fat_event(self):
        """Test creating a fat event."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            tags={"secret_key": "should-be-removed"}  # This should be cleaned
        )
        
        event = create_fat_event(
            EventType.ASSET_CREATED,
            asset,
            tenant_id="org-123"
        )
        
        assert isinstance(event, EventEnvelopeFat)
        assert event.event_type == EventType.ASSET_CREATED
        assert event.get_asset_id() == "test-asset"
        assert event.tenant_id == "org-123"
        
        # Check that sensitive data was removed
        extracted_asset = event.get_asset()
        assert "secret_key" not in extracted_asset.tags
    
    def test_thin_event_validation_no_asset_id(self):
        """Test thin event validation requires asset_id."""
        with pytest.raises(ValueError, match="must contain asset_id"):
            EventEnvelopeThin(
                event_id=uuid4(),
                event_type=EventType.ASSET_CREATED,
                occurred_at=datetime.utcnow(),
                data={"summary": {"type": "database"}},  # Missing asset_id
                links={}
            )
    
    def test_thin_event_validation_data_too_large(self):
        """Test thin event validation rejects large data."""
        large_data = {
            "asset_id": "test-asset",
            "large_field": "x" * 2000  # Too large for thin event
        }
        
        with pytest.raises(ValueError, match="Thin event data too large"):
            EventEnvelopeThin(
                event_id=uuid4(),
                event_type=EventType.ASSET_CREATED,
                occurred_at=datetime.utcnow(),
                data=large_data,
                links={}
            )
    
    def test_fat_event_validation_no_asset(self):
        """Test fat event validation requires asset data."""
        with pytest.raises(ValueError, match="must contain asset data"):
            EventEnvelopeFat(
                event_id=uuid4(),
                event_type=EventType.ASSET_CREATED,
                occurred_at=datetime.utcnow(),
                data={"summary": {"type": "database"}}  # Missing asset
            )
    
    def test_traceparent_validation_invalid_format(self):
        """Test traceparent validation with invalid format."""
        with pytest.raises(ValueError, match="Invalid traceparent format"):
            EventEnvelopeThin(
                event_id=uuid4(),
                event_type=EventType.ASSET_CREATED,
                occurred_at=datetime.utcnow(),
                data={"asset_id": "test-asset"},
                links={},
                traceparent="invalid-format"
            )
    
    def test_traceparent_validation_valid_format(self):
        """Test traceparent validation with valid format."""
        event = EventEnvelopeThin(
            event_id=uuid4(),
            event_type=EventType.ASSET_CREATED,
            occurred_at=datetime.utcnow(),
            data={"asset_id": "test-asset"},
            links={},
            traceparent="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        )
        
        assert event.traceparent == "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


class TestAgentOutput:
    """Test cases for AgentOutput model."""
    
    def test_create_valid_agent_output(self):
        """Test creating valid agent output."""
        evidence = [
            Evidence(
                type="tag",
                source="asset_metadata",
                value="backup=enabled",
                confidence=0.9,
                description="Backup tag found"
            )
        ]
        
        output = AgentOutput(
            asset_id="test-asset",
            backup_status=BackupStatus.ENABLED,
            confidence=0.85,
            evidence=evidence,
            reasoning="Asset has explicit backup configuration",
            backup_locations=["s3://backup-bucket/"],
            recommendations=["Monitor backup success rates"],
            risk_level="low"
        )
        
        assert output.asset_id == "test-asset"
        assert output.backup_status == BackupStatus.ENABLED
        assert output.confidence == 0.85
        assert len(output.evidence) == 1
        assert output.risk_level == "low"
    
    def test_confidence_validation_invalid_range(self):
        """Test confidence validation rejects values outside 0-1 range."""
        with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
            AgentOutput(
                asset_id="test-asset",
                backup_status=BackupStatus.ENABLED,
                confidence=1.5  # Invalid
            )
    
    def test_evidence_sorting_by_confidence(self):
        """Test that evidence is sorted by confidence."""
        evidence = [
            Evidence(type="tag", source="metadata", value="low", confidence=0.3),
            Evidence(type="uri", source="metadata", value="high", confidence=0.9),
            Evidence(type="api", source="cloud", value="medium", confidence=0.6)
        ]
        
        output = AgentOutput(
            asset_id="test-asset",
            backup_status=BackupStatus.ENABLED,
            confidence=0.8,
            evidence=evidence
        )
        
        # Evidence should be sorted by confidence (highest first)
        assert output.evidence[0].confidence == 0.9
        assert output.evidence[1].confidence == 0.6
        assert output.evidence[2].confidence == 0.3
    
    def test_get_highest_confidence_evidence(self):
        """Test getting highest confidence evidence."""
        evidence = [
            Evidence(type="tag", source="metadata", value="low", confidence=0.3),
            Evidence(type="uri", source="metadata", value="high", confidence=0.9)
        ]
        
        output = AgentOutput(
            asset_id="test-asset",
            backup_status=BackupStatus.ENABLED,
            confidence=0.8,
            evidence=evidence
        )
        
        highest = output.get_highest_confidence_evidence()
        
        assert highest is not None
        assert highest.confidence == 0.9
        assert highest.value == "high"
    
    def test_get_evidence_by_type(self):
        """Test filtering evidence by type."""
        evidence = [
            Evidence(type="tag", source="metadata", value="tag1", confidence=0.8),
            Evidence(type="uri", source="metadata", value="uri1", confidence=0.7),
            Evidence(type="tag", source="metadata", value="tag2", confidence=0.6)
        ]
        
        output = AgentOutput(
            asset_id="test-asset",
            backup_status=BackupStatus.ENABLED,
            confidence=0.8,
            evidence=evidence
        )
        
        tag_evidence = output.get_evidence_by_type("tag")
        
        assert len(tag_evidence) == 2
        assert all(e.type == "tag" for e in tag_evidence)
    
    def test_has_strong_evidence(self):
        """Test strong evidence detection."""
        evidence = [
            Evidence(type="tag", source="metadata", value="strong", confidence=0.9),
            Evidence(type="uri", source="metadata", value="weak", confidence=0.4)
        ]
        
        output = AgentOutput(
            asset_id="test-asset",
            backup_status=BackupStatus.ENABLED,
            confidence=0.8,
            evidence=evidence
        )
        
        assert output.has_strong_evidence(min_confidence=0.8) is True
        assert output.has_strong_evidence(min_confidence=0.95) is False
    
    def test_get_summary(self):
        """Test getting output summary."""
        output = AgentOutput(
            asset_id="test-asset",
            backup_status=BackupStatus.ENABLED,
            confidence=0.8,
            evidence=[Evidence(type="tag", source="metadata", value="test", confidence=0.8)],
            backup_locations=["s3://bucket1/", "s3://bucket2/"],
            recommendations=["Monitor backups"],
            risk_level="low"
        )
        
        summary = output.get_summary()
        
        assert summary["asset_id"] == "test-asset"
        assert summary["backup_status"] == BackupStatus.ENABLED
        assert summary["confidence"] == 0.8
        assert summary["evidence_count"] == 1
        assert summary["backup_locations_count"] == 2
        assert summary["risk_level"] == "low"
        assert summary["has_recommendations"] is True
    
    def test_to_thin_event_data(self):
        """Test conversion to thin event data format."""
        output = AgentOutput(
            asset_id="test-asset",
            backup_status=BackupStatus.ENABLED,
            confidence=0.8,
            evidence=[Evidence(type="tag", source="metadata", value="test", confidence=0.8)],
            backup_locations=["s3://bucket/"],
            risk_level="low",
            processing_time_ms=150
        )
        
        event_data = output.to_thin_event_data()
        
        assert event_data["asset_id"] == "test-asset"
        assert event_data["backup_status"] == BackupStatus.ENABLED
        assert event_data["confidence"] == 0.8
        assert event_data["evidence_count"] == 1
        assert event_data["backup_locations_count"] == 1
        assert event_data["risk_level"] == "low"
        assert event_data["processing_time_ms"] == 150
        assert "checked_at" in event_data


class TestEvidence:
    """Test cases for Evidence model."""
    
    def test_create_valid_evidence(self):
        """Test creating valid evidence."""
        evidence = Evidence(
            type="tag",
            source="asset_metadata",
            value="backup=enabled",
            confidence=0.9,
            description="Backup tag found in asset metadata"
        )
        
        assert evidence.type == "tag"
        assert evidence.source == "asset_metadata"
        assert evidence.value == "backup=enabled"
        assert evidence.confidence == 0.9
        assert evidence.description == "Backup tag found in asset metadata"
    
    def test_confidence_validation_invalid_range(self):
        """Test confidence validation rejects invalid range."""
        with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
            Evidence(
                type="tag",
                source="metadata",
                value="test",
                confidence=2.0  # Invalid
            )
