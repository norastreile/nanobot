import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "Voice",
    initials: "VO",
    color: "#ffc916",
    logoUrl:
      "https://api.iconify.design/mdi/account-voice.svg?height=32",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("voice"),
      fields: [
        { key: "channels.voice.tts_voice", section: "text-to-speech" },
        { key: "channels.voice.wake_word_engine", section: "wakeword" },
        { key: "channels.voice.picovoice_access_key", section: "wakeword" },
        { key: "channels.voice.porcupine_model", section: "wakeword" },
        { key: "channels.voice.wake_word_models", section: "wakeword" },
        { key: "channels.voice.wake_word_sensitivities", section: "wakeword" },
        { key: "channels.voice.audio_device_index", section: "recording" },
        { key: "channels.voice.silence_threshold", section: "recording" },
        { key: "channels.voice.silence_duration", section: "recording" },
        { key: "channels.voice.max_recording_duration", section: "recording" },
        { key: "channels.voice.allowFrom", section: "access" },
      ],
    },
  },
} satisfies ChannelUiContribution;
