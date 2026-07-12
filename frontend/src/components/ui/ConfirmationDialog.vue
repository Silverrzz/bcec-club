<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from "vue";
import { storeToRefs } from "pinia";

import { useConfirmationStore } from "@/stores/confirmation";
import AppIcon from "./AppIcon.vue";
import BaseButton from "./BaseButton.vue";

const store = useConfirmationStore();
const { pending } = storeToRefs(store);
const dialog = ref<HTMLElement | null>(null);
let previousFocus: HTMLElement | null = null;

function focusableElements(): HTMLElement[] {
  if (!dialog.value) return [];
  return Array.from(
    dialog.value.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  );
}

function onKeydown(event: KeyboardEvent): void {
  if (!pending.value) return;
  if (event.key === "Escape") {
    event.preventDefault();
    store.settle(false);
    return;
  }
  if (event.key !== "Tab") return;
  const elements = focusableElements();
  if (!elements.length) return;
  const first = elements[0];
  const last = elements[elements.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first?.focus();
  }
}

watch(pending, async (current, previous) => {
  if (current) {
    previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKeydown);
    await nextTick();
    const selector = current.tone === "danger" ? "[data-cancel-button]" : "[data-confirm-button]";
    const button = dialog.value?.querySelector<HTMLElement>(selector);
    button?.focus();
  } else if (previous) {
    document.body.style.overflow = "";
    document.removeEventListener("keydown", onKeydown);
    previousFocus?.focus();
    previousFocus = null;
  }
});

onBeforeUnmount(() => {
  document.body.style.overflow = "";
  document.removeEventListener("keydown", onKeydown);
});
</script>

<template>
  <Teleport to="body">
    <Transition name="dialog-fade">
      <div v-if="pending" class="dialog-backdrop" @mousedown.self="store.settle(false)">
        <section
          ref="dialog"
          class="confirm-dialog"
          role="alertdialog"
          aria-modal="true"
          aria-labelledby="confirm-dialog-title"
          aria-describedby="confirm-dialog-message"
        >
          <div class="confirm-dialog__icon" :class="{ 'confirm-dialog__icon--danger': pending.tone === 'danger' }">
            <AppIcon :name="pending.tone === 'danger' ? 'alert-circle' : 'info'" :size="22" />
          </div>
          <div class="confirm-dialog__copy">
            <h2 id="confirm-dialog-title">{{ pending.title }}</h2>
            <p id="confirm-dialog-message">{{ pending.message }}</p>
          </div>
          <div class="confirm-dialog__actions">
            <BaseButton data-cancel-button @click="store.settle(false)">{{ pending.cancelLabel ?? "Cancel" }}</BaseButton>
            <BaseButton
              data-confirm-button
              :variant="pending.tone === 'danger' ? 'danger' : 'primary'"
              @click="store.settle(true)"
            >
              {{ pending.confirmLabel ?? "Confirm" }}
            </BaseButton>
          </div>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.dialog-backdrop {
  position: fixed;
  z-index: 1100;
  inset: 0;
  display: grid;
  place-items: center;
  overflow-y: auto;
  background: var(--color-overlay);
  padding: var(--space-4);
}

.confirm-dialog {
  width: min(100%, 28rem);
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--space-4);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-xl);
  background: var(--color-surface-raised);
  box-shadow: var(--shadow-md);
  padding: clamp(var(--space-5), 3vw, var(--space-6));
}

.confirm-dialog__icon {
  width: 2.5rem;
  height: 2.5rem;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--color-info-soft);
  color: var(--color-info);
}

.confirm-dialog__icon--danger {
  background: var(--color-danger-soft);
  color: var(--color-danger);
}

.confirm-dialog__copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.confirm-dialog__copy h2 {
  font-size: 1.125rem;
}

.confirm-dialog__copy p {
  color: var(--color-text-secondary);
  font-size: 0.875rem;
  text-wrap: pretty;
}

.confirm-dialog__actions {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
  margin-top: var(--space-2);
}

.dialog-fade-enter-active,
.dialog-fade-leave-active {
  transition: opacity var(--transition-base);
}

.dialog-fade-enter-active .confirm-dialog,
.dialog-fade-leave-active .confirm-dialog {
  transition: transform var(--transition-base);
}

.dialog-fade-enter-from,
.dialog-fade-leave-to {
  opacity: 0;
}

.dialog-fade-enter-from .confirm-dialog,
.dialog-fade-leave-to .confirm-dialog {
  transform: translateY(0.5rem) scale(0.98);
}

@media (max-width: 28rem) {
  .confirm-dialog {
    grid-template-columns: 1fr;
  }

  .confirm-dialog__actions {
    grid-column: auto;
    flex-direction: column-reverse;
  }

  .confirm-dialog__actions :deep(.base-button) {
    width: 100%;
  }
}
</style>
