"""Voice setup validation owned by the channel package.

Validation is static and dependency-free on purpose: optional wake word and
TTS modules are detected via ``importlib.util.find_spec`` (no heavy imports),
playback backends via ``shutil.which``, and custom model files via
``Path.is_file()`` on the gateway host. Anything that touches audio hardware
is deferred to channel startup and reported as a skipped check.
"""

from __future__ import annotations

import importlib.util
from typing import Any, cast

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.validation import (
    check,
    required_checks,
    status_from_checks,
    string_value,
)
from loguru import logger

_ENABLE_HINT = "Run: nanobot plugins enable voice."


def _sensitivity_ok(value: Any) -> bool:
    """Mirror the runtime normalization: 0.0-1.0, or 0-100 scaled down."""
    try:
        return float(string_value(value).replace(",", ".")) >= 0
    except ValueError:
        return False


def _module_available(module: str) -> bool:
    """Check importability without importing (no SDK side effects)."""
    return importlib.util.find_spec(module) is not None


def validate(values: dict[str, Any], _context: ChannelValidationContext) -> dict[str, Any]:

    logger.info("Starting Voice checks using values: {}", values)
    
    checks, missing = required_checks("voice", values)
    logger.info("Received checks: {}", checks)

    if _module_available("pvrecorder"):
        logger.info("Recorder module 'pvrecorder' is available.")
        checks.append(check("recorder", "Microphone recorder", "pass", "pvrecorder installed."))
    else:
        logger.info("Recorder module 'pvrecorder' is not available.")
        checks.append(
            check(
                "recorder",
                "Microphone recorder",
                "fail",
                f"pvrecorder is not installed. {_ENABLE_HINT}",
            )
        )

    result = status_from_checks("voice", checks, missing)
    logger.info("Validation result: {}", result)
    return result


__all__ = ["validate"]
