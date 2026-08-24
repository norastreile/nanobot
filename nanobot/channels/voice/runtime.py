# pyright: reportConstantRedefinition=false, reportMissingTypeStubs=false, reportPrivateUsage=false
"""Voice channel with wake word detection for local microphone/speaker interaction."""

import asyncio
import struct
import tempfile
import wave
from pathlib import Path
from typing import Any, Optional

from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.voice.status import CommandStatusListener, VoiceStatus, VoiceStatusEmitter
from nanobot.config.schema import Base

PICOVOICE_AVAILABLE = False
EDGE_TTS_AVAILABLE = False

try:
    import pvporcupine
    from pvrecorder import PvRecorder

    PICOVOICE_AVAILABLE = True
except ImportError:
    pass

try:
    import edge_tts

    EDGE_TTS_AVAILABLE = True
except ImportError:
    pass


class VoiceConfig(Base):
    """Voice Channel configuration."""

    enabled: bool = False
    allow_from: list[str] = Field(default_factory=list)  # Allowed voice users

    # Picovoice access key
    picovoice_access_key: str = ""  # required

    # Wake word settings
    wake_word_model: str = ""  # path to Porcupine wakeword model .pv file
    wake_word_keywords: list[str] = Field(default_factory=lambda: ["nano"])  # list of wake words
    wake_word_keyword_paths: list[str] = Field(default_factory=list)  # path to custom wakeword .ppn file
    wake_word_sensitivities: list[str] = Field(default_factory=lambda: ["0.5"])  # range 0.0 to 1.0

    # Audio settings
    audio_device_index: int = 1
    silence_threshold: int = 500
    silence_duration: int = 1500  # in milliseconds
    max_recording_duration: int = 30  # in seconds

    # TTS settings
    tts_voice: str = "en-US-AriaNeural"

    # Optional status indicator (e.g. LED). Shell command executed on every state
    # change via `sh -c <command>`, the status value is passed as $1.
    led_command: str = ""


