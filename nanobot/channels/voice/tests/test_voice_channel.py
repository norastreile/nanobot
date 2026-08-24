"""Essential tests for the voice channel."""

import asyncio
import wave

import pytest

from nanobot.bus.queue import MessageBus
from nanobot.channels.voice.runtime import VoiceChannel, VoiceConfig
from nanobot.channels.voice.status import (
    CommandStatusListener,
    VoiceStatus,
    VoiceStatusEmitter,
)


def make_channel(config: dict | None = None) -> VoiceChannel:
    return VoiceChannel(config or {}, MessageBus())


def test_default_config() -> None:
    defaults = VoiceChannel.default_config()
    assert defaults["enabled"] is False
    assert defaults["wakeWordKeywords"] == ["nano"]
    assert defaults["wakeWordSensitivities"] == ["0.5"]
    assert defaults["ttsVoice"] == "en-US-AriaNeural"
    assert defaults["silenceDuration"] == 1500


def test_config_accepts_camel_case_keys() -> None:
    config = VoiceConfig.model_validate(
        {
            "picovoiceAccessKey": "test-key",
            "allowFrom": ["*"],
            "silenceDuration": 2000,
        }
    )
    assert config.picovoice_access_key == "test-key"
    assert config.allow_from == ["*"]
    assert config.silence_duration == 2000
    # unset fields keep their defaults
    assert config.wake_word_keywords == ["nano"]


def test_safe_float_normalizes_percent_values() -> None:
    # Porcupine expects 0.0-1.0; legacy 0-100 input is scaled down.
    assert VoiceChannel._safe_float("0.5") == 0.5
    assert VoiceChannel._safe_float("100") == 1.0
    assert VoiceChannel._safe_float("50") == 0.5
    # comma as decimal separator is accepted
    assert VoiceChannel._safe_float("0,5") == 0.5
    assert VoiceChannel._safe_float("1,0") == 1.0
    # invalid input falls back to 0.5
    assert VoiceChannel._safe_float("not-a-number") == 0.5
    assert VoiceChannel._safe_float(None) == 0.5


def test_save_wav(tmp_path) -> None:
    channel = make_channel({"audio_device_index": 1})
    path = tmp_path / "out.wav"
    audio = [0, 100, -100, 500]
    channel._save_wav(path, audio)

    with wave.open(str(path), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == channel._sample_rate
        assert wf.getnframes() == len(audio)


async def test_send_ignores_empty_messages() -> None:
    channel = make_channel()

    # Must not raise or attempt TTS for empty content
    from nanobot.bus.events import OutboundMessage

    await channel.send(OutboundMessage(channel="voice", chat_id="voice", content=""))
    await channel.send(
        OutboundMessage(channel="voice", chat_id="voice", content="[empty message]")
    )


def test_is_allowed_uses_allow_from() -> None:
    channel = make_channel({"allowFrom": ["voice_user"]})
    assert channel.is_allowed("voice_user")
    assert not channel.is_allowed("stranger")


# --- TTS tests (skipped when edge-tts is not installed or offline) ---

pytest.importorskip("edge_tts", reason="edge-tts not installed (pip install edge-tts)")

import edge_tts  # noqa: E402


async def _tts_available() -> bool:
    """Return False when the Edge TTS service is unreachable."""
    try:
        communicate = edge_tts.Communicate("Test", "en-US-AriaNeural")
        await communicate.save("/dev/null")
        return True
    except Exception:
        return False


async def test_edge_tts_generates_audio(tmp_path) -> None:
    if not await _tts_available():
        pytest.skip("Edge TTS service unreachable (offline?)")

    out = tmp_path / "test.mp3"
    communicate = edge_tts.Communicate("Hallo Welt", VoiceConfig().tts_voice)
    await communicate.save(str(out))
    assert out.stat().st_size > 0


async def test_speak_completes_without_audio_player(monkeypatch) -> None:
    if not await _tts_available():
        pytest.skip("Edge TTS service unreachable (offline?)")

    # Simulate a system without mpv/ffmpeg/aplay: _speak must not raise.
    async def fail_exec(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fail_exec)
    channel = make_channel()
    await channel._speak("Hallo Welt")


# --- Status emitter / LED listener ---


async def test_emitter_notifies_listeners() -> None:
    received: list[VoiceStatus] = []

    class _Listener:
        async def on_voice_status(self, status: VoiceStatus) -> None:
            received.append(status)

    emitter = VoiceStatusEmitter()
    emitter.add_listener(_Listener())
    await emitter.emit(VoiceStatus.RECORDING)
    await emitter.emit(VoiceStatus.SPEAKING)

    assert received == [VoiceStatus.RECORDING, VoiceStatus.SPEAKING]


async def test_emitter_isolates_listener_failures() -> None:
    ok_statuses: list[VoiceStatus] = []

    class _Broken:
        async def on_voice_status(self, status: VoiceStatus) -> None:
            raise RuntimeError("LED hardware gone")

    class _Ok:
        async def on_voice_status(self, status: VoiceStatus) -> None:
            ok_statuses.append(status)

    emitter = VoiceStatusEmitter()
    emitter.add_listener(_Broken())
    emitter.add_listener(_Ok())

    await emitter.emit(VoiceStatus.THINKING)  # must not raise
    assert ok_statuses == [VoiceStatus.THINKING]


async def test_command_listener_receives_status_as_arg(tmp_path) -> None:
    out = tmp_path / "statuses.txt"
    listener = CommandStatusListener(f'echo "$1" >> {out}')

    await listener.on_voice_status(VoiceStatus.RECORDING)
    await listener.on_voice_status(VoiceStatus.LISTENING_WAKE_WORD)

    assert out.read_text().splitlines() == ["recording", "listening_wake_word"]


def test_channel_registers_led_listener_from_config() -> None:
    channel = make_channel({"led_command": "true"})
    assert len(channel.status_emitter._listeners) == 1

    plain = make_channel()
    assert plain.status_emitter._listeners == []

