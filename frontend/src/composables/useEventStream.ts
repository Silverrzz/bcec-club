import { onBeforeUnmount, ref, watch, type Ref } from "vue";

export type StreamConnectionState = "idle" | "connecting" | "live" | "reconnecting" | "closed" | "error";

interface EventStreamOptions<T> {
  enabled?: Ref<boolean>;
  event?: string;
  parse?: (data: string) => T;
  onMessage?: (data: T) => void;
}

export function useEventStream<T = unknown>(url: Ref<string> | string, options: EventStreamOptions<T> = {}) {
  const state = ref<StreamConnectionState>("idle");
  const lastEventAt = ref<Date | null>(null);
  const error = ref<string | null>(null);
  let source: EventSource | null = null;
  let hasConnected = false;

  const parse = options.parse ?? ((data: string) => JSON.parse(data) as T);

  function disconnect(): void {
    source?.close();
    source = null;
    state.value = "closed";
  }

  function connect(): void {
    if (options.enabled && !options.enabled.value) return;
    source?.close();
    const target = typeof url === "string" ? url : url.value;
    if (!target) return;

    state.value = hasConnected ? "reconnecting" : "connecting";
    error.value = null;
    source = new EventSource(target, { withCredentials: true });
    source.onopen = () => {
      hasConnected = true;
      state.value = "live";
      error.value = null;
    };
    source.onerror = () => {
      state.value = source?.readyState === EventSource.CLOSED ? "error" : "reconnecting";
      error.value = "Live updates are temporarily unavailable.";
    };

    const listener = (event: MessageEvent<string>) => {
      try {
        const data = parse(event.data);
        lastEventAt.value = new Date();
        options.onMessage?.(data);
      } catch {
        error.value = "A live update could not be read.";
      }
    };
    if (options.event) source.addEventListener(options.event, listener as EventListener);
    else source.onmessage = listener;
  }

  if (typeof url !== "string") watch(url, connect);
  if (options.enabled) watch(options.enabled, (enabled) => (enabled ? connect() : disconnect()), { immediate: true });
  else connect();

  onBeforeUnmount(() => source?.close());

  return { state, lastEventAt, error, connect, disconnect };
}
