"""Voice channel with wake word detection for local microphone/speaker interaction."""

from __future__ import annotations

import asyncio
import struct
import tempfile
import wave
from pathlib import Path

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import VoiceConfig

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
    
    def __init__(self, config: VoiceConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: VoiceConfig = config
        self._porcupine = None
        self._recorder = None
        self._sample_rate = 16000
        
    async def start(self) -> None:
        """Start the voice channel with wake word detection."""
        # Set environment variable so voice skill knows not to play audio
        # (voice channel has built-in TTS, calling voice skill would cause double output)
        import os
        os.environ["NANOBOT_VOICE_CHANNEL"] = "1"
        
        try:
            import pvporcupine
            from pvrecorder import PvRecorder
        except ImportError:
            logger.error("Voice channel requires pvporcupine and pvrecorder. "
                        "Install with: pip3 install pvporcupine pvrecorder --break-system-packages")
            return
            
        self._running = True
        logger.info("Starting voice channel...")
        
        try:
            # Initialize Porcupine wake word engine
            self._porcupine = pvporcupine.create(
                access_key=self.config.picovoice_api_key,
                model_path=self.config.wake_word_model,
                keyword_paths=[self.config.wake_word_keyword],
                sensitivities=[self.config.sensitivity]
            )
            
            self._sample_rate = self._porcupine.sample_rate
            frame_length = self._porcupine.frame_length
            
            # Initialize recorder
            self._recorder = PvRecorder(
                device_index=self.config.audio_device_index,
                frame_length=frame_length
            )
            
            logger.info("Voice channel ready - listening for wake word...")
            
            # Main loop
            self._recorder.start()
            
            while self._running:
                # Run wake word detection in thread pool to not block
                pcm = await asyncio.get_event_loop().run_in_executor(
                    None, self._recorder.read
                )
                
                result = self._porcupine.process(pcm)
                
                if result >= 0:
                    logger.info("Wake word detected!")
                    await self._handle_wake_word()
                    
        except Exception as e:
            logger.error("Voice channel error: {}", e)
        finally:
            await self.stop()
            
    async def stop(self) -> None:
        """Stop the voice channel."""
        self._running = False
        
        if self._recorder:
            try:
                self._recorder.stop()
            except:
                pass
            self._recorder = None
            
        if self._porcupine:
            self._porcupine.delete()
            self._porcupine = None
            
        logger.info("Voice channel stopped")
        
    async def send(self, msg: OutboundMessage) -> None:
        """Speak the response using TTS."""
        if not msg.content or msg.content == "[empty message]":
            return
            
        logger.info("Speaking response: {}...", msg.content[:50])
        
        try:
            await self._speak(msg.content)
        except Exception as e:
            logger.error("TTS error: {}", e)
            
    async def _handle_wake_word(self) -> None:
        """Handle wake word detection - record, transcribe, respond."""
        
        logger.info("Recording user speech...")
        
        # Record until silence
        audio_data = await self._record_until_silence()

        if not audio_data:
            logger.warning("No audio recorded")
            return
            
        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = Path(f.name)
            self._save_wav(temp_path, audio_data)
            
        logger.info("Recorded {} seconds of audio", len(audio_data) / self._sample_rate)
        
        # Transcribe
        transcription = await self.transcribe_audio(temp_path)
        
        # Clean up temp file
        try:
            temp_path.unlink()
        except:
            pass
            
        if not transcription:
            logger.warning("Could not transcribe audio")
            await self._speak("Das habe ich leider nicht verstanden.")
            return
            
        logger.info("Transcribed: {}", transcription)
        
        # Send to agent via message bus
        await self._handle_message(
            sender_id="voice_user",
            chat_id="voice",
            content=transcription,
            metadata={"source": "voice"}
        )
        
    async def _record_until_silence(self) -> list[int]:
        """Record audio until silence is detected."""
        from pvrecorder import PvRecorder
        
        audio_frames = []
        silence_frames = 0
        frames_per_second = self._sample_rate / self._porcupine.frame_length
        silence_frames_needed = int(self.config.silence_duration * frames_per_second)
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
                    logger.debug("Silence detected, stopping recording")
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
        try:
            import edge_tts
        except ImportError:
            logger.error("edge_tts not installed. Install with: pip3 install edge-tts --break-system-packages")
            return
            
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            temp_path = Path(f.name)
            
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
                logger.error("Could not play audio: {}", e)
        finally:
            temp_path.unlink(missing_ok=True)