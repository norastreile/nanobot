"""Essential tests for the voice channel."""

import asyncio
import wave

import pytest

import nanobot.channels.voice.runtime as voice_runtime
from nanobot.bus.queue import MessageBus
from nanobot.channels.voice.runtime import SPEAKER_ID, VoiceChannel, VoiceConfig
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
    assert defaults["wakeWordEngine"] == "auto"
    assert defaults["wakeWordModels"] == []
    assert defaults["wakeWordSensitivities"] == ["0.5"]
    assert defaults["ttsVoice"] == "en-US-AriaNeural"
    assert defaults["silenceDuration"] == 1500


def test_config_accepts_camel_case_keys() -> None:
    config = VoiceConfig.model_validate(
        {
            "wakeWordModels": ["/tmp/custom_model.tflite"],
            "allowFrom": ["*"],
            "silenceDuration": 2000,
        }
    )
    assert config.wake_word_models == ["/tmp/custom_model.tflite"]
    assert config.allow_from == ["*"]
    assert config.silence_duration == 2000
    # unset fields keep their defaults


def test_safe_float_normalizes_percent_values() -> None:
    # openWakeWord scores are 0.0-1.0; legacy 0-100 input is scaled down.
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
    channel = make_channel({"allowFrom": [SPEAKER_ID]})
    assert channel.is_allowed(SPEAKER_ID)
    assert not channel.is_allowed("stranger")


def test_inbound_message_uses_speaker_id() -> None:
    assert SPEAKER_ID == "local_speaker"


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

    # cmd.exe (Windows) echoes the quotes of "$1" and may keep trailing
    # whitespace; normalize both so the assertion holds on POSIX sh and
    # cmd.exe alike.
    lines = [line.strip().strip('"').strip() for line in out.read_text().splitlines()]
    assert lines == ["recording", "listening_wake_word"]


def test_channel_registers_led_listener_from_config() -> None:
    channel = make_channel({"led_command": "true"})
    assert len(channel.status_emitter._listeners) == 1

    plain = make_channel()
    assert plain.status_emitter._listeners == []



# --- Wake word engine selection ---


def test_resolve_engine_auto_prefers_openwakeword(monkeypatch) -> None:
    channel = make_channel()
    assert channel._resolve_engine() == "openwakeword"


def test_resolve_engine_auto_falls_back_to_porcupine(monkeypatch) -> None:
    monkeypatch.setattr(voice_runtime, "OpenWakeWord", None)
    monkeypatch.setattr(voice_runtime, "OpenWakeWordFeatures", None)
    monkeypatch.setattr(voice_runtime, "np", None)
    monkeypatch.setattr(voice_runtime, "BuiltinWakeWordModel", None)
    if voice_runtime.pvporcupine is None:
        pytest.skip("pvporcupine not installed")
    channel = make_channel()
    assert channel._resolve_engine() == "porcupine"


def test_resolve_engine_none_logs_error(monkeypatch, caplog) -> None:
    monkeypatch.setattr(voice_runtime, "OpenWakeWord", None)
    monkeypatch.setattr(voice_runtime, "OpenWakeWordFeatures", None)
    monkeypatch.setattr(voice_runtime, "np", None)
    monkeypatch.setattr(voice_runtime, "BuiltinWakeWordModel", None)
    monkeypatch.setattr(voice_runtime, "pvporcupine", None)
    channel = make_channel()
    assert channel._resolve_engine() == ""


def test_resolve_engine_explicit_porcupine(monkeypatch) -> None:
    if voice_runtime.pvporcupine is None:
        pytest.skip("pvporcupine not installed")
    channel = make_channel({"wakeWordEngine": "porcupine"})
    assert channel._resolve_engine() == "porcupine"


def test_resolve_engine_invalid_value(monkeypatch) -> None:
    channel = make_channel({"wakeWordEngine": "snowboy"})
    assert channel._resolve_engine() == ""


def test_setup_porcupine_rejects_pvporcupine_2() -> None:
    if voice_runtime.pvporcupine is None:
        pytest.skip("pvporcupine not installed")
    channel = make_channel({"wakeWordEngine": "porcupine"})
    with pytest.raises(ValueError, match="pvporcupine==1.9.5"):
        channel._setup_porcupine()



async def test_setup_openwakeword_loads_builtin_models() -> None:
    if voice_runtime.OpenWakeWord is None:
        pytest.skip("pyopen-wakeword not installed")
    channel = make_channel({"wakeWordModels": ["hey_jarvis"]})
    await channel._setup_openwakeword()
    assert list(channel._words) == ["hey_jarvis"]
    assert channel._model_thresholds == {"hey_jarvis": 0.5}
    # detection on silence must not fire
    import numpy as np

    assert channel._detect_wake_word(np.zeros(1280, dtype=np.int16)) is False
    channel._reset_openwakeword_state()
    channel._features.close()


def test_setup_porcupine_empty_wake_words_uses_all_builtin(monkeypatch) -> None:
    if voice_runtime.pvporcupine is None:
        pytest.skip("pvporcupine not installed")
    # simulate the keyless pvporcupine 1.9.5 (as installed on 32-bit ARM)
    monkeypatch.setattr(voice_runtime, "_porcupine_requires_access_key", lambda m: False)
    captured: dict = {}

    class FakePorcupine:
        sample_rate = 16000
        frame_length = 512

    def fake_create(**kwargs):
        captured.update(kwargs)
        return FakePorcupine()

    monkeypatch.setattr(voice_runtime.pvporcupine, "create", fake_create)
    channel = make_channel({"wakeWordEngine": "porcupine"})
    channel._setup_porcupine()
    assert len(captured["keyword_paths"]) == len(voice_runtime.pvporcupine.KEYWORD_PATHS)
    assert len(captured["sensitivities"]) == len(captured["keyword_paths"])


def test_setup_porcupine_resolves_builtin_and_ppn(monkeypatch, tmp_path) -> None:
    if voice_runtime.pvporcupine is None:
        pytest.skip("pvporcupine not installed")
    monkeypatch.setattr(voice_runtime, "_porcupine_requires_access_key", lambda m: False)
    captured: dict = {}

    class FakePorcupine:
        sample_rate = 16000
        frame_length = 512

    def fake_create(**kwargs):
        captured.update(kwargs)
        return FakePorcupine()

    monkeypatch.setattr(voice_runtime.pvporcupine, "create", fake_create)

    ppn = tmp_path / "custom.ppn"
    ppn.write_bytes(b"fake")
    channel = make_channel(
        {
            "wakeWordEngine": "porcupine",
            "wakeWordModels": ["JARVIS", str(ppn)],
        }
    )
    channel._setup_porcupine()
    # keyless pvporcupine 1.9.5: no access_key may be passed
    assert "access_key" not in captured
    keyword_paths = captured["keyword_paths"]
    assert len(keyword_paths) == 2
    assert keyword_paths[0].endswith("jarvis_linux.ppn")
    assert keyword_paths[1] == str(ppn)
    assert channel._frame_length == 512


def test_setup_porcupine_unknown_builtin_keyword(monkeypatch, tmp_path) -> None:
    if voice_runtime.pvporcupine is None:
        pytest.skip("pvporcupine not installed")
    monkeypatch.setattr(voice_runtime, "_porcupine_requires_access_key", lambda m: False)
    channel = make_channel(
        {
            "wakeWordEngine": "porcupine",
            "wakeWordModels": ["nosuchkeyword"],
        }
    )
    with pytest.raises(ValueError, match="Unknown built-in Porcupine keyword"):
        channel._setup_porcupine()
