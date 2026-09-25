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

_ENGINE_MODULES = {
    "openwakeword": ("pyopen_wakeword", "numpy"),
    "porcupine": ("pvporcupine",),
}
_ENGINE_LABELS = {"openwakeword": "openWakeWord", "porcupine": "Porcupine"}
_ENABLE_HINT = "Run: nanobot plugins enable voice."


def _module_available(module: str) -> bool:
    """Check importability without importing (no SDK side effects)."""
    return importlib.util.find_spec(module) is not None


def _auto_engines() -> tuple[str, ...]:
    """Engines the manifest would install on this machine, in preference order."""
    machine = platform.machine().lower()
    if machine in {"armv7l", "armv6l"}:
        # openWakeWord ships no wheels for 32-bit ARM; Porcupine is the fallback.
        return ("porcupine",)
    return ("openwakeword", "porcupine")


def _sensitivity_ok(value: Any) -> bool:
    """Mirror the runtime normalization: 0.0-1.0, or 0-100 scaled down."""
    try:
        return float(string_value(value).replace(",", ".")) >= 0
    except ValueError:
        return False


def validate(values: dict[str, Any], _context: ChannelValidationContext) -> dict[str, Any]:
    checks, missing = required_checks("voice", values)

    requested = string_value(values.get("wakeWordEngine")).lower() or "auto"
    if requested != "auto" and requested not in _ENGINE_MODULES:
        checks.append(
            check(
                "engine",
                "Wake word engine",
                "fail",
                f"Invalid wakeWordEngine '{requested}': use 'auto', 'openwakeword' or 'porcupine'.",
            )
        )
    else:
        engines = (requested,) if requested in _ENGINE_MODULES else _auto_engines()
        installed = [
            name
            for name in engines
            if all(_module_available(module) for module in _ENGINE_MODULES[name])
        ]
        if installed:
            labels = " or ".join(_ENGINE_LABELS[name] for name in installed)
            checks.append(check("engine", "Wake word engine", "pass", f"{labels} installed."))
        elif requested == "auto":
            checks.append(
                check(
                    "engine",
                    "Wake word engine",
                    "fail",
                    f"Neither openWakeWord nor Porcupine is installed. {_ENABLE_HINT}",
                )
            )
        else:
            checks.append(
                check(
                    "engine",
                    "Wake word engine",
                    "fail",
                    f"{_ENGINE_LABELS[requested]} is not installed; "
                    f"install it or set wakeWordEngine to 'auto'. {_ENABLE_HINT}",
                )
            )

    if _module_available("pvrecorder"):
        checks.append(check("recorder", "Microphone recorder", "pass", "pvrecorder installed."))
    else:
        checks.append(
            check(
                "recorder",
                "Microphone recorder",
                "fail",
                f"pvrecorder is not installed. {_ENABLE_HINT}",
            )
        )

    if _module_available("edge_tts"):
        checks.append(check("tts", "Text-to-speech", "pass", "edge-tts installed."))
    else:
        checks.append(
            check("tts", "Text-to-speech", "fail", f"edge-tts is not installed. {_ENABLE_HINT}")
        )

    if shutil.which("mpv"):
        checks.append(check("audio_player", "Audio player", "pass", "mpv found."))
    elif shutil.which("ffmpeg") and (shutil.which("aplay") or shutil.which("paplay")):
        checks.append(
            check("audio_player", "Audio player", "pass", "ffmpeg with aplay/paplay found.")
        )
    else:
        checks.append(
            check(
                "audio_player",
                "Audio player",
                "fail",
                "No audio player found. Install mpv, or ffmpeg together with "
                "alsa-utils (aplay) or pulseaudio-utils (paplay).",
            )
        )

    raw_models = cast("list[Any]", values.get("wakeWordModels") or [])
    entries = [string_value(entry) for entry in raw_models if string_value(entry)]
    if not entries:
        checks.append(
            check("wake_words", "Wake words", "skipped", "All built-in wake words will be used.")
        )
    else:
        missing_files = [
            entry
            for entry in entries
            if entry.lower().endswith(".tflite") and not Path(entry).is_file()
        ]
        if missing_files:
            checks.append(
                check(
                    "wake_words",
                    "Wake words",
                    "fail",
                    "Wake word model file not found on the gateway host: "
                    + ", ".join(missing_files),
                )
            )
        elif any(entry.lower().endswith(".tflite") for entry in entries):
            checks.append(
                check("wake_words", "Wake words", "pass", "Custom wake word model files found.")
            )
        else:
            checks.append(
                check(
                    "wake_words",
                    "Wake words",
                    "skipped",
                    "Built-in wake word names are verified when the channel starts.",
                )
            )

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

    device = int_value(values.get("audioDeviceIndex"))
    if device is not None and device < 0:
        checks.append(
            check(
                "audio_device",
                "Audio device index",
                "fail",
                "Set audioDeviceIndex to a whole number of 0 or more.",
            )
        )
    else:
        index = device if device is not None else 1
        checks.append(
            check(
                "audio_device",
                "Audio device index",
                "skipped",
                f"Microphone availability for device index {index} is verified "
                "when the channel starts.",
            )
        )

    checks.append(
        check(
            "manual_review",
            "Microphone and LED",
            "skipped",
            "Live wake word detection, recording, and LED output are verified "
            "when the channel starts.",
        )
    )

    return status_from_checks("voice", checks, missing)


__all__ = ["validate"]
