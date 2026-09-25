"""Voice setup validation owned by the channel package.

Validation is static and dependency-free on purpose: optional wake word and
TTS modules are detected via ``importlib.util.find_spec`` (no heavy imports),
playback backends via ``shutil.which``, and custom model files via
``Path.is_file()`` on the gateway host. Anything that touches audio hardware
is deferred to channel startup and reported as a skipped check.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
from threading import Thread
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


def _await_if_needed(value: Any) -> Any:
    """Run awaitable values safely from a synchronous validation entrypoint."""
    if not inspect.isawaitable(value):
        return value

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)

    result: dict[str, Any] = {}

    def runner() -> None:
        result["value"] = asyncio.run(value)

    thread = Thread(target=runner)
    thread.start()
    thread.join()
    return result.get("value")


def _edge_tts_voice_exists(voice_name: str) -> bool:
    """Return whether the configured Edge TTS voice exists in the current library."""
    if not _module_available("edge_tts"):
        return False

    try:
        import edge_tts

        voices = _await_if_needed(edge_tts.list_voices())
        if not isinstance(voices, list):
            return False
        for voice in voices:
            name = voice.get("ShortName") or voice.get("Name")
            if name == voice_name:
                return True
        return False
    except Exception:
        return False


def _sensitivity_ok(value: Any) -> bool:
    """Mirror the runtime normalization: 0.0-1.0, or 0-100 scaled down."""
    try:
        return float(string_value(value).replace(",", ".")) >= 0
    except ValueError:
        return False


def _module_available(module: str) -> bool:
    """Check importability without importing (no SDK side effects)."""
    return importlib.util.find_spec(module) is not None


def _audio_device_index_ok(value: Any) -> bool:
    """Return whether the optional device index is a non-negative integer."""
    if value is None or value == "":
        return True
    try:
        return int(value) >= 0
    except (TypeError, ValueError):
        return False


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

    voice_name = string_value(values.get("ttsVoice"))
    if voice_name:
        if _edge_tts_voice_exists(voice_name):
            checks.append(
                check(
                    "tts_voice",
                    "Edge TTS voice",
                    "pass",
                    f"Voice '{voice_name}' is available in Edge TTS.",
                )
            )
        else:
            checks.append(
                check(
                    "tts_voice",
                    "Edge TTS voice",
                    "fail",
                    f"Voice '{voice_name}' was not found in the Edge TTS voice list.",
                )
            )
    else:
        checks.append(
            check(
                "tts_voice",
                "Edge TTS voice",
                "fail",
                f"ttsVoice is required. {_ENABLE_HINT}",
            )
        )

    audio_device_index = values.get("audioDeviceIndex")
    if audio_device_index is not None and audio_device_index != "":
        if _audio_device_index_ok(audio_device_index):
            checks.append(
                check(
                    "audio_device_index",
                    "Audio device index",
                    "pass",
                    "The audio device index is a non-negative integer.",
                )
            )
        else:
            checks.append(
                check(
                    "audio_device_index",
                    "Audio device index",
                    "fail",
                    "audioDeviceIndex must be an integer >= 0.",
                )
            )

    result = status_from_checks("voice", checks, missing)
    logger.info("Validation result: {}", result)
    return result


__all__ = ["validate"]
