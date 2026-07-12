import { ref } from "vue";
import { defineStore } from "pinia";

import type { ConfirmOptions } from "@/types/ui";

interface PendingConfirmation extends ConfirmOptions {
  resolve: (confirmed: boolean) => void;
}

export const useConfirmationStore = defineStore("confirmation", () => {
  const pending = ref<PendingConfirmation | null>(null);

  function open(options: ConfirmOptions): Promise<boolean> {
    if (pending.value) pending.value.resolve(false);
    return new Promise<boolean>((resolve) => {
      pending.value = { ...options, resolve };
    });
  }

  function settle(confirmed: boolean): void {
    const current = pending.value;
    pending.value = null;
    current?.resolve(confirmed);
  }

  return { pending, open, settle };
});
