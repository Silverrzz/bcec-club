import { onBeforeUnmount, ref, type Ref } from "vue";

export function useAsyncResource<T>(loader: (signal: AbortSignal) => Promise<T>) {
  const data = ref<T | null>(null) as Ref<T | null>;
  const loading = ref(false);
  const error = ref<unknown>(null);
  let controller: AbortController | null = null;

  async function load(): Promise<T | null> {
    controller?.abort();
    controller = new AbortController();
    loading.value = true;
    error.value = null;
    try {
      const result = await loader(controller.signal);
      data.value = result;
      return result;
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === "AbortError")) error.value = reason;
      return null;
    } finally {
      loading.value = false;
    }
  }

  onBeforeUnmount(() => controller?.abort());
  return { data, loading, error, load };
}
