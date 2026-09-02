# pyright: reportConstantRedefinition=false, reportMissingTypeStubs=false, reportPrivateUsage=false
"""Voice channel with wake word detection for local microphone/speaker interaction."""

import asyncio
import struct
import tempfile
import wave
from pathlib import Path
from typing import Any

from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.channels.voice.status import CommandStatusListener, VoiceStatus, VoiceStatusEmitter
from nanobot.config.schema import Base

try:
    import numpy as np
    from openwakeword.model import Model
    from openwakeword.utils import download_models
    from pvrecorder import PvRecorder
except ImportError:
    np = None  # type: ignore[assignment]
    Model = None  # type: ignore[assignment]
    download_models = None  # type: ignore[assignment]
    PvRecorder = None  # type: ignore[assignment]

try:
    import edge_tts
except ImportError:
    edge_tts = None  # type: ignore[assignment]

# Identity of the person speaking into the local microphone. Used as
# sender_id for inbound messages so allowFrom can grant access to "the
# person at the device" without a real user ID.
SPEAKER_ID = "local_speaker"


class VoiceConfig(Base):
    """Voice Channel configuration."""

    enabled: bool = False
    allow_from: list[str] = Field(default_factory=list)  # Allowed senders, e.g. ["local_speaker"] or ["*"]

    # Wake word settings (openWakeWord)
    wake_word_models: list[str] = Field(default_factory=list)  # paths to custom openWakeWord models (.tflite/.onnx); empty = all bundled pretrained models
    wake_word_sensitivities: list[str] = Field(default_factory=lambda: ["0.5"])  # detection score thresholds, range 0.0 to 1.0

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
    1. Listen for wake word (openWakeWord)
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
        """Parse a threshold value; normalize 0-100 input to the 0.0-1.0 range openWakeWord scores use."""
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
        self._model: Any = None
        self._model_thresholds: dict[str, float] = {}
        self._frame_length = 1280  # 80 ms of 16 kHz audio, as recommended by openWakeWord
        self._recorder: Any = None
        self._sample_rate = 16000
        self.status_emitter = VoiceStatusEmitter()
        if config.led_command:
            self.status_emitter.add_listener(CommandStatusListener(config.led_command))

    async def start(self) -> None:
        """Start the voice channel with wake word detection."""

        if Model is None or PvRecorder is None or np is None or download_models is None:
            self.logger.error(
                "openWakeWord, PvRecorder or numpy not installed. Run: nanobot plugins enable voice"
            )
            return
        if edge_tts is None:
            self.logger.error(
                "Edge TTS not installed. Run: nanobot plugins enable voice"
            )
            return

        self._running = True
        self.logger.info("Starting voice channel...")

        try:
            model_paths = [p.strip() for p in self.config.wake_word_models if p.strip()]
            if not model_paths:
                # No custom models: use all bundled pretrained wake words and
                # make sure they are downloaded (no-op once cached).
                fetch_models: Any = download_models
                await asyncio.get_event_loop().run_in_executor(None, fetch_models)

            # Initialize openWakeWord engine (ONNX backend for cross-platform support)
            self._model = Model(wakeword_models=model_paths, inference_framework="onnx")

            # One entry per parent model (e.g. "hey_jarvis"); scores are returned
            # per label and mapped back to their parent model for comparison.
            num_models = len(self._model.models)
            sensitivities = [self._safe_float(x) for x in self.config.wake_word_sensitivities]
            if not sensitivities:
                sensitivities = [0.5]
            if len(sensitivities) < num_models:
                self.logger.warning(
                    "Number of thresholds (%d) does not match number of wake word models (%d); "
                    "padding with 0.5.",
                    len(sensitivities),
                    num_models,
                )
                sensitivities = sensitivities + [0.5] * (num_models - len(sensitivities))
            elif len(sensitivities) > num_models:
                self.logger.warning(
                    "Number of thresholds (%d) exceeds number of wake word models (%d); truncating.",
                    len(sensitivities),
                    num_models,
                )
                sensitivities = sensitivities[:num_models]
            self._model_thresholds = dict(zip(self._model.models, sensitivities))
            self.logger.info("Wake word models: {}", self._model_thresholds)

            # Initialize recorder
            self._recorder = PvRecorder(
                device_index=self.config.audio_device_index,
                frame_length=self._frame_length
            )

            self._recorder.start()

            await self.status_emitter.emit(VoiceStatus.LISTENING_WAKE_WORD)
            self.logger.info("Voice channel ready - listening for wake words ...")

            while self._running:

                # Run wake word detection in thread pool to not block
                pcm = await asyncio.get_event_loop().run_in_executor(
                    None, self._recorder.read
                )

                scores = await asyncio.get_event_loop().run_in_executor(
                    None, self._model.predict, np.asarray(pcm, dtype=np.int16)
                )

                if any(
                    score >= self._model_thresholds.get(
                        self._model.get_parent_model_from_label(label), ""
                    )
                    for label, score in scores.items()
                ):
                    # Clear stale audio from the model buffer before recording
                    self._model.reset()
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

        if self._model:
            self._model = None

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
            sender_id=SPEAKER_ID,
            chat_id="voice",
            content=transcription,
            metadata={"source": "voice"}
        )

    async def _record_until_silence(self) -> list[int]:
        """Record audio until silence is detected."""

        audio_frames: list[int] = []
        silence_frames = 0
        frames_per_second = self._sample_rate / self._frame_length
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

        if edge_tts is None:
            self.logger.error("Edge TTS not installed; cannot speak.")
            return

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
