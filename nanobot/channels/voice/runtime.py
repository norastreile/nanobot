# pyright: reportConstantRedefinition=false, reportMissingTypeStubs=false, reportPrivateUsage=false
"""Voice channel with wake word detection for local microphone/speaker interaction."""

import asyncio
import platform
import struct
import subprocess
import sys
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

try:
    import numpy as np
    from pyopen_wakeword import Model as BuiltinWakeWordModel
    from pyopen_wakeword import OpenWakeWord, OpenWakeWordFeatures
except ImportError:
    np = None  # type: ignore[assignment]
    OpenWakeWord = None  # type: ignore[assignment]
    OpenWakeWordFeatures = None  # type: ignore[assignment]
    BuiltinWakeWordModel = None  # type: ignore[assignment]


def _porcupine_requires_access_key(pvporcupine_module: Any) -> bool:
    """Access keys were introduced in pvporcupine 2.0; 1.9.5 is keyless."""
    return hasattr(pvporcupine_module, "PorcupineActivationError")


def _import_pvporcupine() -> Any:
    """Import pvporcupine, tolerating 1.9.x CPU detection on modern kernels.

    pvporcupine 1.9.x (used on 32-bit ARM) parses the
    'Hardware'/'model name' lines of /proc/cpuinfo at import time to select
    the Raspberry Pi library. Modern kernels no longer write these lines,
    so the import would crash with IndexError. In that case we synthesize
    the lines the old detector expects, based on /proc/device-tree/model.
    """
    try:
        import pvporcupine
        return pvporcupine
    except ImportError:
        return None
    except Exception:
        if not (sys.platform.startswith("linux") and platform.machine().startswith("arm")):
            return None
        try:
            with open("/proc/device-tree/model", encoding="utf-8") as f:
                model = f.read().strip("\x00\n")
        except OSError:
            model = ""
        if any(x in model for x in ("Pi 4", "Pi 5", "Pi 400", "Compute Module 4")):
            rev = "rev 3"  # -> cortex-a72 (Pi 4 / Pi 5)
        else:
            rev = "rev 4"  # -> cortex-a53 (Pi 3, Zero 2, ...)
        fake_cpuinfo = (
            f"Hardware\t: BCM2711\n"
            f"model name\t: ARMv7 Processor {rev}\n"
        ).encode()
        original_check_output = subprocess.check_output
        subprocess.check_output = lambda *args, **kwargs: fake_cpuinfo  # type: ignore[assignment]
        try:
            import pvporcupine
            return pvporcupine
        except Exception:
            return None
        finally:
            subprocess.check_output = original_check_output


pvporcupine = _import_pvporcupine()

try:
    from pvrecorder import PvRecorder
