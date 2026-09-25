"""Voice setup validation owned by the channel package.

Validation is static and dependency-free on purpose: optional wake word and
TTS modules are detected via ``importlib.util.find_spec`` (no heavy imports),
playback backends via ``shutil.which``, and custom model files via
``Path.is_file()`` on the gateway host. Anything that touches audio hardware
is deferred to channel startup and reported as a skipped check.
"""

from __future__ import annotations

import importlib.util
import platform
import shutil
from pathlib import Path
from typing import Any, cast

from nanobot.channels.contracts import ChannelValidationContext
from nanobot.channels.validation import (
    check,
    int_value,
    required_checks,
    status_from_checks,
    string_value,
)


def _sensitivity_ok(value: Any) -> bool:
    """Mirror the runtime normalization: 0.0-1.0, or 0-100 scaled down."""
    try:
        return float(string_value(value).replace(",", ".")) >= 0
    except ValueError:
        return False


def validate(values: dict[str, Any], _context: ChannelValidationContext) -> dict[str, Any]:
    checks, missing = required_checks("voice", values)

    raw_sensitivities = cast("list[Any]", values.get("wakeWordSensitivities") or [])
    sensitivities = [
        string_value(value) for value in raw_sensitivities if string_value(value)
    ]
    invalid = [value for value in sensitivities if not _sensitivity_ok(value)]
    if invalid:
        checks.append(
            check(
                "sensitivities",
                "Wake word sensitivities",
                "fail",
                "Not a valid sensitivity (0.0 to 1.0, comma accepted): " + ", ".join(invalid),
            )
        )
    elif sensitivities:
        checks.append(
            check("sensitivities", "Wake word sensitivities", "pass", "All sensitivities parse.")
        )
    else:
        checks.append(
            check(
                "sensitivities",
                "Wake word sensitivities",
                "skipped",
                "Unset; every wake word uses 0.5.",
            )
        )

    return status_from_checks("voice", checks, missing)


__all__ = ["validate"]
