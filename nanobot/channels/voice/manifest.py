"""Voice channel management contract."""

from nanobot.channels._manifest import field, required_fields
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin

"""Voice Channel configuration."""
SETUP_SPEC = ChannelSetupSpec(
    fields={
        "picovoice_access_key": field("secret"), # Picovoice API key
        "tts_voice": field(kind="string", default="en-US-AriaNeural"),
        "porcupine_model": field("string"), # path to Porcupine speech model .pv file (language/base model), NOT a wake word keyword
        "wake_word_keywords": field("list", default=["jarvis"]), # built-in wake word names; only used when wake_word_keyword_paths is empty
        "wake_word_keyword_paths": field("list"), # paths to custom wake word keywords (.ppn files); take precedence over wake_word_keywords
        "wake_word_sensitivities": field("list", default=["0.5"]), # list of wake word sensitivities, range 0.0 to 1.0 (higher = detects wake word at greater distance/noise)
        "audio_device_index": field(kind="int", default=1),
        "silence_threshold": field(kind="int", default=500),
        "silence_duration": field(kind="int", default=1500), #in milliseconds
        "max_recording_duration": field(kind="int", default=30), #in seconds
        "led_command": field(kind="string"),  # optional status LED shell command, status as $1
        "allowFrom": field("list"),
    },
    required=required_fields("picovoice_access_key"),
    official_url="https://console.picovoice.ai/",
)

PLUGIN = ChannelPlugin(
    name="voice",
    display_name="Voice",
    runtime=f"{__package__}.runtime:VoiceChannel",
    setup=SETUP_SPEC,
    dependencies=("pvporcupine>=4.0.3,<5.0.0","pvrecorder>=1.2.7,<2.0.0","edge-tts>=7.2.8,<8.0.0"),
    webui="webui/index.ts",
)
