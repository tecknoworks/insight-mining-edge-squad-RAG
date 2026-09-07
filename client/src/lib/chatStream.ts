// Hand-rolled SSE reader for POST /chat/messages.
//
// This lives outside src/api/ on purpose: that directory is generated from the
// backend's OpenAPI schema and must never be hand-edited, and the generated
// fetch client cannot consume a streaming response body. The request and
// citation *shapes* still come from the generated types, so they stay in sync
// with the backend.
import { client } from '../api/client.gen';
import type { ChatCitation, ChatMessageRequest } from '../api';

export interface ChatStreamHandlers {
  /** One incremental chunk of the answer. Append it; do not replace. */
  onToken: (text: string) => void;
  /** Emitted once, after the last token. May legitimately be empty. */
  onCitations: (items: ChatCitation[]) => void;
  /** Terminal success. */
  onDone: (conversationId: string, messageId: string) => void;
  /** Terminal failure — no done event will follow. */
  onError: (message: string) => void;
}

function resolveBaseUrl(): string {
  // Read it back off the generated client rather than re-deriving it from an
  // env var, which is how hooks/useLlmHealth.ts drifted onto a different
  // variable name than lib/apiClient.ts uses.
  return client.getConfig().baseUrl ?? 'http://localhost:8000';
}

/**
 * Parse one SSE frame into its event name and data payload.
 *
 * Returns null for frames that carry no event — notably the `:` keepalive
 * comments the server injects when the first token takes a while, which a
 * parser that assumed every frame has an `event:` line would choke on.
 */
function parseFrame(raw: string): { event: string | null; data: string } | null {
  let event: string | null = null;
  const dataParts: string[] = [];

  for (const line of raw.split('\n')) {
    if (line === '' || line.startsWith(':')) continue; // blank or keepalive comment

    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1); // SSE strips one leading space

    if (field === 'event') event = value;
    else if (field === 'data') dataParts.push(value);
  }

  if (event === null && dataParts.length === 0) return null;
  return { event, data: dataParts.join('\n') };
}

function dispatch(
  frame: { event: string | null; data: string },
  handlers: ChatStreamHandlers,
): boolean {
  let payload: unknown;
  try {
    payload = JSON.parse(frame.data);
  } catch {
    // A frame we cannot parse is not worth tearing the stream down over.
    return false;
  }

  switch (frame.event) {
    case 'token':
      handlers.onToken((payload as { text: string }).text);
      return false;
    case 'citations':
      handlers.onCitations((payload as { items: ChatCitation[] }).items);
      return false;
    case 'done': {
      const done = payload as { conversation_id: string; message_id: string };
      handlers.onDone(done.conversation_id, done.message_id);
      return true;
    }
    case 'error':
      handlers.onError((payload as { message: string }).message);
      return true;
    default:
      return false;
  }
}

/**
 * Send a chat message and stream the grounded answer.
 *
 * Resolves once the stream terminates. Exactly one of `onDone` / `onError` is
 * invoked, so a caller can always clear its loading state.
 */
export async function streamChatMessage(
  body: ChatMessageRequest,
  handlers: ChatStreamHandlers,
  options: { signal?: AbortSignal } = {},
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${resolveBaseUrl()}/chat/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') return;
    handlers.onError(error instanceof Error ? error.message : 'Could not reach the server');
    return;
  }

  // 404 / 422 / 503 arrive as ordinary JSON, because everything that can fail
  // is resolved before the stream starts.
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === 'string') detail = body.detail;
    } catch {
      // keep the status-derived message
    }
    handlers.onError(detail);
    return;
  }

  if (!response.body) {
    handlers.onError('The server sent no response body');
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let terminated = false;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n');

      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);

        const frame = parseFrame(raw);
        if (frame && dispatch(frame, handlers)) {
          terminated = true;
          break;
        }
        boundary = buffer.indexOf('\n\n');
      }
      if (terminated) break;
    }
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') return;
    handlers.onError(error instanceof Error ? error.message : 'The stream failed');
    return;
  } finally {
    void reader.cancel().catch(() => undefined);
  }

  if (!terminated) {
    // The stream closed without a done or error frame — a dropped connection.
    // Surface it so the UI never sits on a spinner forever.
    handlers.onError('The connection closed before the answer finished');
  }
}
