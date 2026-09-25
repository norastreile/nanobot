"""Tests for the voice channel setup validation."""

from __future__ import annotations

from typing import Any

from nanobot.channels.contracts import ChannelValidationContext
import nanobot.channels.voice.validation as voice_validation

CONTEXT = ChannelValidationContext()


def _check(payload: dict[str, Any], check_id: str) -> dict[str, Any]:
    return next(check for check in payload["checks"] if check["id"] == check_id)


def _validate(values: dict[str, Any], monkeypatch=None, *, installed: tuple[str, ...] = ()) -> dict[str, Any]:
    if monkeypatch is not None:
        monkeypatch.setattr(
            voice_validation,
            "_module_available",
            lambda name: name in installed,
        )
    return voice_validation.validate(values, CONTEXT)


def test_missing_tts_voice_reports_needs_setup(monkeypatch) -> None:
    payload = _validate({"wakeWordModels": ["hey_jarvis"]}, monkeypatch, installed=("pvrecorder", "edge_tts"))
    assert payload["status"] == "needs_setup"
    assert payload["missing_fields"] == ["ttsVoice"]
    assert payload["can_enable"] is False


def test_valid_voice_and_device_index_passes(monkeypatch) -> None:
    monkeypatch.setattr(
        voice_validation,
        "_module_available",
        lambda name: name in {"pvrecorder", "edge_tts"},
    )
    monkeypatch.setattr(
        voice_validation,
        "_edge_tts_voice_exists",
        lambda _voice_name: True,
    )

    payload = voice_validation.validate(
        {
            "ttsVoice": "en-US-AriaNeural",
            "audioDeviceIndex": 1,
        },
        CONTEXT,
    )

    assert _check(payload, "tts_voice")["status"] == "pass"
    assert _check(payload, "audio_device_index")["status"] == "pass"


def test_negative_audio_device_index_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        voice_validation,
        "_module_available",
        lambda name: name in {"pvrecorder", "edge_tts"},
    )
    monkeypatch.setattr(
        voice_validation,
        "_edge_tts_voice_exists",
        lambda _voice_name: True,
    )

    payload = voice_validation.validate(
        {
            "ttsVoice": "en-US-AriaNeural",
            "audioDeviceIndex": -1,
        },
        CONTEXT,
    )

    audio_index = _check(payload, "audio_device_index")
    assert audio_index["status"] == "fail"
    assert "integer >= 0" in audio_index["message"]
