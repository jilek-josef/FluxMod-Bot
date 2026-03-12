"""
LHS (Language Harm Scanner) Client

HTTP client for communicating with the LHS inference server.
Provides async interface for content moderation using the TCN + Performer model.
"""

import asyncio
import aiohttp
import os
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class LHSCategory(str, Enum):
    """LHS classification categories"""
    DANGEROUS_CONTENT = "dangerous_content"
    HATE_SPEECH = "hate_speech"
    HARASSMENT = "harassment"
    SEXUALLY_EXPLICIT = "sexually_explicit"
    TOXICITY = "toxicity"
    SEVERE_TOXICITY = "severe_toxicity"
    THREAT = "threat"
    INSULT = "insult"
    IDENTITY_ATTACK = "identity_attack"
    PHISH = "phish"
    SPAM = "spam"


# All LHS categories
ALL_LHS_CATEGORIES = [c.value for c in LHSCategory]

# Category display names for UI
CATEGORY_DISPLAY_NAMES = {
    "dangerous_content": "Dangerous Content",
    "hate_speech": "Hate Speech",
    "harassment": "Harassment",
    "sexually_explicit": "Sexually Explicit",
    "toxicity": "Toxicity",
    "severe_toxicity": "Severe Toxicity",
    "threat": "Threat",
    "insult": "Insult",
    "identity_attack": "Identity Attack",
    "phish": "Phishing",
    "spam": "Spam",
}

# Category descriptions for UI
CATEGORY_DESCRIPTIONS = {
    "dangerous_content": "Content promoting dangerous or illegal activities",
    "hate_speech": "Content attacking protected groups",
    "harassment": "Content targeting individuals for harassment",
    "sexually_explicit": "Sexual or NSFW content",
    "toxicity": "General toxic behavior",
    "severe_toxicity": "Extremely toxic or hateful content",
    "threat": "Threats of violence or harm",
    "insult": "Personal insults or attacks",
    "identity_attack": "Attacks based on identity characteristics",
    "phish": "Phishing attempts or suspicious links",
    "spam": "Spam or repetitive unwanted content",
}

# Default threshold for all categories
DEFAULT_LHS_THRESHOLD = 0.55

# Default settings for a guild
DEFAULT_LHS_SETTINGS = {
    "enabled": False,
    "global_threshold": DEFAULT_LHS_THRESHOLD,
    "categories": {
        "dangerous_content": {"enabled": True, "threshold": DEFAULT_LHS_THRESHOLD},
        "hate_speech": {"enabled": True, "threshold": DEFAULT_LHS_THRESHOLD},
        "harassment": {"enabled": True, "threshold": DEFAULT_LHS_THRESHOLD},
        "sexually_explicit": {"enabled": True, "threshold": DEFAULT_LHS_THRESHOLD},
        "toxicity": {"enabled": True, "threshold": DEFAULT_LHS_THRESHOLD},
        "severe_toxicity": {"enabled": True, "threshold": DEFAULT_LHS_THRESHOLD},
        "threat": {"enabled": True, "threshold": DEFAULT_LHS_THRESHOLD},
        "insult": {"enabled": True, "threshold": DEFAULT_LHS_THRESHOLD},
        "identity_attack": {"enabled": True, "threshold": DEFAULT_LHS_THRESHOLD},
        "phish": {"enabled": True, "threshold": DEFAULT_LHS_THRESHOLD},
        "spam": {"enabled": True, "threshold": DEFAULT_LHS_THRESHOLD},
    },
    "exempt_roles": [],
    "exempt_channels": [],
    "exempt_users": [],
    "action": "delete",  # delete, warn, mute, kick, ban
    "severity": 2,  # 1-3
    "log_only_mode": False,  # If True, only logs without taking action
    "channel_overrides": {},  # Per-channel settings: {channel_id: {...}}
}


@dataclass
class LHSCheckResult:
    """Result of an LHS content check"""
    is_harmful: bool
    detected_categories: List[str]
    predictions: Dict[str, Dict[str, Any]]
    inference_time_ms: float
    
    def get_top_violations(self, limit: int = 3) -> List[Dict[str, Any]]:
        """Get top violations sorted by confidence"""
        violations = [
            {
                "category": cat,
                "confidence": data["confidence"],
                "display_name": CATEGORY_DISPLAY_NAMES.get(cat, cat),
            }
            for cat, data in self.predictions.items()
            if data.get("detected", False)
        ]
        violations.sort(key=lambda x: x["confidence"], reverse=True)
        return violations[:limit]


