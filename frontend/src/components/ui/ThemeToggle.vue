<script setup lang="ts">
import { computed } from "vue";

import { useTheme } from "@/composables/useTheme";
import AppIcon from "./AppIcon.vue";
import BaseButton from "./BaseButton.vue";

const { resolvedTheme, toggleTheme } = useTheme();
const label = computed(() => (resolvedTheme.value === "dark" ? "Use light theme" : "Use dark theme"));
</script>

<template>
  <BaseButton variant="ghost" size="small" icon-only :title="label" :aria-label="label" @click="toggleTheme">
    <template #icon><AppIcon :name="resolvedTheme === 'dark' ? 'sun' : 'moon'" :size="18" /></template>
    {{ label }}
  </BaseButton>
</template>
