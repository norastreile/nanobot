"""Voice status fan-out for external indicators (e.g. LEDs).

The voice channel publishes its local state through :class:`VoiceStatusEmitter`.
Listeners (LED drivers, home automation hooks, ...) are optional and must never
break the voice loop, so every listener call is error-isolated.
"""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Protocol

from loguru import logger


class VoiceStatus(StrEnum):
    """Local states of the voice channel."""

    IDLE = "idle"
    LISTENING_WAKE_WORD = "listening_wake_word"
    RECORDING = "recording"
    THINKING = "thinking"
    SPEAKING = "speaking"


class StatusListener(Protocol):
    """A consumer of voice status changes (LED driver, HTTP hook, ...)."""

    async def on_voice_status(self, status: VoiceStatus) -> None:
        """Handle a status transition."""
        ...


class VoiceStatusEmitter:
    """Minimal pub/sub for voice status changes.

    Listener failures are logged and swallowed: an indicator must never
    take down wake word detection or TTS playback.
    """

    def __init__(self) -> None:
        self._listeners: list[StatusListener] = []

    def add_listener(self, listener: StatusListener) -> None:
        self._listeners.append(listener)

    async def emit(self, status: VoiceStatus) -> None:
        for listener in self._listeners:
            try:
                await listener.on_voice_status(status)
            except Exception as e:
                logger.warning("Voice status listener failed for {}: {}", status, e)


class CommandStatusListener:
    """Runs a shell command on every status change.

    The command is executed via ``sh -c <command>`` with the status value
    (e.g. ``recording``) available as ``$1``. This keeps the mapping from
    state to LED color entirely on the command side, e.g.::

        sh -c 'curl -s http://wled/x/json/state -d "{\"on\":true,\"seg\":{\"col\":[[255,0,0]]}}"' -- "$1"
    """

    def __init__(self, command: str) -> None:
        self._command = command

    async def on_voice_status(self, status: VoiceStatus) -> None:
        process = await asyncio.create_subprocess_exec(
            "/bin/sh",
            "-c",
            self._command,
            "sh",
            status.value,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(process.wait(), timeout=10)
