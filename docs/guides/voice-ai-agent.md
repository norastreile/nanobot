# Talk to nanobot with your voice

This guide turns a computer with a microphone and speakers into a hands-free
nanobot station. You say a wake word, speak your request, and nanobot answers
out loud through the same model, tools, memory, and workspace as every other
channel.

## What this guide builds

- the `voice` channel enabled in nanobot
- wake word detection on the gateway host (openWakeWord, with Porcupine as the
  fallback on 32-bit ARM boards such as Raspberry Pi OS)
- spoken replies through text-to-speech (Edge TTS)
- one local speaker identity (`voice_user`) allowed to talk to the agent

## Prerequisites

- A working nanobot CLI reply:

```bash
nanobot agent -m "Hello!"
```

- A microphone and speakers attached to the machine that runs the gateway.
- An audio player for spoken replies. Install one of:
  - `mpv` (recommended), or
  - `ffmpeg` together with `alsa-utils` (`aplay`) or `pulseaudio-utils`
    (`paplay`)

  Without a player the channel refuses to start and logs a clear error instead
  of staying silent later.
- A configured transcription provider, because your speech is transcribed in
  the cloud before it reaches the agent. The default provider is Groq Whisper;
  see [Transcription Settings](../configuration.md#transcription-settings).
- Internet access on the gateway host: both speech-to-text and Edge TTS are
  cloud services.

## Install nanobot

```bash
python -m pip install nanobot-ai
nanobot onboard --wizard
```

## Connect Voice in the WebUI

Start the WebUI:

```bash
nanobot webui
```

Open **Settings → Channels → Voice**:

1. If voice support is not installed, turn on its switch and confirm the
   installation. This installs the wake word engine (pyopen-wakeword, or
   pvporcupine on 32-bit ARM), `pvrecorder`, and `edge-tts`.
2. Keep **Wake word engine** on `auto`: it uses openWakeWord on 64-bit systems
   and falls back to Porcupine where openWakeWord has no wheels.
3. Set **Custom wake words or models** to built-in wake word names
   (`okay_nabu`, `hey_jarvis`, `hey_mycroft`, `alexa`, `hey_rhasspy`) or paths
   to custom `.tflite` models. Leave the field empty to listen for all built-in
   wake words at once.
4. Optionally set **Wake word sensitivities** from `0.0` to `1.0`, one per
   wake word in the same order. Higher values detect from greater distance or
   in noisier rooms; missing values default to `0.5`.
5. Keep **Allowed users** at `voice_user`, which represents the person
   speaking into the local microphone.
6. Optionally point **LED status command** at a shell command that reflects
   the channel state (see below).
7. Save and enable Voice, then restart the gateway when the WebUI shows a
   restart requirement.

## Manual setup

For a headless installation, install voice support in the gateway's Python
environment:

```bash
nanobot plugins enable voice
```

Then merge this snippet into `~/.nanobot/config.json`:

```json
{
  "channels": {
    "voice": {
      "enabled": true,
      "allowFrom": ["voice_user"],
      "wakeWordEngine": "auto",
      "wakeWordModels": ["hey_jarvis"],
      "ttsVoice": "en-US-AriaNeural"
    }
  }
}
```

Useful optional fields:

- `wakeWordSensitivities`: one `0.0`–`1.0` value per wake word.
- `porcupineModel`: path to a Porcupine speech model (`.pv`) for languages
  other than English; this is the language model, not a wake word.
- `audioDeviceIndex`: index of the microphone to record from (default `1`).
- `silenceThreshold`, `silenceDuration`, `maxRecordingDuration`: tune when a
  spoken request is considered finished.
- `ledCommand`: shell command for a status LED (see below).

## Run nanobot gateway

```bash
nanobot channels status
nanobot gateway
```

The log should show `Voice channel ready - listening for wake words ...`.
Leave the gateway running while you test.

## Talk to nanobot

Say your wake word, then speak your request in the same breath:

```text
Hey Jarvis, how are you today?
```

The channel moves through `recording`, `thinking`, and `speaking`, and the
reply uses the same model and workspace as your local CLI check. With no wake
words configured, any built-in wake word triggers recording.

## Optional: drive a status LED

`ledCommand` runs a shell command on every state change via
`sh -c <command>`, with the state available as `$1`. Possible states:
`idle`, `listening_wake_word`, `recording`, `thinking`, `speaking`.

Keep the mapping from state to color in a small script instead of a long
inline command:

```bash
#!/bin/sh
# /home/pi/voice-led.sh
case "$1" in
  recording) curl -s http://wled.local/json/state -d '{"on":true,"seg":{"col":[[255,0,0]]}}' ;;
  speaking)  curl -s http://wled.local/json/state -d '{"on":true,"seg":{"col":[[0,255,0]]}}' ;;
  *)         curl -s http://wled.local/json/state -d '{"on":true,"seg":{"col":[[64,64,255]]}}' ;;
esac
```

Then set:

```json
"ledCommand": "/home/pi/voice-led.sh $1"
```

## Security notes

- `allowFrom: ["voice_user"]` trusts anyone with physical access to the
  microphone. Place the device accordingly; do not combine it with tools you
  would not hand to a stranger.
- Audio is recorded only after a wake word, but each request is sent to the
  configured cloud transcription provider and each reply to Edge TTS. Do not
  point the microphone at rooms you would not want transcribed in the cloud.
- `ledCommand` executes an arbitrary shell command on every state change.
  Keep its value a local, trusted script path.

## Troubleshooting

- **`No audio player found for TTS playback`** at gateway start: install `mpv`,
  or `ffmpeg` together with `alsa-utils` or `pulseaudio-utils`, then restart
  the gateway.
- **`Could not transcribe audio`** or spoken requests never reach the agent:
  configure the transcription settings and the matching provider API key; see
  [Transcription Settings](../configuration.md#transcription-settings).
- **The wake word is never detected**: try another built-in wake word, raise
  `wakeWordSensitivities`, or point `audioDeviceIndex` at the correct
  microphone. Run `nanobot gateway --verbose` to confirm the channel started.
- **Replies are silent although the log shows `speaking`**: the audio player
  works but the output device or volume is wrong; test with
  `mpv --no-video <file>` or `aplay <file>` directly.
- **Raspberry Pi (32-bit OS)**: the channel automatically uses Porcupine, which
  ships English keywords only and requires choosing wake words. Custom keywords
  come as `.ppn` files from the Picovoice Console; other languages need a
  `porcupineModel` (`.pv`) file.

## Next: memory, automations, MCP tools

- [Configuration reference](../configuration.md)
- [AI Agent Memory](./ai-agent-memory.md)
- [Deploy nanobot gateway](./deploy-nanobot-gateway.md)
