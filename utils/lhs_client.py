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
DEFAULT_LHS_THRESHOLD = 0.65

# Default settings for a guild
# Image filter display names
IMAGE_FILTER_DISPLAY_NAMES = {
    "general": "General non-NSFW",
    "sensitive": "Sensitive",
    "questionable": "Questionable",
    "explicit": "Explicit",
    "guro": "Gore/Violence",
    "realistic": "Realistic",
    "csam_check": "CSAM Check",
}

# All image filter IDs
ALL_IMAGE_FILTERS = list(IMAGE_FILTER_DISPLAY_NAMES.keys())

# Default image filter settings (all disabled by default, each with its own action)
DEFAULT_IMAGE_FILTER_SETTINGS = {
    "general": {"enabled": False, "threshold": 0.2, "action": "delete"},
    "sensitive": {"enabled": False, "threshold": 0.8, "action": "delete"},
    "questionable": {"enabled": False, "threshold": 0.2, "action": "delete"},
    "explicit": {"enabled": False, "threshold": 0.2, "action": "delete"},
    "guro": {"enabled": False, "threshold": 0.3, "action": "delete"},
    "realistic": {"enabled": False, "threshold": 0.25, "action": "delete"},
    "csam_check": {"enabled": False, "threshold": 0.09, "action": "ban"},
}

DEFAULT_LHS_SETTINGS = {
    "enabled": False,
    "global_threshold": DEFAULT_LHS_THRESHOLD,
    "categories": {
        "dangerous_content": {"enabled": False, "threshold": DEFAULT_LHS_THRESHOLD},
        "hate_speech": {"enabled": False, "threshold": DEFAULT_LHS_THRESHOLD},
        "harassment": {"enabled": False, "threshold": DEFAULT_LHS_THRESHOLD},
        "sexually_explicit": {"enabled": False, "threshold": DEFAULT_LHS_THRESHOLD},
        "toxicity": {"enabled": False, "threshold": DEFAULT_LHS_THRESHOLD},
        "severe_toxicity": {"enabled": False, "threshold": DEFAULT_LHS_THRESHOLD},
        "threat": {"enabled": False, "threshold": DEFAULT_LHS_THRESHOLD},
        "insult": {"enabled": False, "threshold": DEFAULT_LHS_THRESHOLD},
        "identity_attack": {"enabled": False, "threshold": DEFAULT_LHS_THRESHOLD},
        "phish": {"enabled": False, "threshold": DEFAULT_LHS_THRESHOLD},
        "spam": {"enabled": False, "threshold": DEFAULT_LHS_THRESHOLD},
    },
    "exempt_roles": [],
    "exempt_channels": [],
    "exempt_users": [],
    "action": "delete",  # delete, warn, mute, kick, ban
    "severity": 2,  # 1-3
    "log_only_mode": False,  # If True, only logs without taking action
    "channel_overrides": {},  # Per-channel settings: {channel_id: {...}}
    # Image moderation settings (all disabled by default)
    "image_moderation": {
        "enabled": False,
        "scan_attachments": True,
        "scan_embeds": True,
        "filters": DEFAULT_IMAGE_FILTER_SETTINGS.copy(),
        "log_only_mode": False,
    },
}


@dataclass
class LHSCheckResult:
    """Result of an LHS content check - now works with raw probabilities"""
    is_harmful: bool
    detected_categories: List[str]
    predictions: Dict[str, Dict[str, Any]]  # category -> {detected, confidence}
    inference_time_ms: float
    logits: List[float] = field(default_factory=list)  # Raw logits
    probabilities: List[float] = field(default_factory=list)  # Raw probabilities
    
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
    image_moderation: Dict[str, Any] = field(default_factory=dict)
    
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
    
    # Image moderation helper methods
    def is_image_filter_enabled(self, filter_id: str) -> bool:
        """Check if an image filter is enabled"""
        img_settings = self.image_moderation or {}
        filters = img_settings.get("filters", {})
        filter_settings = filters.get(filter_id, {})
        return filter_settings.get("enabled", False)
    
    def get_image_filter_threshold(self, filter_id: str) -> float:
        """Get threshold for an image filter"""
        img_settings = self.image_moderation or {}
        filters = img_settings.get("filters", {})
        filter_settings = filters.get(filter_id, {})
        return filter_settings.get("threshold", DEFAULT_IMAGE_FILTER_SETTINGS.get(filter_id, {}).get("threshold", 0.2))
    
    def get_image_filter_action(self, filter_id: str) -> str:
        """Get action for a specific image filter"""
        img_settings = self.image_moderation or {}
        filters = img_settings.get("filters", {})
        filter_settings = filters.get(filter_id, {})
        return filter_settings.get("action", DEFAULT_IMAGE_FILTER_SETTINGS.get(filter_id, {}).get("action", "delete"))
    
    def is_image_log_only(self) -> bool:
        """Check if image moderation is in log only mode"""
        img_settings = self.image_moderation or {}
        return img_settings.get("log_only_mode", False)
    
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
            "image_moderation": self.image_moderation,
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
        
        # Get image_moderation with defaults (all filters disabled by default)
        img_defaults = {
            "enabled": False,
            "scan_attachments": True,
            "scan_embeds": True,
            "filters": DEFAULT_IMAGE_FILTER_SETTINGS.copy(),
            "log_only_mode": False,
        }
        
        stored_img_settings = data.get("image_moderation", {})
        # Merge filters, ensuring all filter IDs exist and have action field
        merged_filters = DEFAULT_IMAGE_FILTER_SETTINGS.copy()
        if "filters" in stored_img_settings:
            for filter_id in ALL_IMAGE_FILTERS:
                if filter_id in stored_img_settings["filters"]:
                    merged_filters[filter_id] = {
                        **DEFAULT_IMAGE_FILTER_SETTINGS[filter_id],
                        **stored_img_settings["filters"][filter_id]
                    }
        
        image_moderation = {
            **img_defaults,
            **stored_img_settings,
            "filters": merged_filters,
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
            image_moderation=image_moderation,
        )


