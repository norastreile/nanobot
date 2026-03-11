import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

export default {
  presentation: {
    displayName: "Voice",
    initials: "VO",
    color: "#ffc916",
    logoUrl:
      "https://img.alicdn.com/imgextra/i3/O1CN01WMvMRG1ks3Ixc9x1v_!!6000000004738-55-tps-32-32.svg",
    setup: {
      mode: "credentials",
      docsUrl: chatAppGuideUrl("voice"),
      fields: [
        { key: "channels.voice.picovoice_access_key" },
        { key: "channels.voice.wake_word_model" },
        { key: "channels.voice.wake_word_keywords" },
        { key: "channels.voice.wake_word_keyword_paths" },
        { key: "channels.voice.wake_word_sensitivities" },
        { key: "channels.voice.audio_device_index" },
        { key: "channels.voice.silence_threshold" },
        { key: "channels.voice.silence_duration" },
        { key: "channels.voice.max_recording_duration" },
        { key: "channels.voice.tts_voice" },
        { key: "channels.voice.allowFrom" },
      ],
    },
  },
} satisfies ChannelUiContribution;
