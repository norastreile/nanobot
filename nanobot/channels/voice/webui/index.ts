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
        { key: "channels.voice.ttsVoice", section: "text-to-speech" },
        { key: "channels.voice.wakeWordEngine", section: "wakeword" },
        { key: "channels.voice.porcupineModel", section: "wakeword" },
        { key: "channels.voice.wakeWordModels", section: "wakeword" },
        { key: "channels.voice.wakeWordSensitivities", section: "wakeword" },
        { key: "channels.voice.audioDeviceIndex", section: "recording" },
        { key: "channels.voice.silenceThreshold", section: "recording" },
        { key: "channels.voice.silenceDuration", section: "recording" },
        { key: "channels.voice.maxRecordingDuration", section: "recording" },
        { key: "channels.voice.ledCommand", section: "status" },
        { key: "channels.voice.allowFrom", section: "access" },
      ],
    },
  },
} satisfies ChannelUiContribution;