class VoiceChannel(BaseChannel):
    """
    Voice channel using wake word detection.

    Flow:
    1. Listen for wake word (Porcupine)
    2. Record audio until silence detected
    3. Transcribe with Groq Whisper
    4. Send to agent, get response
    5. Speak response with Edge TTS
    """

    name = "voice"

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return VoiceConfig().model_dump(by_alias=True)

    @staticmethod
    def _safe_float(val: Any) -> float:
        """Parse a sensitivity value; normalize 0-100 input to the 0.0-1.0 range Porcupine expects."""
        if isinstance(val, str):
            # Accept comma as decimal separator (e.g. "0,5")
            val = val.replace(",", ".")
        try:
            value = float(val)
        except (TypeError, ValueError):
            return 0.5
        return value / 100 if value > 1 else value

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = VoiceConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: VoiceConfig = config
        self._porcupine = None
        self._recorder = None
        self._sample_rate = 16000
        self.status_emitter = VoiceStatusEmitter()
        if config.led_command:
            self.status_emitter.add_listener(CommandStatusListener(config.led_command))

    async def start(self) -> None:
        """Start the voice channel with wake word detection."""

        if not PICOVOICE_AVAILABLE:
            self.logger.error(
                "Porcupine and PvRecorder not installed. Run: nanobot plugins enable voice"
            )
            return
        if not EDGE_TTS_AVAILABLE:
            self.logger.error(
                "Edge TTS not installed. Run: nanobot plugins enable voice"
            )
            return

        self._running = True
        self.logger.info("Starting voice channel...")

        try:

            model_path: str = self.config.wake_word_model
            if model_path and len(model_path.strip()) < 1:
                model_path = None

            keywords: Optional[list[str]] = self.config.wake_word_keywords
            if not keywords or not keywords[0].strip():
                keywords = None

            keyword_paths: Optional[list[str]] = None
            if not keywords:
                keyword_paths = self.config.wake_word_keyword_paths
                if not keyword_paths or not keyword_paths[0].strip():
                    keyword_paths = None

            sensitivities = [self._safe_float(x) for x in self.config.wake_word_sensitivities]

            # Initialize Porcupine wake word engine
            self._porcupine = pvporcupine.create(
                access_key=self.config.picovoice_access_key,
                model_path=model_path,
                keywords=keywords,
                keyword_paths=keyword_paths,
                sensitivities=sensitivities
            )

            self._sample_rate = self._porcupine.sample_rate
            frame_length = self._porcupine.frame_length

            # Initialize recorder
            self._recorder = PvRecorder(
                device_index=self.config.audio_device_index,
                frame_length=frame_length
            )

            self._recorder.start()

            await self.status_emitter.emit(VoiceStatus.LISTENING_WAKE_WORD)
            self.logger.info("Voice channel ready - listening for wake words ...")

            while self._running:

                # Run wake word detection in thread pool to not block
                pcm = await asyncio.get_event_loop().run_in_executor(
                    None, self._recorder.read
                )

                result = self._porcupine.process(pcm)

                if result >= 0:
                    self.logger.info("Wake word detected!")
                    await self.status_emitter.emit(VoiceStatus.RECORDING)
                    await self._handle_wake_word()

        except Exception:
            self.logger.exception("Failed to start channel")
        finally:
            self._running = False
            await self.status_emitter.emit(VoiceStatus.IDLE)

    async def stop(self) -> None:
        """Stop the voice channel."""
        self._running = False

        if self._recorder:
            try:
                self._recorder.stop()
            except Exception:
                pass
            self._recorder = None

        if self._porcupine:
            self._porcupine.delete()
            self._porcupine = None

        self.logger.info("Voice channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Speak the response using TTS."""
        if not msg.content or msg.content == "[empty message]":
            return

        self.logger.info("Speaking response: {}...", msg.content[:50])

        try:
            await self._speak(msg.content)
        except Exception as e:
            self.logger.error("TTS error: {}", e)

    async def _handle_wake_word(self) -> None:
        """Handle wake word detection - record, transcribe, respond."""

        self.logger.info("Recording user speech...")

        # Record until silence
        audio_data = await self._record_until_silence()

        if not audio_data:
            self.logger.warning("No audio recorded")
            return

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = Path(f.name)
            self._save_wav(temp_path, audio_data)

        self.logger.info("Recorded {} seconds of audio", len(audio_data) / self._sample_rate)

        # Transcribe
        transcription = await self.transcribe_audio(temp_path)

        # Clean up temp file
        try:
            temp_path.unlink()
        except Exception:
            pass

        if not transcription:
            self.logger.warning("Could not transcribe audio")
            await self._speak("Das habe ich leider nicht verstanden.")
            return

        self.logger.info("Transcribed: {}", transcription)

        await self.status_emitter.emit(VoiceStatus.THINKING)

        # Send to agent via message bus
        await self._handle_message(
            sender_id="voice_user",
            chat_id="voice",
            content=transcription,
            metadata={"source": "voice"}
        )

    async def _record_until_silence(self) -> list[int]:
        """Record audio until silence is detected."""

        audio_frames = []
        silence_frames = 0
        frames_per_second = self._sample_rate / self._porcupine.frame_length
        silence_frames_needed = int(self.config.silence_duration / 1000 * frames_per_second)
        max_frames = int(self.config.max_recording_duration * frames_per_second)

        frame_count = 0

        while self._running and frame_count < max_frames:
            pcm = await asyncio.get_event_loop().run_in_executor(
                None, self._recorder.read
            )

            audio_frames.extend(pcm)
            frame_count += 1

            # Check for silence
            max_amplitude = max(abs(x) for x in pcm)

            if max_amplitude < self.config.silence_threshold:
                silence_frames += 1
                if silence_frames >= silence_frames_needed:
                    self.logger.debug("Silence detected, stopping recording")
                    break
            else:
                silence_frames = 0

        return audio_frames

    def _save_wav(self, path: Path, audio_data: list[int]) -> None:
        """Save audio data to WAV file."""
        with wave.open(str(path), 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self._sample_rate)
            wf.writeframes(struct.pack(f'{len(audio_data)}h', *audio_data))

    async def _speak(self, text: str) -> None:
        """Speak text using Edge TTS."""

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_path = Path(f.name)

        await self.status_emitter.emit(VoiceStatus.SPEAKING)
        try:
            # Generate TTS
            communicate = edge_tts.Communicate(text, self.config.tts_voice)
            await communicate.save(str(temp_path))

            # Play audio
            process = await asyncio.create_subprocess_exec(
                "mpv", "--no-video", "--really-quiet", str(temp_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL
            )
            await process.wait()

        except FileNotFoundError:
            # Try aplay/paplay as fallback
            try:
                # Convert to wav first
                wav_path = temp_path.with_suffix(".wav")
                process = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-i", str(temp_path), "-y", str(wav_path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await process.wait()

                process = await asyncio.create_subprocess_exec(
                    "aplay", str(wav_path),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await process.wait()

                wav_path.unlink(missing_ok=True)
            except Exception as e:
                self.logger.error("Could not play audio: {}", e)
        finally:
            temp_path.unlink(missing_ok=True)

        if self._running:
            await self.status_emitter.emit(VoiceStatus.LISTENING_WAKE_WORD)
