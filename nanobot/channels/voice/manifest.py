"""Voice channel management contract."""

import platform

from nanobot.channels._manifest import field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

"""Voice Channel configuration."""
SETUP_SPEC = ChannelSetupSpec(
    fields={
        "tts_voice": field(kind="string", default="en-US-AriaNeural"),
        "wake_word_engine": field(kind="string", choices=("auto", "openwakeword", "porcupine"), default="auto"), # auto = openWakeWord with Porcupine fallback on 32-bit ARM
        "wake_word_models": field("list"), # wake words: built-in names (openwakeword: hey_jarvis/...; porcupine: jarvis/...) or custom model paths (.tflite / .ppn)
        "wake_word_sensitivities": field("list", default=["0.5"]), # detection thresholds (openWakeWord) / sensitivities (Porcupine), range 0.0 to 1.0
        "picovoice_access_key": field("secret"), # Picovoice API key, only needed for the Porcupine engine (32-bit ARM fallback)
        "porcupine_model": field("string"), # path to Porcupine speech model .pv file (language/base model), NOT a wake word keyword
        "audio_device_index": field(kind="int", default=1),
        "silence_threshold": field(kind="int", default=500),
        "silence_duration": field(kind="int", default=1500), #in milliseconds
        "max_recording_duration": field(kind="int", default=30), #in seconds
        "led_command": field(kind="string"),  # optional status LED shell command, status as $1
        "allowFrom": field("list"),
    },
    required=required_fields(),
    official_url="https://github.com/rhasspy/pyopen-wakeword",
)

# openWakeWord requires onnxruntime/litert, which ship no wheels for 32-bit
# ARM; Porcupine is the wake word engine fallback there. PEP 508 environment
# markers cannot be combined with a direct URL reference, so the gating happens
# at import time (the manifest is evaluated per host).
def _wake_word_dependencies() -> tuple[str, ...]:
    """Wake word engine dependencies for this machine."""
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64", "aarch64", "arm64"}:
        return ("pyopen-wakeword>=1.1.0,<2",)
    if machine in {"armv7l", "armv6l"}:
        return ("pvporcupine>=4.0.3,<5.0.0",)
    # Unknown platform (e.g. Windows ARM): install nothing extra; the channel
    # reports a clear error at start if no engine is importable.
    return ()


_WAKE_WORD_DEPENDENCIES = _wake_word_dependencies()

PLUGIN = ChannelPlugin(
    name="voice",
    display_name="Voice",
    runtime=f"{__package__}.runtime:VoiceChannel",
    setup=SETUP_SPEC,
    dependencies=_WAKE_WORD_DEPENDENCIES + ("pvrecorder>=1.2.7,<2.0.0", "edge-tts>=7.2.8,<8.0.0"),
    webui="webui/index.ts",
)