@dataclass
class GuildLHSSettings:
    """Guild-specific LHS configuration"""
    guild_id: int
    enabled: bool = False
    global_threshold: float = DEFAULT_LHS_THRESHOLD
    categories: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    exempt_roles: List[int] = field(default_factory=list)
    exempt_channels: List[int] = field(default_factory=list)
    exempt_users: List[int] = field(default_factory=list)
    action: str = "delete"
    severity: int = 2
    log_only_mode: bool = False
    channel_overrides: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    def __post_init__(self):
        # Initialize default categories if not set
        if not self.categories:
            self.categories = {
                cat: {"enabled": True, "threshold": self.global_threshold}
                for cat in ALL_LHS_CATEGORIES
            }
    
    def is_category_enabled(self, category: str, channel_id: Optional[int] = None) -> bool:
        """Check if a category is enabled, considering channel overrides"""
        # Check channel override first
        if channel_id and str(channel_id) in self.channel_overrides:
            channel_cats = self.channel_overrides[str(channel_id)].get("categories", {})
            if category in channel_cats:
                return channel_cats[category].get("enabled", True)
        
        # Fall back to global category setting
        cat_settings = self.categories.get(category, {})
        return cat_settings.get("enabled", True)
    
    def get_threshold(self, category: str, channel_id: Optional[int] = None) -> float:
        """Get threshold for a category, considering channel overrides"""
        # Check channel override first
        if channel_id and str(channel_id) in self.channel_overrides:
            channel_cats = self.channel_overrides[str(channel_id)].get("categories", {})
            if category in channel_cats:
                return channel_cats[category].get("threshold", self.global_threshold)
        
        # Fall back to global category setting
        cat_settings = self.categories.get(category, {})
        return cat_settings.get("threshold", self.global_threshold)
    
    def is_exempt(self, entity_id: int, entity_type: str) -> bool:
        """Check if an entity is exempt"""
        entity_id = int(entity_id)
        if entity_type == "role":
            return entity_id in self.exempt_roles
        elif entity_type == "channel":
            return entity_id in self.exempt_channels
        elif entity_type == "user":
            return entity_id in self.exempt_users
        return False
    
    def get_action(self, channel_id: Optional[int] = None) -> str:
        """Get action, considering channel overrides"""
        if channel_id and str(channel_id) in self.channel_overrides:
            return self.channel_overrides[str(channel_id)].get("action", self.action)
        return self.action
    
    def get_severity(self, channel_id: Optional[int] = None) -> int:
        """Get severity, considering channel overrides"""
        if channel_id and str(channel_id) in self.channel_overrides:
            return self.channel_overrides[str(channel_id)].get("severity", self.severity)
        return self.severity
    
    def is_log_only(self, channel_id: Optional[int] = None) -> bool:
        """Check if log only mode, considering channel overrides"""
        if channel_id and str(channel_id) in self.channel_overrides:
            return self.channel_overrides[str(channel_id)].get("log_only_mode", self.log_only_mode)
        return self.log_only_mode
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "guild_id": self.guild_id,
            "enabled": self.enabled,
            "global_threshold": self.global_threshold,
            "categories": self.categories,
            "exempt_roles": self.exempt_roles,
            "exempt_channels": self.exempt_channels,
            "exempt_users": self.exempt_users,
            "action": self.action,
            "severity": self.severity,
            "log_only_mode": self.log_only_mode,
            "channel_overrides": self.channel_overrides,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GuildLHSSettings":
        """Create from dictionary"""
        guild_id = data.get("guild_id", 0)
        
        # Handle categories properly
        categories = data.get("categories", {})
        if not categories:
            categories = {
                cat: {"enabled": True, "threshold": DEFAULT_LHS_THRESHOLD}
                for cat in ALL_LHS_CATEGORIES
            }
        
        return cls(
            guild_id=guild_id,
            enabled=data.get("enabled", False),
            global_threshold=data.get("global_threshold", DEFAULT_LHS_THRESHOLD),
            categories=categories,
            exempt_roles=data.get("exempt_roles", []),
            exempt_channels=data.get("exempt_channels", []),
            exempt_users=data.get("exempt_users", []),
            action=data.get("action", "delete"),
            severity=data.get("severity", 2),
            log_only_mode=data.get("log_only_mode", False),
            channel_overrides=data.get("channel_overrides", {}),
        )


