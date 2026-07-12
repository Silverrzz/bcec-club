<script setup lang="ts">
import { computed } from "vue";

import type { IconName } from "@/types/icons";

const props = withDefaults(
  defineProps<{
    name: IconName;
    size?: number | string;
    label?: string;
    strokeWidth?: number;
  }>(),
  { size: 20, strokeWidth: 1.8 },
);

const paths: Record<IconName, readonly string[]> = {
  activity: ["M3 12h4l2.5-7 5 14 2.5-7h4"],
  "alert-circle": ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z", "M12 8v5", "M12 17h.01"],
  archive: ["M3 6h18", "M5 6v14h14V6", "M4 2h16v4H4z", "M9 10h6"],
  "arrow-left": ["M19 12H5", "m12 19-7-7 7-7"],
  "arrow-right": ["M5 12h14", "m12 5 7 7-7 7"],
  "book-open": ["M2.5 4.5A3.5 3.5 0 0 1 6 3h5v17H6a3.5 3.5 0 0 0-3.5 1.5z", "M21.5 4.5A3.5 3.5 0 0 0 18 3h-5v17h5a3.5 3.5 0 0 1 3.5 1.5z"],
  check: ["m5 12 4 4L19 6"],
  "check-circle": ["M22 11.1V12a10 10 0 1 1-5.9-9.1", "m9 11 3 3L22 4"],
  "chevron-down": ["m6 9 6 6 6-6"],
  "chevron-left": ["m15 18-6-6 6-6"],
  "chevron-right": ["m9 18 6-6-6-6"],
  clock: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z", "M12 6v6l4 2"],
  close: ["M18 6 6 18", "m6 6 12 12"],
  copy: ["M8 8h12v12H8z", "M16 8V4H4v12h4"],
  download: ["M12 3v12", "m7 10 5 5 5-5", "M5 21h14"],
  edit: ["M12 20h9", "M16.5 3.5a2.1 2.1 0 0 1 3 3L8 18l-4 1 1-4z"],
  engine: ["M7 7h10v10H7z", "M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3", "M10 10h4v4h-4z"],
  "external-link": ["M14 3h7v7", "m10 14 11-11", "M18 13v7H4V6h7"],
  eye: ["M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z", "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z"],
  "eye-off": ["m3 3 18 18", "M10.6 5.2A10.8 10.8 0 0 1 12 5c6.5 0 10 7 10 7a17.4 17.4 0 0 1-2.1 3.2", "M6.6 6.6C3.6 8.4 2 12 2 12s3.5 7 10 7a9.8 9.8 0 0 0 4.1-.9", "M9.9 9.9a3 3 0 0 0 4.2 4.2"],
  filter: ["M4 5h16", "M7 12h10", "M10 19h4"],
  gauge: ["M4.9 19a10 10 0 1 1 14.2 0", "m12 14 4-4", "M12 18h.01"],
  home: ["m3 11 9-8 9 8", "M5 10v10h14V10", "M9 20v-6h6v6"],
  info: ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z", "M12 11v6", "M12 7h.01"],
  "log-out": ["M10 17l5-5-5-5", "M15 12H3", "M15 4h5v16h-5"],
  logo: ["M8.2 21h9.6", "M9 17.5 7.4 21h9.2L15 17.5", "M9 17.5h6c1.5-2.2 2.1-4.3 1.4-6.2-.8-2-2.4-3-4.8-3.3l1-3-2-2-3.2 4.2C5.9 9.1 5.5 12 7 13.5l3-1.5c1.8 1.6 1.2 3.7-1 5.5Z"],
  menu: ["M4 6h16", "M4 12h16", "M4 18h16"],
  "message-square": ["M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4z"],
  moon: ["M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"],
  "more-vertical": ["M12 5h.01", "M12 12h.01", "M12 19h.01"],
  pause: ["M8 5v14", "M16 5v14"],
  play: ["m7 4 13 8-13 8z"],
  plus: ["M12 5v14", "M5 12h14"],
  radio: ["M12 12h.01", "M8.5 8.5a5 5 0 0 0 0 7", "M15.5 8.5a5 5 0 0 1 0 7", "M5.6 5.6a9 9 0 0 0 0 12.8", "M18.4 5.6a9 9 0 0 1 0 12.8"],
  refresh: ["M20 7v5h-5", "M4 17v-5h5", "M6.1 8a7 7 0 0 1 11.6-1.8L20 12", "m4 12 2.3 5.8A7 7 0 0 0 17.9 16"],
  search: ["M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z", "m21 21-4.3-4.3"],
  server: ["M4 3h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z", "M4 13h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2Z", "M6 7h.01M6 17h.01"],
  settings: ["M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z", "M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"],
  stop: ["M6 6h12v12H6z"],
  sun: ["M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z", "M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"],
  tag: ["M20.6 13.6 13.7 20.5a2 2 0 0 1-2.8 0L3.5 13.1a2 2 0 0 1-.6-1.4V4a1 1 0 0 1 1-1h7.7a2 2 0 0 1 1.4.6l7.4 7.4a2 2 0 0 1 .2 2.6Z", "M7.5 7.5h.01"],
  trash: ["M3 6h18", "M8 6V3h8v3", "M19 6l-1 15H6L5 6", "M10 11v5M14 11v5"],
  trophy: ["M8 21h8", "M12 17v4", "M7 4h10v4a5 5 0 0 1-10 0z", "M7 6H3v2a4 4 0 0 0 4 4M17 6h4v2a4 4 0 0 1-4 4"],
  upload: ["M12 21V9", "m7 14 5-5 5 5", "M5 3h14"],
  user: ["M20 21a8 8 0 0 0-16 0", "M12 13a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z"],
  "wifi-off": ["m2 2 20 20", "M8.5 16.5a5 5 0 0 1 7 0", "M5 13a10 10 0 0 1 2.4-1.8M10.7 6.2A15 15 0 0 1 21 9", "M3 9a15 15 0 0 1 3.1-1.7", "M12 20h.01"],
  "x-circle": ["M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z", "m15 9-6 6", "m9 9 6 6"],
};

const dimensions = computed(() => (typeof props.size === "number" ? `${props.size}px` : props.size));
</script>

<template>
  <svg
    class="app-icon"
    :width="dimensions"
    :height="dimensions"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    :stroke-width="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    :aria-hidden="label ? undefined : 'true'"
    :role="label ? 'img' : undefined"
  >
    <title v-if="label">{{ label }}</title>
    <path v-for="path in paths[name]" :key="path" :d="path" />
  </svg>
</template>

<style scoped>
.app-icon {
  flex: 0 0 auto;
}
</style>
