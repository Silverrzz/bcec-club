export type ThemePreference = "light" | "dark" | "system";
export type FeedbackTone = "neutral" | "info" | "success" | "warning" | "danger";

export interface ToastOptions {
  title?: string;
  duration?: number;
  actionLabel?: string;
  onAction?: () => void;
}

export interface Toast extends ToastOptions {
  id: number;
  message: string;
  tone: Exclude<FeedbackTone, "neutral">;
}

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
}

export interface SelectOption {
  label: string;
  value: string | number;
  disabled?: boolean;
}

export interface TabItem {
  value: string;
  label: string;
  count?: number;
  disabled?: boolean;
}
