import { EventSourceParserStream } from "eventsource-parser/stream";
import { parseEvent, type EventEnvelope } from "./events";
import { apiFetch } from "./api";

export interface SSEClientOptions {
  sessionId: string;
  turnId: string;
  onEvent: (event: EventEnvelope) => void;
  onError?: (error: Error) => void;
  onClose?: () => void;
  maxRetries?: number;
}

/**
 * Ringbuffer that reorders SSE events by sequence number and emits them
 * strictly in order, as specified in CLAUDE.md.
 */
class RingBuffer {
  private ring = new Map<number, EventEnvelope>();
  private nextEmit = 1;
  private emitter: (event: EventEnvelope) => void;

  constructor(emitter: (event: EventEnvelope) => void) {
    this.emitter = emitter;
  }

  push(event: EventEnvelope) {
    this.ring.set(event.sequence, event);
    while (this.ring.has(this.nextEmit)) {
      this.emitter(this.ring.get(this.nextEmit)!);
      this.ring.delete(this.nextEmit);
      this.nextEmit++;
    }
  }

  get resumeSequence(): number {
    return this.nextEmit;
  }
}

/**
 * Creates an SSE connection to the orchestrator stream endpoint.
 * Returns a cleanup function to close the connection.
 */
export function createSSEClient(options: SSEClientOptions): () => void {
  const {
    sessionId,
    turnId,
    onEvent,
    onError,
    onClose,
    maxRetries = 5,
  } = options;

  let abortController = new AbortController();
  let retryCount = 0;
  let closed = false;
  const ringBuffer = new RingBuffer(onEvent);

  async function connect() {
    if (closed) return;

    const sinceSequence = ringBuffer.resumeSequence;
    const params = new URLSearchParams({
      session_id: sessionId,
      turn_id: turnId,
      ...(sinceSequence > 1 && { since_sequence: String(sinceSequence) }),
    });

    try {
      abortController = new AbortController();
      // fetch-based rather than EventSource; apiFetch sends the session cookie
      // (the equivalent of EventSource withCredentials) and handles 401.
      const response = await apiFetch(`/api/stream?${params}`, {
        signal: abortController.signal,
        headers: { Accept: "text/event-stream" },
      });

      if (response.status === 403) {
        closed = true;
        onError?.(new Error("You don't have access to this conversation."));
        onClose?.();
        return;
      }
      if (!response.ok) {
        throw new Error(`SSE connection failed: ${response.status}`);
      }

      if (!response.body) {
        throw new Error("SSE response has no body");
      }

      retryCount = 0;

      const stream = response.body
        .pipeThrough(new TextDecoderStream())
        .pipeThrough(new EventSourceParserStream());

      const reader = stream.getReader();

      while (true) {
        const { done, value } = await reader.read();
        if (done || closed) break;

        if (value.data) {
          try {
            const data = JSON.parse(value.data);
            const event = parseEvent(data);
            ringBuffer.push(event);

            if (event.event === "final" || event.event === "error") {
              closed = true;
              onClose?.();
              return;
            }
          } catch (parseError) {
            onError?.(
              parseError instanceof Error
                ? parseError
                : new Error(String(parseError))
            );
          }
        }
      }
    } catch (error) {
      if (closed) return;
      if ((error as Error).name === "AbortError") return;

      if (retryCount < maxRetries) {
        retryCount++;
        const backoffMs = Math.min(1000 * 2 ** retryCount, 30000);
        setTimeout(connect, backoffMs);
      } else {
        onError?.(
          new Error(`SSE connection failed after ${maxRetries} retries`)
        );
        onClose?.();
      }
    }
  }

  connect();

  return () => {
    closed = true;
    abortController.abort();
  };
}