class LHSClient:
    """Async HTTP client for LHS inference server"""
    
    DEFAULT_URL = "http://127.0.0.1:9000"
    
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
            
            # API no longer takes threshold - returns raw logits/probabilities
            payload = {"text": text}
            
            async with session.post(
                f"{self.base_url}/predict",
                json=payload,
            ) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                
                # Server now returns raw logits and probabilities
                logits = data.get("logits", [])
                probabilities = data.get("probabilities", [])
                
                # Build predictions dict from probabilities
                predictions = {}
                detected = []
                effective_threshold = threshold if threshold is not None else DEFAULT_LHS_THRESHOLD
                
                for i, cat in enumerate(ALL_LHS_CATEGORIES):
                    if i < len(probabilities):
                        is_detected = probabilities[i] >= effective_threshold
                        predictions[cat] = {
                            "detected": is_detected,
                            "confidence": probabilities[i],
                        }
                        if is_detected:
                            detected.append(cat)
                
                # Filter by categories if specified
                if categories:
                    predictions = {
                        k: v for k, v in predictions.items()
                        if k in categories
                    }
                    detected = [cat for cat in detected if cat in categories]
                
                return LHSCheckResult(
                    is_harmful=len(detected) > 0,
                    detected_categories=detected,
                    predictions=predictions,
                    inference_time_ms=data.get("inference_time_ms", 0),
                    logits=logits,
                    probabilities=probabilities,
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
            
            # API no longer takes threshold - returns raw logits/probabilities
            payload = {"texts": texts}
            
            async with session.post(
                f"{self.base_url}/predict_batch",
                json=payload,
            ) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                results = data.get("results", [])
                
                check_results = []
                effective_threshold = threshold if threshold is not None else DEFAULT_LHS_THRESHOLD
                
                for r in results:
                    probabilities = r.get("probabilities", [])
                    logits = r.get("logits", [])
                    label_names = r.get("label_names", ALL_LHS_CATEGORIES)
                    
                    # Build predictions dict from probabilities
                    predictions = {}
                    detected = []
                    
                    for i, cat in enumerate(label_names):
                        if i < len(probabilities):
                            is_detected = probabilities[i] >= effective_threshold
                            predictions[cat] = {
                                "detected": is_detected,
                                "confidence": probabilities[i],
                            }
                            if is_detected:
                                detected.append(cat)
                    
                    check_results.append(LHSCheckResult(
                        is_harmful=len(detected) > 0,
                        detected_categories=detected,
                        predictions=predictions,
                        inference_time_ms=r.get("inference_time_ms", 0),
                        logits=logits,
                        probabilities=probabilities,
                    ))
                
                return check_results
        
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
        
        # Get raw logits/probabilities from server (no threshold applied)
        result = await self.check_content(text)
        if not result:
            return None
        
        # Filter predictions by category settings
        filtered_predictions = {}
        filtered_detected = []
        
        for cat in enabled_categories:
            if cat in result.predictions:
                cat_threshold = settings.get_threshold(cat, channel_id)
                pred = result.predictions[cat]
                
                # Apply category-specific threshold
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
            logits=result.logits,
            probabilities=result.probabilities,
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
# Image moderation client
_image_client: Optional["ImageModerationClient"] = None


class ImageModerationClient:
    """HTTP client for the image moderation inference server v2"""
    
    DEFAULT_URL = "http://127.0.0.1:9001"
    
    # Image model constants (from image_moderation.py)
    CONTENT_RATINGS = ["general", "sensitive", "questionable", "explicit"]
    INDEX_GURO = 3664
    INDEX_REALISTIC = 1558
    INDEX_CSAM_CHECK = 299
    
    def __init__(self, base_url: Optional[str] = None, timeout: float = 30.0):
        self.base_url = base_url or os.environ.get("IMAGE_MODERATION_URL") or self.DEFAULT_URL
        self.timeout = timeout
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )
        return self._session
    
    def _analyze_probabilities(self, probabilities: List[float], thresholds: Dict[str, float]) -> Dict[str, Any]:
        """
        Analyze probabilities to determine content rating and flags.
        This mirrors the logic in image_moderation.py.
        """
        import numpy as np
        
        probs_arr = np.array(probabilities)
        
        # Get content rating probabilities (first 4)
        rating_probs = probs_arr[:4]
        
        # Get special flags
        guro_prob = float(probs_arr[self.INDEX_GURO])
        realistic_prob = float(probs_arr[self.INDEX_REALISTIC])
        csam_check_prob = float(probs_arr[self.INDEX_CSAM_CHECK])
        
        # Check for ambiguous (sum of ratings > threshold)
        ratings_sum = np.sum(rating_probs)
        ambiguous_threshold = thresholds.get("ambiguous_threshold", 1.5)
        is_ambiguous = ratings_sum > ambiguous_threshold
        
        # Check CSAM potential
        potential_csam = (
            csam_check_prob > thresholds.get("csam_check", 0.09) and
            realistic_prob > thresholds.get("realistic", 0.25)
        )
        
        # Determine content rating (if not ambiguous)
        content_rating = "general"
        confidence = 0.0
        is_nsfw = False
        
        if not is_ambiguous:
            # Check in order: explicit -> questionable -> general -> sensitive
            if rating_probs[3] > thresholds.get("explicit", 0.2):
                content_rating = "explicit"
                confidence = float(rating_probs[3])
                is_nsfw = True
            elif rating_probs[2] > thresholds.get("questionable", 0.2):
                content_rating = "questionable"
                confidence = float(rating_probs[2])
                is_nsfw = True
            elif rating_probs[0] > thresholds.get("general", 0.2):
                content_rating = "general"
                confidence = float(rating_probs[0])
            elif rating_probs[1] > thresholds.get("sensitive", 0.8):
                content_rating = "sensitive"
                confidence = float(rating_probs[1])
            else:
                # Fallback: pick highest
                max_idx = int(np.argmax(rating_probs))
                content_rating = self.CONTENT_RATINGS[max_idx]
                confidence = float(rating_probs[max_idx])
                is_nsfw = max_idx >= 2
        
        return {
            "is_nsfw": is_nsfw,
            "content_rating": content_rating,
            "confidence": confidence,
            "is_ambiguous": is_ambiguous,
            "is_guro": guro_prob > thresholds.get("guro", 0.3),
            "is_realistic": realistic_prob > thresholds.get("realistic", 0.25),
            "potential_csam": potential_csam,
            "guro_score": guro_prob,
            "realistic_score": realistic_prob,
            "csam_check_score": csam_check_prob,
            "probabilities": {
                "general": float(rating_probs[0]),
                "sensitive": float(rating_probs[1]),
                "questionable": float(rating_probs[2]),
                "explicit": float(rating_probs[3]),
            },
        }
    
    async def moderate_image(
        self,
        image_data: bytes,
        thresholds: Optional[Dict[str, float]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Moderate an image.
        
        Args:
            image_data: Raw image bytes
            thresholds: Dict of thresholds for each filter (applied client-side)
        
        Returns:
            Processed result with is_nsfw, content_rating, etc.
        """
        try:
            session = await self._get_session()
            
            data = aiohttp.FormData()
            data.add_field("file", image_data, filename="image.jpg")
            
            async with session.post(
                f"{self.base_url}/predict",  # New endpoint
                data=data,
            ) as response:
                if response.status != 200:
                    return None
                
                result = await response.json()
                # Server now returns probabilities (sigmoid applied), not raw logits
                probabilities = result.get("probabilities", [])
                
                if not probabilities:
                    return None
                
                # Apply thresholds client-side
                effective_thresholds = thresholds or {
                    "general": 0.2,
                    "sensitive": 0.8,
                    "questionable": 0.2,
                    "explicit": 0.2,
                    "guro": 0.3,
                    "realistic": 0.25,
                    "csam_check": 0.09,
                    "ambiguous_threshold": 1.5,
                }
                
                return self._analyze_probabilities(probabilities, effective_thresholds)
        
        except Exception:
            return None
    
    async def moderate_video(
        self,
        video_data: bytes,
        thresholds: Optional[Dict[str, float]] = None,
        num_frames: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """
        Moderate a video by sampling frames.
        Note: Video moderation is not yet implemented in v2 API.
        For now, returns None.
        """
        # TODO: Implement video moderation with frame sampling
        # This would require extracting frames client-side or server-side
        return None
    
    async def health_check(self) -> Optional[Dict[str, Any]]:
        """Check if the image moderation server is healthy"""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/") as response:
                if response.status == 200:
                    data = await response.json()
                    # Add version info
                    data["version"] = "2.0.0"
                    return data
                return None
        except Exception:
            return None
    
    async def close(self):
        """Close the HTTP session"""
        if self._session and not self._session.closed:
            await self._session.close()


def get_image_moderation_client() -> ImageModerationClient:
    """Get or create global image moderation client"""
    global _image_client
    if _image_client is None:
        _image_client = ImageModerationClient()
    return _image_client


def reset_image_moderation_client():
    """Reset the global image client (useful for testing)"""
    global _image_client
    _image_client = None
