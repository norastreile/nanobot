import pytest

# Check optional voice dependencies before running tests
try:
    import nanobot.channels.voice.runtime as voice_module
    PICOVOICE_AVAILABLE = voice_module.PICOVOICE_AVAILABLE
except ImportError:
    PICOVOICE_AVAILABLE = False

try:
    EDGE_TTS_AVAILABLE = voice_module.EDGE_TTS_AVAILABLE
except ImportError:
    EDGE_TTS_AVAILABLE = False

if not PICOVOICE_AVAILABLE:
    pytest.skip("Voice dependencies not installed (pvporcupine,pvrecorder)", allow_module_level=True)
if not EDGE_TTS_AVAILABLE:
    pytest.skip("Voice dependencies not installed (edge-tts)", allow_module_level=True)



