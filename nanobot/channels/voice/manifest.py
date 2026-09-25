"""Voice channel management contract."""

from nanobot.channels._manifest import field, required
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.voice.validation import validate

"""Voice Channel configuration."""
SETUP_SPEC = ChannelSetupSpec(
    fields={
        "ttsVoice": field(kind="string", default="en-US-AriaNeural"),
        "wakeWordEngine": field(
            kind="string",
            choices=("auto", "openwakeword", "porcupine"),
            default="auto",
        ),  # auto = openWakeWord with Porcupine fallback on 32-bit ARM
        "wakeWordModels": field("list"),  # wake words: built-in names (openwakeword: hey_jarvis/...; porcupine: jarvis/...) or custom .tflite model paths
        "wakeWordSensitivities": field("list", default=["0.5"]),  # detection thresholds/sensitivities, range 0.0 to 1.0
        "audioDeviceIndex": field(kind="int", default=1),
        "silenceThreshold": field(kind="int", default=500),
        "silenceDuration": field(kind="int", default=1500),  # in milliseconds
        "maxRecordingDuration": field(kind="int", default=30),  # in seconds
        "ledCommand": field("string"),  # optional status LED shell command, status as $1
        "allowFrom": field("list"),
    },
    required=(required("ttsVoice"),),
    official_url="https://github.com/rhasspy/pyopen-wakeword",
    validator=validate,
)

# Wake word engine dependencies are gated at manifest import time (the
# manifest is evaluated per host): openWakeWord requires onnxruntime/litert,
# which ship no wheels for 32-bit ARM; there Porcupine is the wake word engine
# fallback (1.9.5 is the last keyless release, no Picovoice registration
# needed). The platform import lives inside the function because manifests may
# only import contract modules at module level. Unknown platforms install
# nothing extra; the channel reports a clear error at start if no engine is
# importable.
def _wake_word_dependencies() -> tuple[str, ...]:
    """Wake word engine dependencies for this machine."""
    import platform

    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64", "aarch64", "arm64"}:
        return ("pyopen-wakeword>=1.1.0,<2",)
    if machine in {"armv7l", "armv6l"}:
        return ("pvporcupine==1.9.5",)
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

