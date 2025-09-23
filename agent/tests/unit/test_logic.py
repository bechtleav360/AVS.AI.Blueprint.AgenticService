"""Unit tests for backup logic functions."""

import pytest

from src.agent.logic import BackupLogic
from src.models.asset import AssetMetadata, AssetType, CloudProvider


class TestBackupLogic:
    """Test cases for BackupLogic class."""
    
    def test_detect_cloud_provider_aws_from_uri(self):
        """Test AWS provider detection from URI."""
        provider, evidence = BackupLogic.detect_cloud_provider(
            CloudProvider.UNKNOWN,
            {},
            ["s3://my-backup-bucket/backups/"]
        )
        
        assert provider == CloudProvider.AWS
        assert len(evidence) == 1
        assert "AWS URI detected" in evidence[0]
    
    def test_detect_cloud_provider_azure_from_uri(self):
        """Test Azure provider detection from URI."""
        provider, evidence = BackupLogic.detect_cloud_provider(
            CloudProvider.UNKNOWN,
            {},
            ["https://mystorageaccount.blob.core.windows.net/backups/"]
        )
        
        assert provider == CloudProvider.AZURE
        assert len(evidence) == 1
        assert "Azure URI detected" in evidence[0]
    
    def test_detect_cloud_provider_from_tags(self):
        """Test provider detection from tags."""
        provider, evidence = BackupLogic.detect_cloud_provider(
            CloudProvider.UNKNOWN,
            {"cloud_provider": "aws", "region": "us-east-1"},
            []
        )
        
        assert provider == CloudProvider.AWS
        assert len(evidence) == 1
        assert "AWS tag detected" in evidence[0]
    
    def test_detect_cloud_provider_declared(self):
        """Test that declared provider is trusted."""
        provider, evidence = BackupLogic.detect_cloud_provider(
            CloudProvider.GCP,
            {},
            []
        )
        
        assert provider == CloudProvider.GCP
        assert len(evidence) == 1
        assert "Provider declared as gcp" in evidence[0]
    
    def test_score_cloud_backup_with_backup_tags(self):
        """Test backup scoring with explicit backup tags."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            tags={"backup": "enabled", "backup-schedule": "daily"},
            uris=["s3://backup-bucket/db-backups/"]
        )
        
        has_backup, confidence, evidence = BackupLogic.score_cloud_backup(asset)
        
        assert has_backup is True
        assert confidence > 0.5
        assert len(evidence) > 0
        assert any("backup enabled" in e.lower() for e in evidence)
    
    def test_score_cloud_backup_with_backup_uris(self):
        """Test backup scoring with backup URIs."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.VIRTUAL_MACHINE,
            provider=CloudProvider.AWS,
            tags={},
            uris=["s3://vm-snapshots/daily-backup/", "ebs://snap-12345"]
        )
        
        has_backup, confidence, evidence = BackupLogic.score_cloud_backup(asset)
        
        assert has_backup is True
        assert confidence > 0.5
        assert len(evidence) > 0
    
    def test_score_cloud_backup_no_indicators(self):
        """Test backup scoring with no backup indicators."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.APPLICATION,
            provider=CloudProvider.UNKNOWN,
            tags={"environment": "dev"},
            uris=["http://app.example.com"]
        )
        
        has_backup, confidence, evidence = BackupLogic.score_cloud_backup(asset)
        
        assert has_backup is False
        assert confidence <= 0.5
    
    def test_score_cloud_backup_production_environment(self):
        """Test that production environment increases backup likelihood."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            tags={},
            uris=[],
            environment="production"
        )
        
        has_backup, confidence, evidence = BackupLogic.score_cloud_backup(asset)
        
        # Production should have some positive impact
        assert any("production" in e.lower() for e in evidence)
    
    def test_generate_recommendations_no_backup(self):
        """Test recommendations when no backup is detected."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            environment="production"
        )
        
        recommendations = BackupLogic.generate_recommendations(
            asset, has_backup=False, confidence=0.2, evidence=[]
        )
        
        assert len(recommendations) > 0
        assert any("backup" in rec.lower() for rec in recommendations)
        assert any("database" in rec.lower() for rec in recommendations)
        assert any("production" in rec.lower() for rec in recommendations)
    
    def test_generate_recommendations_has_backup_low_confidence(self):
        """Test recommendations when backup exists but confidence is low."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.VIRTUAL_MACHINE,
            provider=CloudProvider.AZURE
        )
        
        recommendations = BackupLogic.generate_recommendations(
            asset, has_backup=True, confidence=0.6, evidence=[]
        )
        
        assert len(recommendations) > 0
        assert any("verify" in rec.lower() or "test" in rec.lower() for rec in recommendations)
    
    def test_assess_risk_level_no_backup_production(self):
        """Test risk assessment for production asset without backup."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.DATABASE,
            provider=CloudProvider.AWS,
            environment="production"
        )
        
        risk_level = BackupLogic.assess_risk_level(asset, has_backup=False, confidence=0.1)
        
        assert risk_level == "high"
    
    def test_assess_risk_level_backup_exists_high_confidence(self):
        """Test risk assessment when backup exists with high confidence."""
        asset = AssetMetadata(
            id="test-asset",
            name="Test Asset",
            type=AssetType.STORAGE_BUCKET,
            provider=CloudProvider.AWS,
            environment="production"
        )
        
        risk_level = BackupLogic.assess_risk_level(asset, has_backup=True, confidence=0.9)
        
        assert risk_level in ["low", "medium"]  # Production might elevate to medium
    
    def test_analyze_backup_tags_enabled(self):
        """Test backup tag analysis with enabled backup."""
        tags = {"backup": "enabled", "backup-retention": "30 days"}
        
        result = BackupLogic._analyze_backup_tags(tags)
        
        assert len(result["evidence"]) > 0
        assert len(result["confidence_factors"]) > 0
        assert all(cf > 0 for cf in result["confidence_factors"])
    
    def test_analyze_backup_tags_disabled(self):
        """Test backup tag analysis with disabled backup."""
        tags = {"backup": "disabled", "backup-enabled": "false"}
        
        result = BackupLogic._analyze_backup_tags(tags)
        
        assert len(result["evidence"]) > 0
        assert len(result["confidence_factors"]) > 0
        assert any(cf < 0 for cf in result["confidence_factors"])
    
    def test_analyze_backup_uris_aws_patterns(self):
        """Test backup URI analysis with AWS patterns."""
        uris = [
            "s3://backup-bucket/database-backups/",
            "glacier://archive-vault/yearly-backups/",
            "rds://db-instance.backup.region.amazonaws.com"
        ]
        
        result = BackupLogic._analyze_backup_uris(uris, CloudProvider.AWS)
        
        assert len(result["evidence"]) > 0
        assert len(result["confidence_factors"]) > 0
        assert all(cf > 0 for cf in result["confidence_factors"])
    
    def test_analyze_asset_type_backup_database(self):
        """Test asset type specific backup analysis for database."""
        tags = {"db_backup": "enabled"}
        uris = ["mysql://backup-server/dumps/"]
        
        result = BackupLogic._analyze_asset_type_backup(
            AssetType.DATABASE, tags, uris
        )
        
        assert len(result["evidence"]) > 0
        assert len(result["confidence_factors"]) > 0
        assert all(cf > 0 for cf in result["confidence_factors"])
    
    def test_analyze_environment_backup_production(self):
        """Test environment-based backup analysis for production."""
        result = BackupLogic._analyze_environment_backup("production", {})
        
        assert len(result["evidence"]) > 0
        assert len(result["confidence_factors"]) > 0
        assert result["confidence_factors"][0] > 0.5  # Production should have high confidence
    
    def test_analyze_environment_backup_development(self):
        """Test environment-based backup analysis for development."""
        result = BackupLogic._analyze_environment_backup("development", {})
        
        assert len(result["evidence"]) > 0
        assert len(result["confidence_factors"]) > 0
        assert result["confidence_factors"][0] < 0.5  # Development should have low confidence
