"""Tests for the voice channel setup validation."""

import nanobot.channels.voice.validation as voice_validation
from nanobot.channels.contracts import ChannelValidationContext

CONTEXT = ChannelValidationContext()
_GOOD_MODULES = ("pyopen_wakeword", "numpy", "pvrecorder", "edge_tts")


def _validate(values: dict, monkeypatch=None, installed: tuple[str, ...] = _GOOD_MODULES) -> dict:
    if monkeypatch is not None:
        monkeypatch.setattr(
            voice_validation.importlib.util,
            "find_spec",
            lambda name: object() if name in installed else None,
        )
    return voice_validation.validate(values, CONTEXT)


def _check(payload: dict, check_id: str) -> dict:
    return next(c for c in payload["checks"] if c["id"] == check_id)


_GOOD_VALUES = {
    "ttsVoice": "en-US-AriaNeural",
    "wakeWordEngine": "openwakeword",
    "wakeWordModels": ["hey_jarvis"],
    "wakeWordSensitivities": ["0,5"],
    "audioDeviceIndex": 1,
}


def test_missing_tts_voice_reports_needs_setup(monkeypatch) -> None:
    payload = _validate({}, monkeypatch)
    assert payload["status"] == "needs_setup"
    assert payload["missing_fields"] == ["ttsVoice"]
    assert payload["can_enable"] is False


def test_ready_configuration_is_configured(monkeypatch) -> None:
    monkeypatch.setattr(voice_validation.shutil, "which", lambda name: "/usr/bin/mpv")
    payload = _validate(dict(_GOOD_VALUES), monkeypatch)
    assert payload["status"] == "configured"
    assert payload["can_enable"] is True
    assert not [c for c in payload["checks"] if c["status"] == "fail"]
    assert _check(payload, "engine")["message"] == "openWakeWord installed."
    assert _check(payload, "wake_words")["status"] == "skipped"
    assert _check(payload, "sensitivities")["status"] == "pass"
    assert _check(payload, "audio_player")["message"] == "mpv found."


def test_auto_engine_prefers_installed_openwakeword(monkeypatch) -> None:
    values = {"ttsVoice": "en-US-AriaNeural"}
    payload = _validate(values, monkeypatch)
    assert _check(payload, "engine")["status"] == "pass"
    assert "openWakeWord" in _check(payload, "engine")["message"]


def test_auto_engine_falls_back_to_porcupine(monkeypatch) -> None:
    values = {"ttsVoice": "en-US-AriaNeural"}
    payload = _validate(values, monkeypatch, installed=("pvporcupine", "pvrecorder", "edge_tts"))
    engine = _check(payload, "engine")
    assert engine["status"] == "pass"
    assert "Porcupine" in engine["message"]


def test_auto_engine_without_any_engine_fails(monkeypatch) -> None:
    payload = _validate({"ttsVoice": "en-US-AriaNeural"}, monkeypatch, installed=())
    engine = _check(payload, "engine")
    assert engine["status"] == "fail"
    assert "Neither openWakeWord nor Porcupine" in engine["message"]


def test_explicit_engine_missing_suggests_auto(monkeypatch) -> None:
    values = {"ttsVoice": "en-US-AriaNeural", "wakeWordEngine": "porcupine"}
    payload = _validate(values, monkeypatch)
    engine = _check(payload, "engine")
    assert engine["status"] == "fail"
    assert "set wakeWordEngine to 'auto'" in engine["message"]


def test_invalid_engine_value_fails() -> None:
    payload = voice_validation.validate(
        {"ttsVoice": "en-US-AriaNeural", "wakeWordEngine": "snowboy"}, CONTEXT
    )
    engine = _check(payload, "engine")
    assert engine["status"] == "fail"
    assert "Invalid wakeWordEngine" in engine["message"]


def test_missing_recorder_or_tts_fails_with_enable_hint(monkeypatch) -> None:
    payload = _validate(dict(_GOOD_VALUES), monkeypatch, installed=("pyopen_wakeword", "numpy"))
    assert _check(payload, "recorder")["status"] == "fail"
    assert _check(payload, "tts")["status"] == "fail"
    assert "nanobot plugins enable voice" in _check(payload, "tts")["message"]


def test_missing_audio_player_fails(monkeypatch) -> None:
    monkeypatch.setattr(voice_validation.shutil, "which", lambda name: None)
    payload = _validate(dict(_GOOD_VALUES), monkeypatch)
    player = _check(payload, "audio_player")
    assert player["status"] == "fail"
    assert "Install mpv" in player["message"]


def test_missing_model_file_fails(tmp_path) -> None:
    values = dict(_GOOD_VALUES, wakeWordModels=[str(tmp_path / "nope.tflite")])
    payload = voice_validation.validate(values, CONTEXT)
    wake_words = _check(payload, "wake_words")
    assert wake_words["status"] == "fail"
    assert "not found on the gateway host" in wake_words["message"]


def test_existing_model_file_passes(tmp_path) -> None:
    model = tmp_path / "custom.tflite"
    model.write_bytes(b"fake")
    values = dict(_GOOD_VALUES, wakeWordModels=[str(model)])
    payload = voice_validation.validate(values, CONTEXT)
    assert _check(payload, "wake_words")["status"] == "pass"


def test_invalid_sensitivity_fails() -> None:
    values = dict(_GOOD_VALUES, wakeWordSensitivities=["abc"])
    payload = voice_validation.validate(values, CONTEXT)
    sensitivities = _check(payload, "sensitivities")
    assert sensitivities["status"] == "fail"
    assert "abc" in sensitivities["message"]


def test_negative_audio_device_index_fails() -> None:
    values = dict(_GOOD_VALUES, audioDeviceIndex=-1)
    payload = voice_validation.validate(values, CONTEXT)
    assert _check(payload, "audio_device")["status"] == "fail"


def test_live_audio_checks_are_skipped(monkeypatch) -> None:
    payload = _validate(dict(_GOOD_VALUES), monkeypatch)
    manual = _check(payload, "manual_review")
    assert manual["status"] == "skipped"
    assert "when the channel starts" in manual["message"]
    device = _check(payload, "audio_device")
    assert device["status"] == "skipped"
