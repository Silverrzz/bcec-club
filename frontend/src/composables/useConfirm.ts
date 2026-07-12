import { useConfirmationStore } from "@/stores/confirmation";
import type { ConfirmOptions } from "@/types/ui";

export function useConfirm() {
  const store = useConfirmationStore();
  return {
    confirm: (options: ConfirmOptions) => store.open(options),
  };
}
