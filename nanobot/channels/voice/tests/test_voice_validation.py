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


def test_omitted_tts_voice_uses_runtime_default(monkeypatch) -> None:
    checked_voices: list[str] = []
    monkeypatch.setattr(
        voice_validation,
        "_module_available",
        lambda name: name in {"pvrecorder", "edge_tts"},
    )
    monkeypatch.setattr(
        voice_validation,
        "_edge_tts_voice_exists",
        lambda voice_name: checked_voices.append(voice_name) or True,
    )

    payload = voice_validation.validate({}, CONTEXT)

    assert checked_voices == ["en-US-AriaNeural"]
    assert _check(payload, "tts_voice")["status"] == "pass"
    assert payload["missing_fields"] == []


def test_empty_tts_voice_fails(monkeypatch) -> None:
    payload = _validate({"ttsVoice": ""}, monkeypatch, installed=("pvrecorder", "edge_tts"))

    voice_check = _check(payload, "tts_voice")
    assert voice_check["status"] == "fail"
    assert "cannot be empty" in voice_check["message"]


def test_missing_edge_tts_reports_dependency_error(monkeypatch) -> None:
    payload = _validate({"ttsVoice": "en-US-AriaNeural"}, monkeypatch, installed=("pvrecorder",))

    voice_check = _check(payload, "tts_voice")
    assert voice_check["status"] == "fail"
    assert "edge-tts is not installed" in voice_check["message"]


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
