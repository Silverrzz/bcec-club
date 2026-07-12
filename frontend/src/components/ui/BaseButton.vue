<script setup lang="ts">
import { computed } from "vue";
import { RouterLink, type RouteLocationRaw } from "vue-router";

import BaseSpinner from "./BaseSpinner.vue";

const props = withDefaults(
  defineProps<{
    variant?: "primary" | "secondary" | "ghost" | "danger";
    size?: "small" | "medium" | "large";
    type?: "button" | "submit" | "reset";
    to?: RouteLocationRaw;
    href?: string;
    disabled?: boolean;
    loading?: boolean;
    block?: boolean;
    iconOnly?: boolean;
  }>(),
  {
    variant: "secondary",
    size: "medium",
    type: "button",
  },
);

const component = computed(() => (props.to ? RouterLink : props.href ? "a" : "button"));
const inactive = computed(() => Boolean(props.disabled || props.loading));
</script>

<template>
  <component
    :is="component"
    class="base-button"
    :class="[
      `base-button--${variant}`,
      `base-button--${size}`,
      { 'base-button--block': block, 'base-button--icon': iconOnly },
    ]"
    :to="to"
    :href="href"
    :type="component === 'button' ? type : undefined"
    :disabled="component === 'button' ? inactive : undefined"
    :aria-disabled="component !== 'button' && inactive ? 'true' : undefined"
    :tabindex="component !== 'button' && inactive ? -1 : undefined"
    @click="inactive && $event.preventDefault()"
  >
    <BaseSpinner v-if="loading" :size="size === 'small' ? 14 : 17" label="Working" />
    <slot v-else name="icon" />
    <span v-if="!iconOnly" class="base-button__label"><slot /></span>
    <span v-else class="sr-only"><slot /></span>
    <slot name="trailing" />
  </component>
</template>

<style scoped>
.base-button {
  min-height: var(--control-height);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  cursor: pointer;
  font-weight: 640;
  line-height: 1.2;
  text-align: center;
  text-decoration: none;
  transition:
    background-color var(--transition-fast),
    border-color var(--transition-fast),
    color var(--transition-fast),
    box-shadow var(--transition-fast),
    transform var(--transition-fast);
  user-select: none;
}

.base-button:hover:not([disabled], [aria-disabled="true"]) {
  text-decoration: none;
}

.base-button:active:not([disabled], [aria-disabled="true"]) {
  transform: translateY(1px);
}

.base-button[disabled],
.base-button[aria-disabled="true"] {
  cursor: not-allowed;
  opacity: 0.55;
}

.base-button--primary {
  background: var(--color-primary);
  color: var(--color-on-primary);
  box-shadow: var(--shadow-xs);
}

.base-button--primary:hover:not([disabled], [aria-disabled="true"]) {
  background: var(--color-primary-hover);
}

.base-button--secondary {
  border-color: var(--color-border-strong);
  background: var(--color-surface-raised);
  color: var(--color-text);
  box-shadow: var(--shadow-xs);
}

.base-button--secondary:hover:not([disabled], [aria-disabled="true"]),
.base-button--ghost:hover:not([disabled], [aria-disabled="true"]) {
  border-color: var(--color-border-strong);
  background: var(--color-surface-hover);
}

.base-button--ghost {
  background: transparent;
  color: var(--color-text-secondary);
}

.base-button--danger {
  background: var(--color-danger);
  color: var(--color-on-danger);
}

.base-button--danger:hover:not([disabled], [aria-disabled="true"]) {
  background: var(--color-danger-hover);
}

.base-button--small {
  min-height: 2.125rem;
  padding: 0.45rem 0.7rem;
  font-size: 0.8125rem;
}

.base-button--medium {
  padding: 0.625rem 0.9rem;
  font-size: 0.875rem;
}

.base-button--large {
  min-height: 3rem;
  padding: 0.75rem 1.125rem;
  font-size: 0.9375rem;
}

.base-button--block {
  width: 100%;
}

.base-button--icon {
  width: var(--control-height);
  padding: 0;
}

.base-button--icon.base-button--small {
  width: 2.125rem;
}

.base-button--icon.base-button--large {
  width: 3rem;
}

.base-button__label {
  min-width: 0;
}
</style>
