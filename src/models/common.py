from enum import Enum


class SkillLevel(str, Enum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"
    EXPERT = "expert"
    UNKNOWN = "unknown"


class RequirementImportance(str, Enum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    NICE_TO_HAVE = "nice_to_have"


class ConfidenceTier(str, Enum):
    LOW = "low"            # 0.00 - 0.49
    MEDIUM = "medium"      # 0.50 - 0.74
    HIGH = "high"          # 0.75 - 0.89
    VERY_HIGH = "very_high"# 0.90 - 1.00


def get_confidence_tier(score: float) -> ConfidenceTier:
    if score < 0.50:
        return ConfidenceTier.LOW
    elif score < 0.75:
        return ConfidenceTier.MEDIUM
    elif score < 0.90:
        return ConfidenceTier.HIGH
    else:
        return ConfidenceTier.VERY_HIGH
