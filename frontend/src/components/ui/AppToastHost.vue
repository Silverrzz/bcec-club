<script setup lang="ts">
import { storeToRefs } from "pinia";

import { useToastStore } from "@/stores/toasts";
import AppIcon from "./AppIcon.vue";
import type { IconName } from "@/types/icons";

const store = useToastStore();
const { items } = storeToRefs(store);

function iconFor(tone: string): IconName {
  if (tone === "success") return "check-circle";
  if (tone === "danger") return "alert-circle";
  if (tone === "warning") return "alert-circle";
  return "info";
}

function runAction(id: number, action?: () => void): void {
  action?.();
  store.remove(id);
}
</script>

<template>
  <div class="toast-region" aria-live="polite" aria-atomic="false">
    <TransitionGroup name="toast-list">
      <div
        v-for="toast in items"
        :key="toast.id"
        class="toast"
        :class="`toast--${toast.tone}`"
        :role="toast.tone === 'danger' ? 'alert' : 'status'"
      >
        <AppIcon class="toast__icon" :name="iconFor(toast.tone)" :size="20" />
        <div class="toast__copy">
          <strong v-if="toast.title">{{ toast.title }}</strong>
          <p>{{ toast.message }}</p>
          <button v-if="toast.actionLabel" class="toast__action" type="button" @click="runAction(toast.id, toast.onAction)">
            {{ toast.actionLabel }}
          </button>
        </div>
        <button class="toast__close" type="button" aria-label="Dismiss notification" @click="store.remove(toast.id)">
          <AppIcon name="close" :size="17" />
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-region {
  position: fixed;
  z-index: 1000;
  right: max(var(--space-4), env(safe-area-inset-right));
  bottom: max(var(--space-4), env(safe-area-inset-bottom));
  width: min(24rem, calc(100vw - 2rem));
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  pointer-events: none;
}

.toast {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: var(--space-3);
  border: 1px solid var(--color-border-strong);
  border-left: 3px solid currentColor;
  border-radius: var(--radius-md);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-md);
  padding: var(--space-4);
  color: var(--color-info);
  pointer-events: auto;
}

.toast--success {
  color: var(--color-success);
}

.toast--warning {
  color: var(--color-warning);
}

.toast--danger {
  color: var(--color-danger);
}

.toast__icon {
  margin-top: 0.1rem;
}

.toast__copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.toast__copy strong {
  color: var(--color-text);
  font-size: 0.875rem;
}

.toast__copy p {
  overflow-wrap: anywhere;
  color: var(--color-text-secondary);
  font-size: 0.875rem;
}

.toast__action {
  width: fit-content;
  background: none;
  color: currentColor;
  cursor: pointer;
  padding: var(--space-1) 0 0;
  font-size: 0.8125rem;
  font-weight: 680;
}

.toast__close {
  width: 1.75rem;
  height: 1.75rem;
  display: grid;
  place-items: center;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--color-text-muted);
  cursor: pointer;
}

.toast__close:hover {
  background: var(--color-surface-hover);
  color: var(--color-text);
}

.toast-list-enter-active,
.toast-list-leave-active {
  transition:
    opacity var(--transition-base),
    transform var(--transition-base);
}

.toast-list-enter-from,
.toast-list-leave-to {
  opacity: 0;
  transform: translateY(0.75rem);
}
</style>
