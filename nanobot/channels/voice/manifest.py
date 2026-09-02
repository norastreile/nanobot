"""Voice channel management contract."""

from nanobot.channels._manifest import field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

"""Voice Channel configuration."""
SETUP_SPEC = ChannelSetupSpec(
    fields={
        "tts_voice": field(kind="string", default="en-US-AriaNeural"),
        "wake_word_models": field("list"), # paths to custom openWakeWord models (.tflite/.onnx); empty = all bundled pretrained models
        "wake_word_sensitivities": field("list", default=["0.5"]), # list of detection score thresholds, range 0.0 to 1.0 (higher = detects wake word at greater distance/noise)
        "audio_device_index": field(kind="int", default=1),
        "silence_threshold": field(kind="int", default=500),
        "silence_duration": field(kind="int", default=1500), #in milliseconds
        "max_recording_duration": field(kind="int", default=30), #in seconds
        "led_command": field(kind="string"),  # optional status LED shell command, status as $1
        "allowFrom": field("list"),
    },
    required=required_fields(),
    official_url="https://github.com/dscripka/openwakeword",
)

PLUGIN = ChannelPlugin(
    name="voice",
    display_name="Voice",
    runtime=f"{__package__}.runtime:VoiceChannel",
    setup=SETUP_SPEC,
    dependencies=("openwakeword @ git+https://github.com/dscripka/openWakeWord","pvrecorder>=1.2.7,<2.0.0","edge-tts>=7.2.8,<8.0.0"),
    webui="webui/index.ts",
)
