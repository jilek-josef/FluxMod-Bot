# LHS Tests

Tests for the LHS (Language Harm Scanner) AI Moderation feature.

## Running Tests

### Run all tests:
```bash
cd FluxMod-Bot
python -m pytest tests/test_lhs.py -v
```

### Run specific test class:
```bash
python -m pytest tests/test_lhs.py::TestGuildLHSSettings -v
```

### Run without pytest (using unittest):
```bash
cd FluxMod-Bot
python tests/test_lhs.py
```

### Run with coverage:
```bash
cd FluxMod-Bot
python -m pytest tests/test_lhs.py --cov=utils --cov=database -v
```

## Test Categories

### TestLHSCheckResult
Tests for the result dataclass and violation sorting.

### TestGuildLHSSettings
Tests for guild settings including:
- Default values
- Category enable/disable
- Channel overrides
- Exemptions (roles, channels, users)
- Serialization/deserialization

### TestLHSClient
Async tests for the HTTP client with mocked responses:
- Content checking
- Health checks
- Per-category threshold handling

### TestLHSServerManager
Tests for the server manager:
- Default configuration
- Environment variable overrides
- Command building

### TestConstants
Tests for constants and default settings.

### TestDatabaseIntegration
Tests for database functions with mocked MongoDB.

## Manual Integration Test

To test the full flow manually:

```python
import asyncio
from utils.lhs_client import get_lhs_client, GuildLHSSettings

async def test():
    client = get_lhs_client()
    
    # Test health check
    health = await client.health_check()
    print(f"Health: {health}")
    
    # Test content check
    result = await client.check_content("This is a test message")
    if result:
        print(f"Harmful: {result.is_harmful}")
        print(f"Categories: {result.detected_categories}")
    
    # Test with settings
    settings = GuildLHSSettings(guild_id=12345, enabled=True)
    result = await client.check_with_settings("test message", settings)
    print(f"With settings: {result}")

asyncio.run(test())
```

## Notes

- Tests use `unittest.mock` to mock HTTP calls and database
- No real LHS server or MongoDB instance required
- Async tests use `unittest.IsolatedAsyncioTestCase`
