import { ApiError } from "@/api/client";
import { useToastStore } from "@/stores/toasts";
import type { ToastOptions } from "@/types/ui";

function messageFrom(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message) return error.message;
  if (typeof error === "string") return error;
  return "Something went wrong. Please try again.";
}

export function useToast() {
  const store = useToastStore();

  function error(reason: unknown, options?: ToastOptions): number {
    if (reason instanceof ApiError && reason.status === 401) return 0;
    return store.add("danger", messageFrom(reason), { ...options, duration: options?.duration ?? 0 });
  }

  return {
    success: (message: string, options?: ToastOptions) => store.add("success", message, options),
    info: (message: string, options?: ToastOptions) => store.add("info", message, options),
    warning: (message: string, options?: ToastOptions) => store.add("warning", message, options),
    error,
    dismiss: store.remove,
    clear: store.clear,
  };
}
