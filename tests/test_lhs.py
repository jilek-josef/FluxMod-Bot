"""
Tests for LHS (Language Harm Scanner) AI Moderation

Run with: python -m pytest tests/test_lhs.py -v
Or: python tests/test_lhs.py
"""

import unittest
from unittest.mock import Mock, patch, AsyncMock
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.lhs_client import (
    GuildLHSSettings,
    LHSCheckResult,
    get_lhs_client,
    reset_lhs_client,
    DEFAULT_LHS_SETTINGS,
    ALL_LHS_CATEGORIES,
    CATEGORY_DISPLAY_NAMES,
)
from utils.lhs_server_manager import LHSServerManager, reset_lhs_server_manager


class TestLHSCheckResult(unittest.TestCase):
    """Test LHSCheckResult dataclass"""
    
    def test_basic_creation(self):
        result = LHSCheckResult(
            is_harmful=True,
            detected_categories=["toxicity", "insult"],
            predictions={
                "toxicity": {"detected": True, "confidence": 0.85},
                "insult": {"detected": True, "confidence": 0.72},
            },
            inference_time_ms=45.5,
        )
        
        self.assertTrue(result.is_harmful)
        self.assertEqual(len(result.detected_categories), 2)
        self.assertEqual(result.inference_time_ms, 45.5)
    
    def test_get_top_violations(self):
        result = LHSCheckResult(
            is_harmful=True,
            detected_categories=["toxicity", "insult", "threat"],
            predictions={
                "toxicity": {"detected": True, "confidence": 0.85},
                "insult": {"detected": True, "confidence": 0.95},
                "threat": {"detected": True, "confidence": 0.72},
                "spam": {"detected": False, "confidence": 0.1},
            },
            inference_time_ms=50.0,
        )
        
        top = result.get_top_violations(limit=2)
        self.assertEqual(len(top), 2)
        # Should be sorted by confidence desc
        self.assertEqual(top[0]["category"], "insult")  # 0.95
        self.assertEqual(top[1]["category"], "toxicity")  # 0.85


class TestGuildLHSSettings(unittest.TestCase):
    """Test GuildLHSSettings dataclass"""
    
    def test_default_creation(self):
        settings = GuildLHSSettings(guild_id=12345)
        
        self.assertEqual(settings.guild_id, 12345)
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.global_threshold, 0.55)
        self.assertEqual(settings.action, "delete")
        self.assertEqual(settings.severity, 2)
        self.assertFalse(settings.log_only_mode)
    
    def test_categories_initialized(self):
        settings = GuildLHSSettings(guild_id=12345)
        
        # Should have all categories
        for cat in ALL_LHS_CATEGORIES:
            self.assertIn(cat, settings.categories)
            self.assertTrue(settings.categories[cat]["enabled"])
            self.assertEqual(settings.categories[cat]["threshold"], 0.55)
    
    def test_is_category_enabled(self):
        settings = GuildLHSSettings(guild_id=12345)
        settings.categories["spam"]["enabled"] = False
        
        self.assertTrue(settings.is_category_enabled("toxicity"))
        self.assertFalse(settings.is_category_enabled("spam"))
    
    def test_is_category_enabled_with_channel_override(self):
        settings = GuildLHSSettings(guild_id=12345)
        settings.channel_overrides["111"] = {
            "categories": {
                "spam": {"enabled": False, "threshold": 0.8}
            }
        }
        
        # Global: spam enabled, Channel 111: spam disabled
        self.assertTrue(settings.is_category_enabled("spam"))  # Global
        self.assertFalse(settings.is_category_enabled("spam", channel_id=111))  # Override
    
    def test_get_threshold(self):
        settings = GuildLHSSettings(guild_id=12345)
        settings.categories["toxicity"]["threshold"] = 0.7
        
        self.assertEqual(settings.get_threshold("toxicity"), 0.7)
        self.assertEqual(settings.get_threshold("spam"), 0.55)  # Default
    
    def test_get_threshold_with_channel_override(self):
        settings = GuildLHSSettings(guild_id=12345)
        settings.channel_overrides["222"] = {
            "categories": {
                "hate_speech": {"enabled": True, "threshold": 0.9}
            }
        }
        
        self.assertEqual(settings.get_threshold("hate_speech"), 0.55)  # Global
        self.assertEqual(settings.get_threshold("hate_speech", channel_id=222), 0.9)  # Override
    
    def test_is_exempt(self):
        settings = GuildLHSSettings(
            guild_id=12345,
            exempt_roles=[111, 222],
            exempt_channels=[333],
            exempt_users=[444],
        )
        
        self.assertTrue(settings.is_exempt(111, "role"))
        self.assertTrue(settings.is_exempt(222, "role"))
        self.assertFalse(settings.is_exempt(999, "role"))
        
        self.assertTrue(settings.is_exempt(333, "channel"))
        self.assertTrue(settings.is_exempt(444, "user"))
    
    def test_serialization_roundtrip(self):
        original = GuildLHSSettings(
            guild_id=12345,
            enabled=True,
            global_threshold=0.6,
            categories={"spam": {"enabled": False, "threshold": 0.8}},
            exempt_roles=[111],
            action="warn",
            severity=3,
        )
        
        data = original.to_dict()
        restored = GuildLHSSettings.from_dict(data)
        
        self.assertEqual(restored.guild_id, original.guild_id)
        self.assertEqual(restored.enabled, original.enabled)
        self.assertEqual(restored.global_threshold, original.global_threshold)
        self.assertEqual(restored.action, original.action)
        self.assertEqual(restored.severity, original.severity)


