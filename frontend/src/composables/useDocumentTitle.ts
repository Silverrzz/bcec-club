import { onBeforeUnmount, watchEffect, type MaybeRefOrGetter } from "vue";
import { toValue } from "vue";

const DEFAULT_TITLE = "COPE Chess";

export function useDocumentTitle(title: MaybeRefOrGetter<string | null | undefined>): void {
  const stop = watchEffect(() => {
    const value = toValue(title);
    document.title = value ? `${value} | ${DEFAULT_TITLE}` : DEFAULT_TITLE;
  });
  onBeforeUnmount(stop);
}
