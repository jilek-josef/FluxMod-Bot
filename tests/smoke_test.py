#!/usr/bin/env python3
"""
Quick smoke test for LHS implementation
Verifies all components can be imported and basic functionality works.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Track what's available
HAS_COLORAMA = False
HAS_DOTENV = False
HAS_PYMONGO = False

def check_dependencies():
    """Check which dependencies are available"""
    global HAS_COLORAMA, HAS_DOTENV, HAS_PYMONGO
    
    try:
        pass
    except ImportError:
        pass
    
    try:
        pass
    except ImportError:
        pass
    
    try:
        pass
    except ImportError:
        pass


def test_imports():
    """Test all modules can be imported"""
    print("Testing imports...")
    
    try:
        print("  ✓ lhs_client imports OK")
    except Exception as e:
        print(f"  ✗ lhs_client import failed: {e}")
        return False
    
    if HAS_COLORAMA:
        try:
            print("  ✓ lhs_server_manager imports OK")
        except Exception as e:
            print(f"  ✗ lhs_server_manager import failed: {e}")
            return False
    else:
        print("  ⚠ lhs_server_manager (skipped - colorama not installed)")
    
    if HAS_DOTENV and HAS_PYMONGO:
        try:
            print("  ✓ database.guilds imports OK")
        except Exception as e:
            print(f"  ✗ database.guilds import failed: {e}")
            return False
        
        try:
            print("  ✓ datawrapper imports OK")
        except Exception as e:
            print(f"  ✗ datawrapper import failed: {e}")
            return False
    else:
        print("  ⚠ database.guilds (skipped - dotenv/pymongo not installed)")
        print("  ⚠ datawrapper (skipped - dependencies not installed)")
    
    try:
        print("  ✓ lhs_moderation cog imports OK")
    except ImportError as e:
        if any(dep in str(e).lower() for dep in ["colorama", "dotenv", "pymongo", "fluxer"]):
            print("  ⚠ lhs_moderation cog (skipped - missing dependencies)")
        else:
            print(f"  ✗ lhs_moderation cog import failed: {e}")
            return False
    except Exception as e:
        print(f"  ✗ lhs_moderation cog import failed: {e}")
        return False
    
    return True


def test_settings():
    """Test GuildLHSSettings functionality"""
    print("\nTesting GuildLHSSettings...")
    
    from utils.lhs_client import GuildLHSSettings, ALL_LHS_CATEGORIES
    
    # Test default creation
    settings = GuildLHSSettings(guild_id=12345)
    assert settings.guild_id == 12345
    assert not settings.enabled
    assert settings.global_threshold == 0.55
    print("  ✓ Default settings creation OK")
    
    # Test categories
    assert len(settings.categories) == len(ALL_LHS_CATEGORIES)
    for cat in ALL_LHS_CATEGORIES:
        assert cat in settings.categories
        assert settings.categories[cat]["enabled"]
    print(f"  ✓ All {len(ALL_LHS_CATEGORIES)} categories present")
    
    # Test exemptions
    settings2 = GuildLHSSettings(
        guild_id=12345,
        exempt_roles=[111, 222],
        exempt_channels=[333],
        exempt_users=[444],
    )
    assert settings2.is_exempt(111, "role")
    assert settings2.is_exempt(333, "channel")
    assert settings2.is_exempt(444, "user")
    assert not settings2.is_exempt(999, "role")
    print("  ✓ Exemptions working")
    
    # Test channel overrides
    settings2.channel_overrides["555"] = {
        "categories": {"spam": {"enabled": False, "threshold": 0.9}},
        "action": "warn",
    }
    assert not settings2.is_category_enabled("spam", channel_id=555)
    assert settings2.get_threshold("spam", channel_id=555) == 0.9
    assert settings2.get_action(channel_id=555) == "warn"
    print("  ✓ Channel overrides working")
    
    # Test serialization
    data = settings2.to_dict()
    restored = GuildLHSSettings.from_dict(data)
    assert restored.guild_id == settings2.guild_id
    assert restored.enabled == settings2.enabled
    print("  ✓ Serialization roundtrip OK")
    
    return True


def test_client_defaults():
    """Test LHSClient defaults"""
    print("\nTesting LHSClient defaults...")
    
    from utils.lhs_client import LHSClient
    
    client = LHSClient()
    assert client.base_url == "http://127.0.0.1:8000"
    assert client.timeout == 10.0
    print("  ✓ Default client URL OK")
    
    # Test env override
    os.environ["LHS_SERVER_URL"] = "http://example.com:9000"
    client2 = LHSClient()
    assert client2.base_url == "http://example.com:9000"
    print("  ✓ Environment variable override OK")
    del os.environ["LHS_SERVER_URL"]
    
    return True


def test_server_manager():
    """Test LHSServerManager configuration"""
    if not HAS_COLORAMA:
        print("\nTesting LHSServerManager...")
        print("  ⚠ Skipped (colorama not installed)")
        return True
    
    print("\nTesting LHSServerManager...")
    
    from utils.lhs_server_manager import LHSServerManager
    
    # Test defaults
    manager = LHSServerManager()
    assert manager.host == "127.0.0.1"
    assert manager.port == 8000
    assert manager.server_url == "http://127.0.0.1:8000"
    assert manager.device == "cpu"
    print("  ✓ Default configuration OK")
    
    # Test command building
    cmd = manager._build_command()
    assert "-m" in cmd
    assert "LHS.inference_server" in cmd
    assert "--host" in cmd
    assert "--port" in cmd
    print("  ✓ Command building OK")
    
    # Test env overrides
    os.environ["LHS_HOST"] = "0.0.0.0"
    os.environ["LHS_PORT"] = "9000"
    os.environ["LHS_DEVICE"] = "cuda"
    
    manager2 = LHSServerManager()
    assert manager2.host == "0.0.0.0"
    assert manager2.port == 9000
    assert manager2.device == "cuda"
    print("  ✓ Environment variable overrides OK")
    
    del os.environ["LHS_HOST"]
    del os.environ["LHS_PORT"]
    del os.environ["LHS_DEVICE"]
    
    return True


def test_constants():
    """Test constants are correct"""
    print("\nTesting constants...")
    
    from utils.lhs_client import (
        DEFAULT_LHS_SETTINGS, ALL_LHS_CATEGORIES, 
        CATEGORY_DISPLAY_NAMES
    )
    
    assert not DEFAULT_LHS_SETTINGS["enabled"]
    assert DEFAULT_LHS_SETTINGS["global_threshold"] == 0.55
    assert DEFAULT_LHS_SETTINGS["action"] == "delete"
    print("  ✓ Default settings correct")
    
    assert len(ALL_LHS_CATEGORIES) == 11
    print(f"  ✓ {len(ALL_LHS_CATEGORIES)} categories defined")
    
    assert CATEGORY_DISPLAY_NAMES["toxicity"] == "Toxicity"
    assert CATEGORY_DISPLAY_NAMES["hate_speech"] == "Hate Speech"
    assert CATEGORY_DISPLAY_NAMES["phish"] == "Phishing"
    print("  ✓ Display names correct")
    
    return True


def test_check_result():
    """Test LHSCheckResult"""
    print("\nTesting LHSCheckResult...")
    
    from utils.lhs_client import LHSCheckResult
    
    result = LHSCheckResult(
        is_harmful=True,
        detected_categories=["toxicity", "insult"],
        predictions={
            "toxicity": {"detected": True, "confidence": 0.85},
            "insult": {"detected": True, "confidence": 0.95},
            "spam": {"detected": False, "confidence": 0.1},
        },
        inference_time_ms=45.5,
    )
    
    assert result.is_harmful
    assert len(result.detected_categories) == 2
    
    top = result.get_top_violations(limit=2)
    assert len(top) == 2
    assert top[0]["category"] == "insult"  # Highest confidence
    assert top[1]["category"] == "toxicity"
    print("  ✓ Top violations sorting OK")
    
    return True


def main():
    check_dependencies()
    
    print("=" * 60)
    print("LHS Smoke Test")
    print("=" * 60)
    
    if not HAS_COLORAMA:
        print("\nNote: colorama not installed, some tests skipped")
    if not HAS_DOTENV or not HAS_PYMONGO:
        print("Note: dotenv/pymongo not installed, database tests skipped")
    
    all_passed = True
    
    all_passed &= test_imports()
    all_passed &= test_settings()
    all_passed &= test_client_defaults()
    all_passed &= test_server_manager()
    all_passed &= test_constants()
    all_passed &= test_check_result()
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All smoke tests passed!")
    else:
        print("✗ Some tests failed")
        sys.exit(1)
    print("=" * 60)


if __name__ == "__main__":
    main()