class LHSClient:
    """Async HTTP client for LHS inference server"""
    
    DEFAULT_URL = "http://127.0.0.1:8000"
    
    def __init__(self, base_url: Optional[str] = None, timeout: float = 10.0):
        self.base_url = base_url or os.environ.get("LHS_SERVER_URL") or self.DEFAULT_URL
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={"Content-Type": "application/json"},
            )
        return self._session
    
    async def check_content(
        self,
        text: str,
        threshold: Optional[float] = None,
        categories: Optional[List[str]] = None,
    ) -> Optional[LHSCheckResult]:
        """
        Check content for harmful material
        
        Args:
            text: The text to analyze
            threshold: Optional threshold override (default: use model default)
            categories: Optional list of categories to check (default: all)
        
        Returns:
            LHSCheckResult if successful, None otherwise
        """
        try:
            session = await self._get_session()
            
            payload = {"text": text}
            if threshold is not None:
                payload["threshold"] = threshold
            
            async with session.post(
                f"{self.base_url}/predict",
                json=payload,
            ) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                
                # Filter by categories if specified
                predictions = data.get("predictions", {})
                if categories:
                    predictions = {
                        k: v for k, v in predictions.items()
                        if k in categories
                    }
                
                # Recompute is_harmful based on filtered predictions
                detected = [
                    cat for cat, pred in predictions.items()
                    if pred.get("detected", False)
                ]
                
                return LHSCheckResult(
                    is_harmful=len(detected) > 0,
                    detected_categories=detected,
                    predictions=predictions,
                    inference_time_ms=data.get("inference_time_ms", 0),
                )
        
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
    
    async def check_content_batch(
        self,
        texts: List[str],
        threshold: Optional[float] = None,
    ) -> Optional[List[LHSCheckResult]]:
        """
        Check multiple texts in batch
        
        Args:
            texts: List of texts to analyze
            threshold: Optional threshold override
        
        Returns:
            List of LHSCheckResult if successful, None otherwise
        """
        if not texts:
            return []
        
        try:
            session = await self._get_session()
            
            payload = {"texts": texts}
            if threshold is not None:
                payload["threshold"] = threshold
            
            async with session.post(
                f"{self.base_url}/predict_batch",
                json=payload,
            ) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                results = data.get("results", [])
                
                return [
                    LHSCheckResult(
                        is_harmful=len(r.get("detected_categories", [])) > 0,
                        detected_categories=r.get("detected_categories", []),
                        predictions=r.get("predictions", {}),
                        inference_time_ms=r.get("inference_time_ms", 0),
                    )
                    for r in results
                ]
        
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None
    
    async def health_check(self) -> Optional[Dict[str, Any]]:
        """Check if the inference server is healthy"""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/") as response:
                if response.status == 200:
                    return await response.json()
                return None
        except Exception:
            return None
    
    async def close(self):
        """Close the HTTP session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def check_with_settings(
        self,
        text: str,
        settings: GuildLHSSettings,
        channel_id: Optional[int] = None,
    ) -> Optional[LHSCheckResult]:
        """
        Check content with guild-specific settings
        
        This applies per-category thresholds and filters by enabled categories.
        """
        # Get all enabled categories
        enabled_categories = [
            cat for cat in ALL_LHS_CATEGORIES
            if settings.is_category_enabled(cat, channel_id)
        ]
        
        if not enabled_categories:
            return None
        
        # Use the minimum threshold among enabled categories for initial filtering
        # This ensures we catch everything that might be harmful
        min_threshold = min(
            settings.get_threshold(cat, channel_id)
            for cat in enabled_categories
        )
        
        result = await self.check_content(text, threshold=min_threshold)
        if not result:
            return None
        
        # Filter predictions by category settings
        filtered_predictions = {}
        filtered_detected = []
        
        for cat in enabled_categories:
            if cat in result.predictions:
                cat_threshold = settings.get_threshold(cat, channel_id)
                pred = result.predictions[cat]
                
                # Re-check with category-specific threshold
                is_detected = pred["confidence"] >= cat_threshold
                
                filtered_predictions[cat] = {
                    "detected": is_detected,
                    "confidence": pred["confidence"],
                }
                
                if is_detected:
                    filtered_detected.append(cat)
        
        return LHSCheckResult(
            is_harmful=len(filtered_detected) > 0,
            detected_categories=filtered_detected,
            predictions=filtered_predictions,
            inference_time_ms=result.inference_time_ms,
        )


# Global client instance
_lhs_client: Optional[LHSClient] = None


def get_lhs_client() -> LHSClient:
    """Get or create global LHS client"""
    global _lhs_client
    if _lhs_client is None:
        _lhs_client = LHSClient()
    return _lhs_client


def reset_lhs_client():
    """Reset the global client (useful for testing)"""
    global _lhs_client
    _lhs_client = None