class TestLHSClient(unittest.IsolatedAsyncioTestCase):
    """Test LHSClient with mocked HTTP"""
    
    def setUp(self):
        reset_lhs_client()
        self.client = get_lhs_client()
    
    def tearDown(self):
        reset_lhs_client()
    
    @patch("aiohttp.ClientSession")
    async def test_check_content_success(self, mock_session_class):
        # Mock response
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            "predictions": {
                "toxicity": {"detected": True, "confidence": 0.85},
                "spam": {"detected": False, "confidence": 0.1},
            },
            "detected_categories": ["toxicity"],
            "is_harmful": True,
            "inference_time_ms": 50.0,
        }
        
        # Mock session
        mock_session = AsyncMock()
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session
        
        result = await self.client.check_content("test message")
        
        self.assertIsNotNone(result)
        self.assertTrue(result.is_harmful)
        self.assertIn("toxicity", result.detected_categories)
    
    @patch("aiohttp.ClientSession")
    async def test_check_content_failure(self, mock_session_class):
        # Mock failed response
        mock_response = AsyncMock()
        mock_response.status = 503
        
        mock_session = AsyncMock()
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session
        
        result = await self.client.check_content("test message")
        
        self.assertIsNone(result)
    
    @patch("aiohttp.ClientSession")
    async def test_health_check_success(self, mock_session_class):
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            "status": "healthy",
            "model_loaded": True,
            "queue_size": 0,
            "total_requests": 100,
            "device": "cpu",
        }
        
        mock_session = AsyncMock()
        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session
        
        health = await self.client.health_check()
        
        self.assertIsNotNone(health)
        self.assertEqual(health["status"], "healthy")
        self.assertTrue(health["model_loaded"])
    
    @patch("aiohttp.ClientSession")
    async def test_check_with_settings(self, mock_session_class):
        # Mock response with all categories
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.json.return_value = {
            "predictions": {
                "toxicity": {"detected": True, "confidence": 0.85},
                "spam": {"detected": True, "confidence": 0.65},
                "threat": {"detected": True, "confidence": 0.30},  # Below threshold
            },
            "detected_categories": ["toxicity", "spam", "threat"],
            "is_harmful": True,
            "inference_time_ms": 50.0,
        }
        
        mock_session = AsyncMock()
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session
        
        settings = GuildLHSSettings(guild_id=12345)
        settings.categories["toxicity"]["threshold"] = 0.80  # Requires 80%
        settings.categories["spam"]["threshold"] = 0.60     # Requires 60%
        settings.categories["threat"]["threshold"] = 0.50   # Requires 50%
        
        result = await self.client.check_with_settings("test", settings)
        
        self.assertIsNotNone(result)
        # Only spam (0.65 >= 0.60) should be detected with custom thresholds
        # toxicity (0.85 >= 0.80) should also be detected
        # threat (0.30 < 0.50) should NOT be detected
        self.assertIn("toxicity", result.detected_categories)
        self.assertIn("spam", result.detected_categories)
        self.assertNotIn("threat", result.detected_categories)