except ImportError:
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

    # Wake word engine: "auto" prefers openWakeWord and falls back to
    # Porcupine on platforms without openwakeword wheels (32-bit ARM).
    wake_word_engine: str = "auto"

    # Wake word models, interpreted per engine:
    # - openwakeword: built-in names (okay_nabu, hey_jarvis, hey_mycroft, alexa,
    #   hey_rhasspy) or paths to custom .tflite models; empty = all built-in
    # - porcupine: built-in names (e.g. "jarvis", 19 available, English only)
    #   or paths to custom .ppn keyword files; empty = error (choose wake words)
    wake_word_models: list[str] = Field(default_factory=list)
    wake_word_sensitivities: list[str] = Field(default_factory=lambda: ["0.5"])  # detection thresholds (openWakeWord) / sensitivities (Porcupine), range 0.0 to 1.0

    # Porcupine settings (only used with wake_word_engine = "porcupine" or the 32-bit ARM fallback)
    porcupine_model: str = ""  # path to the Porcupine speech model (.pv), e.g. language-specific; NOT a wake word keyword

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
    1. Listen for wake word (openWakeWord, or Porcupine as 32-bit ARM fallback)
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
        """Parse a sensitivity/threshold value; normalize 0-100 input to the 0.0-1.0 range."""
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
        self._engine = ""
        self._features: Any = None
        self._words: dict[str, Any] = {}
        self._model_thresholds: dict[str, float] = {}
        self._porcupine: Any = None
        self._frame_length = 1280  # 80 ms of 16 kHz audio, as recommended by openWakeWord
        self._recorder: Any = None
        self._sample_rate = 16000
        self.status_emitter = VoiceStatusEmitter()
        if config.led_command:
            self.status_emitter.add_listener(CommandStatusListener(config.led_command))

    def _available_engine(self) -> str:
        """Return the fully importable wake word engine ("none" if neither is)."""
        if (
            OpenWakeWord is not None
            and OpenWakeWordFeatures is not None
            and np is not None
            and BuiltinWakeWordModel is not None
        ):
            return "openwakeword"
        if pvporcupine is not None:
            return "porcupine"
        return "none"

    def _resolve_engine(self) -> str:
        """Resolve the configured engine name, or the empty string on error."""
        requested = (self.config.wake_word_engine or "auto").strip().lower()
        if requested == "auto":
            # "auto" prefers openWakeWord and falls back to Porcupine, which is
            # the only engine with wheels for 32-bit ARM (e.g. Raspberry Pi OS).
            available = self._available_engine()
            if available == "none":
                self.logger.error(
                    "Neither openWakeWord nor Porcupine is installed. "
                    "Run: nanobot plugins enable voice"
                )
                return ""
            return available
        if requested not in ("openwakeword", "porcupine"):
            self.logger.error(
                "Invalid wake_word_engine '{}': use 'auto', 'openwakeword' or 'porcupine'.",
                requested,
            )
            return ""
        if requested == "openwakeword" and (
            OpenWakeWord is None or OpenWakeWordFeatures is None or np is None or BuiltinWakeWordModel is None
        ):
            self.logger.error(
                "openWakeWord is not installed; install it or set wake_word_engine to 'auto'."
            )
            return ""
        if requested == "porcupine" and pvporcupine is None:
            self.logger.error(
                "Porcupine is not installed; install it or set wake_word_engine to 'auto'."
            )
            return ""
        return requested

    async def _setup_openwakeword(self) -> None:
        """Initialize the pyopen-wakeword engine and per-model thresholds."""
        # Shared audio-to-embeddings pipeline (melspectrogram + embedding model
        # are bundled with the pyopen-wakeword wheel; no download needed).
        features_cls: Any = OpenWakeWordFeatures
        self._features = features_cls.from_builtin()
        builtin_models: Any = BuiltinWakeWordModel

        # Each entry is either a built-in wake word name (e.g. "hey_jarvis")
        # or a path to a custom .tflite model.
        builtin = {m.value.lower(): m for m in builtin_models}
        entries = [e.strip() for e in self.config.wake_word_models if e.strip()]
        if not entries:
            entries = [m.value for m in builtin_models]

        word_ids: list[str] = []
        for entry in entries:
            if entry.lower().endswith(".tflite"):
                word_cls: Any = OpenWakeWord
                word = word_cls.from_model(entry)
            else:
                model = builtin.get(entry.lower())
                if model is None:
                    raise ValueError(
                        f"Unknown built-in wake word '{entry}'. "
                        f"Built-in wake words: {sorted(builtin)}; "
                        "or provide a path to a custom .tflite model."
                    )
                word_cls = OpenWakeWord
                word = word_cls.from_builtin(model)
            if word.id in self._words:
                continue
            self._words[word.id] = word
            word_ids.append(word.id)

        sensitivities = self._padded_sensitivities(len(word_ids), "wake word models")
        self._model_thresholds = dict(zip(word_ids, sensitivities))
        self.logger.info("Wake word models: {}", self._model_thresholds)

    def _setup_porcupine(self) -> None:
        """Initialize the Porcupine engine (fallback for 32-bit ARM)."""
        porcupine: Any = pvporcupine
        assert porcupine is not None
        if _porcupine_requires_access_key(porcupine):
            raise ValueError(
                "pvporcupine >= 2.0 requires a Picovoice access key. "
                "Install the keyless pvporcupine==1.9.5 "
                "or use wake_word_engine='openwakeword'."
            )

        model_path: Optional[str] = self.config.porcupine_model.strip() or None

        # Each wake_word_models entry is either a built-in keyword name (e.g.
        # "jarvis"; English only) or a path to a custom .ppn keyword file.
        entries = [e.strip() for e in self.config.wake_word_models if e.strip()]
        if not entries:
            raise ValueError(
                "Porcupine requires wake words: set 'wake_word_models' to "
                "built-in keyword names (e.g. 'jarvis', 'computer', 19 available) "
                "or paths to custom .ppn keyword files."
            )

        keyword_paths: list[str] = []
        for entry in entries:
            if entry.lower().endswith(".ppn"):
                if not Path(entry).is_file():
                    raise ValueError(f"Wake word file not found: {entry}")
                keyword_paths.append(entry)
            else:
                built_in = porcupine.KEYWORD_PATHS.get(entry.lower())
                if built_in is None:
                    raise ValueError(
                        f"Unknown built-in Porcupine keyword '{entry}'. "
                        f"Built-in keywords: {sorted(porcupine.KEYWORD_PATHS)}; "
                        "or provide a path to a custom .ppn keyword file."
                    )
                keyword_paths.append(str(built_in))

        sensitivities = self._padded_sensitivities(len(keyword_paths), "keywords")

        self._porcupine = porcupine.create(
            model_path=model_path,
            keyword_paths=keyword_paths,
            sensitivities=sensitivities,
        )
        self._sample_rate = self._porcupine.sample_rate
        self._frame_length = self._porcupine.frame_length
        self.logger.info("Porcupine wake words: {}", keyword_paths)

    def _padded_sensitivities(self, count: int, label: str) -> list[float]:
        """Normalize the configured sensitivities to one value per item."""
        sensitivities = [self._safe_float(x) for x in self.config.wake_word_sensitivities]
        if not sensitivities:
            sensitivities = [0.5]
        if len(sensitivities) < count:
            self.logger.warning(
                "Number of sensitivities (%d) does not match number of %s (%d); padding with 0.5.",
                len(sensitivities),
                label,
                count,
            )
            sensitivities = sensitivities + [0.5] * (count - len(sensitivities))
        elif len(sensitivities) > count:
            self.logger.warning(
                "Number of sensitivities (%d) exceeds number of %s (%d); truncating.",
                len(sensitivities),
                label,
                count,
            )
            sensitivities = sensitivities[:count]
        return sensitivities

    def _reset_openwakeword_state(self) -> None:
        """Clear stale audio from the openWakeWord buffers."""
        if self._features is not None:
            self._features.reset()
        for word in self._words.values():
            word.reset()

    def _detect_wake_word(self, pcm: Any) -> bool:
        """Run one detection step on a recorder frame with the active engine."""
        if self._engine == "porcupine":
            assert self._porcupine is not None
            return self._porcupine.process(pcm) >= 0
        numpy: Any = np
        assert self._features is not None and numpy is not None
        pcm_bytes = numpy.asarray(pcm, dtype=numpy.int16).tobytes()
        for embeddings in self._features.process_streaming(pcm_bytes):
            for word in self._words.values():
                for probability in word.process_streaming(embeddings):
                    if probability >= self._model_thresholds.get(word.id, 0.5):
                        return True
        return False

    async def start(self) -> None:
        """Start the voice channel with wake word detection."""
        engine = self._resolve_engine()
        if not engine:
            return
        if edge_tts is None:
            self.logger.error("Edge TTS not installed. Run: nanobot plugins enable voice")
            return
        if PvRecorder is None:
            self.logger.error("PvRecorder not installed. Run: nanobot plugins enable voice")
            return

        self._running = True
        self._engine = engine
        self.logger.info("Starting voice channel (wake word engine: {})...", engine)

        try:
            if engine == "openwakeword":
                await self._setup_openwakeword()
            else:
                self._setup_porcupine()

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

                detected = await asyncio.get_event_loop().run_in_executor(
                    None, self._detect_wake_word, pcm
                )

                if detected:
                    # Clear stale audio from the buffers before recording
                    self._reset_openwakeword_state()
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
            try:
                self._porcupine.delete()
            except Exception:
                pass
            self._porcupine = None

        if self._features:
            try:
                self._features.close()
            except Exception:
                pass
            self._features = None

        if self._words:
            for word in self._words.values():
                try:
                    word.close()
                except Exception:
                    pass
            self._words = {}

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
