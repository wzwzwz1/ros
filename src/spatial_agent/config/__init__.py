"""Configuration subpackage: strict runtime config schema and validation."""

from spatial_agent.config.schema import Profile, RuntimeConfig
from spatial_agent.config.validation import (
    CapabilityStatus,
    ValidationReport,
    validate_config,
    validate_config_file,
)

__all__ = [
    "CapabilityStatus",
    "Profile",
    "RuntimeConfig",
    "ValidationReport",
    "validate_config",
    "validate_config_file",
]
