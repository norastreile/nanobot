"""Shared defaults for the Voice channel."""

import shutil
from collections.abc import Callable


def audio_player_available(which: Callable[[str], str | None] | None = None) -> bool:
    """Return whether a supported TTS playback backend is available."""
    find_executable = which or shutil.which
    if find_executable("mpv"):
        return True
    return bool(find_executable("ffmpeg")) and bool(
        find_executable("aplay") or find_executable("paplay")
    )


DEFAULT_WAKE_WORD_ENGINE = "auto"
DEFAULT_AUDIO_DEVICE_INDEX = 1
DEFAULT_SILENCE_THRESHOLD = 500
DEFAULT_SILENCE_DURATION = 1500
DEFAULT_MAX_RECORDING_DURATION = 30
DEFAULT_WAKE_WORD_SENSITIVITY = 0.5
DEFAULT_TTS_VOICE = "en-US-AriaNeural"
DEFAULT_SPEAKER_ID = "voice_user"
DEFAULT_ALLOW_FROM = [DEFAULT_SPEAKER_ID]
DEFAULT_SILENT_MODE_ENTER_PHRASES = ["silent mode", "mute yourself"]
DEFAULT_SILENT_MODE_EXIT_PHRASES = ["silent mode", "unmute yourself", "listen to me again", "listen again"]
