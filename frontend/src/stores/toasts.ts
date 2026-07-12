import { ref } from "vue";
import { defineStore } from "pinia";

import type { Toast, ToastOptions } from "@/types/ui";

type ToastTone = Toast["tone"];

const DEFAULT_DURATION = 5000;

export const useToastStore = defineStore("toasts", () => {
  const items = ref<Toast[]>([]);
  let nextId = 1;
  const timers = new Map<number, number>();

  function remove(id: number): void {
    items.value = items.value.filter((toast) => toast.id !== id);
    const timer = timers.get(id);
    if (timer !== undefined) window.clearTimeout(timer);
    timers.delete(id);
  }

  function add(tone: ToastTone, message: string, options: ToastOptions = {}): number {
    const id = nextId++;
    const toast: Toast = { id, tone, message, ...options };
    items.value.push(toast);
    const duration = options.duration ?? DEFAULT_DURATION;
    if (duration > 0) timers.set(id, window.setTimeout(() => remove(id), duration));
    return id;
  }

  function clear(): void {
    for (const timer of timers.values()) window.clearTimeout(timer);
    timers.clear();
    items.value = [];
  }

  return { items, add, remove, clear };
});