class TestLHSServerManager(unittest.TestCase):
    """Test LHSServerManager"""
    
    def setUp(self):
        reset_lhs_server_manager()
    
    def tearDown(self):
        reset_lhs_server_manager()
    
    def test_default_values(self):
        manager = LHSServerManager()
        
        self.assertEqual(manager.host, "127.0.0.1")
        self.assertEqual(manager.port, 8000)
        self.assertEqual(manager.server_url, "http://127.0.0.1:8000")
        self.assertEqual(manager.device, "cpu")
        self.assertEqual(manager.max_batch_size, 32)
    
    def test_env_override(self):
        with patch.dict(os.environ, {
            "LHS_HOST": "0.0.0.0",
            "LHS_PORT": "9000",
            "LHS_DEVICE": "cuda",
        }):
            manager = LHSServerManager()
            
            self.assertEqual(manager.host, "0.0.0.0")
            self.assertEqual(manager.port, 9000)
            self.assertEqual(manager.server_url, "http://0.0.0.0:9000")
            self.assertEqual(manager.device, "cuda")
    
    def test_find_model_path_exists(self):
        manager = LHSServerManager()
        
        with patch("os.path.exists") as mock_exists:
            mock_exists.return_value = True
            path = manager._find_model_path()
            
            self.assertTrue(mock_exists.called)
            self.assertEqual(path, manager.model_path)
    
    def test_build_command(self):
        manager = LHSServerManager()
        cmd = manager._build_command()
        
        self.assertIn("python", cmd[0])
        self.assertIn("-m", cmd)
        self.assertIn("LHS.inference_server", cmd)
        self.assertIn("--host", cmd)
        self.assertIn("--port", cmd)
        self.assertIn("--model-path", cmd)


class TestConstants(unittest.TestCase):
    """Test constants and defaults"""
    
    def test_all_categories_present(self):
        self.assertEqual(len(ALL_LHS_CATEGORIES), 11)
        self.assertIn("toxicity", ALL_LHS_CATEGORIES)
        self.assertIn("spam", ALL_LHS_CATEGORIES)
        self.assertIn("hate_speech", ALL_LHS_CATEGORIES)
    
    def test_category_display_names(self):
        self.assertEqual(CATEGORY_DISPLAY_NAMES["toxicity"], "Toxicity")
        self.assertEqual(CATEGORY_DISPLAY_NAMES["hate_speech"], "Hate Speech")
        self.assertEqual(CATEGORY_DISPLAY_NAMES["phish"], "Phishing")
    
    def test_default_lhs_settings_structure(self):
        self.assertIn("enabled", DEFAULT_LHS_SETTINGS)
        self.assertIn("global_threshold", DEFAULT_LHS_SETTINGS)
        self.assertIn("categories", DEFAULT_LHS_SETTINGS)
        self.assertIn("exempt_roles", DEFAULT_LHS_SETTINGS)
        self.assertIn("action", DEFAULT_LHS_SETTINGS)
        
        self.assertFalse(DEFAULT_LHS_SETTINGS["enabled"])
        self.assertEqual(DEFAULT_LHS_SETTINGS["global_threshold"], 0.55)


# Database tests (require mock)
class TestDatabaseIntegration(unittest.TestCase):
    """Test database functions with mocked MongoDB"""
    
    @patch("database.guilds.guilds")
    def test_get_lhs_settings_default(self, mock_collection):
        from database.guilds import get_lhs_settings, DEFAULT_LHS_SETTINGS
        
        # Mock no existing settings
        mock_collection.find_one.return_value = None
        
        settings = get_lhs_settings(12345)
        
        self.assertEqual(settings["enabled"], DEFAULT_LHS_SETTINGS["enabled"])
        self.assertEqual(settings["global_threshold"], DEFAULT_LHS_SETTINGS["global_threshold"])
    
    @patch("database.guilds.guilds")
    def test_get_lhs_settings_existing(self, mock_collection):
        from database.guilds import get_lhs_settings
        
        # Mock existing settings
        mock_collection.find_one.return_value = {
            "lhs_settings": {
                "enabled": True,
                "global_threshold": 0.7,
                "action": "ban",
            }
        }
        
        settings = get_lhs_settings(12345)
        
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["global_threshold"], 0.7)
        self.assertEqual(settings["action"], "ban")
    
    @patch("database.guilds.guilds")
    def test_update_lhs_settings(self, mock_collection):
        from database.guilds import update_lhs_settings
        
        mock_update = Mock()
        mock_collection.update_one = mock_update
        
        update_lhs_settings(12345, {"enabled": True, "action": "kick"})
        
        mock_update.assert_called_once()
        call_args = mock_update.call_args
        self.assertEqual(call_args[0][0], {"guild_id": 12345})
        self.assertEqual(call_args[1]["$set"]["lhs_settings"]["enabled"], True)


# Simple async runner for manual execution
if __name__ == "__main__":
    print("=" * 60)
    print("Running LHS Tests")
    print("=" * 60)
    
    # Run unittest
    unittest.main(verbosity=2, exit=False)
    
    print("\n" + "=" * 60)
    print("Tests Complete!")
    print("=" * 60)
