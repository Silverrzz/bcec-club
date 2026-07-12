<script setup lang="ts">
import { ref } from "vue";

import { useToast } from "@/composables/useToast";
import AppIcon from "./AppIcon.vue";
import BaseButton from "./BaseButton.vue";

const props = withDefaults(
  defineProps<{
    value: string;
    label?: string;
    successMessage?: string;
    iconOnly?: boolean;
    size?: "small" | "medium";
  }>(),
  {
    label: "Copy",
    successMessage: "Copied to clipboard.",
    size: "small",
  },
);

const copied = ref(false);
const toast = useToast();

async function copy(): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(props.value);
    } else {
      const field = document.createElement("textarea");
      field.value = props.value;
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      const copied = document.execCommand("copy");
      field.remove();
      if (!copied) throw new Error("Clipboard access was denied.");
    }
    copied.value = true;
    toast.success(props.successMessage, { duration: 2500 });
    window.setTimeout(() => (copied.value = false), 1800);
  } catch {
    toast.error("Could not copy to the clipboard.");
  }
}
</script>

<template>
  <BaseButton :size="size" :icon-only="iconOnly" :aria-label="label" @click="copy">
    <template #icon><AppIcon :name="copied ? 'check' : 'copy'" :size="15" /></template>
    {{ copied ? "Copied" : label }}
  </BaseButton>
</template>
