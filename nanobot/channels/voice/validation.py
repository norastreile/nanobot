"""Voice setup validation owned by the channel package.

Validation is static and dependency-free on purpose: optional wake word and
TTS modules are detected via ``importlib.util.find_spec`` (no heavy imports),
playback backends via ``shutil.which``, and custom model files via
``Path.is_file()`` on the gateway host. Anything that touches audio hardware
is deferred to channel startup and reported as a skipped check.
"""

from __future__ import annotations


from typing import Any, cast

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.validation import (
    check,
    required_checks,
    status_from_checks,
    string_value,
)
from loguru import logger


def _sensitivity_ok(value: Any) -> bool:
    """Mirror the runtime normalization: 0.0-1.0, or 0-100 scaled down."""
    try:
        return float(string_value(value).replace(",", ".")) >= 0
    except ValueError:
        return False


def validate(values: dict[str, Any], _context: ChannelValidationContext) -> dict[str, Any]:

    logger.info("Starting Voice checks")
    
    checks, missing = required_checks("voice", values)
    logger.info("Received checks: {}", checks)

    result = status_from_checks("voice", checks, missing)
    logger.info("Validation result: {}", result)
    return result


__all__ = ["validate"]
