import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent, act } from '@testing-library/react';
import { ChatPanel } from '../ChatPanel';
import { DatasetProvider, useDataset } from '../../store/DatasetContext';
import { ChatProvider } from '../../store/ChatContext';
import type { DatasetDetail } from '../../api';
import { useEffect } from 'react';

const mockDataset = {
  id: 'dataset-1',
  filename: 'feedback.csv',
  status: 'embedded',
  row_count_total: 4,
  row_count_accepted: 4,
  row_count_rejected: 0,
  created_at: '2026-03-01T00:00:00Z',
  feedback_items: [],
} as unknown as DatasetDetail;

/** Seeds the dataset into context, since ChatPanel renders nothing without one. */
function SeedDataset() {
  const { setDataset } = useDataset();
  useEffect(() => {
    setDataset(mockDataset);
  }, [setDataset]);
  return null;
}

function renderPanel() {
  return render(
    <DatasetProvider>
      <ChatProvider>
        <SeedDataset />
        <ChatPanel />
      </ChatProvider>
    </DatasetProvider>,
  );
}

/** A ReadableStream is single-use, so each fetch call needs a fresh one. */
function makeSseStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    async start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
        // Yield to the event loop so React can flush a render between chunks —
        // this is what makes incremental rendering observable.
        await new Promise<void>((resolve) => setTimeout(resolve, 0));
      }
      controller.close();
    },
  });
}

/** A fetch stub that streams the given SSE frames, rebuilt on every call. */
function streamingFetch(chunks: string[]) {
  return vi.fn().mockImplementation(
    async () =>
      ({
        ok: true,
        status: 200,
        body: makeSseStream(chunks),
      }) as unknown as Response,
  );
}

function ask(question = 'what about checkout?') {
  fireEvent.change(screen.getByPlaceholderText(/what are people saying about/i), {
    target: { value: question },
  });
  fireEvent.click(screen.getByRole('button', { name: /^ask$/i }));
}

const FRAMES = {
  tokenA: 'event: token\ndata: {"text":"Checkout "}\n\n',
  tokenB: 'event: token\ndata: {"text":"fails at payment [1]."}\n\n',
  citations:
    'event: citations\ndata: {"items":[{"feedback_item_id":"item-1","excerpt":"checkout failed with an error","source":"support ticket","date":"2026-03-01T12:00:00"}]}\n\n',
  done: 'event: done\ndata: {"conversation_id":"conv-1","message_id":"msg-1"}\n\n',
  error: 'event: error\ndata: {"message":"API rate limit exceeded"}\n\n',
  keepalive: ': ping\n\n',
};

describe('ChatPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows a grounded-answer prompt before anything is asked', async () => {
    renderPanel();

    // Matches the empty-state paragraph specifically — the visually-hidden
    // input label repeats the opening words.
    expect(
      await screen.findByText(/answers are grounded in the feedback itself/i),
    ).toBeInTheDocument();
  });

  it('renders tokens incrementally rather than in a single flush', async () => {
    // The test controls when each frame is enqueued, so "the first token is on
    // screen while the rest does not exist yet" is genuinely proven rather
    // than inferred from a flushed stream.
    const encoder = new TextEncoder();
    let push!: (frame: string) => void;
    let finish!: () => void;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        push = (frame) => controller.enqueue(encoder.encode(frame));
        finish = () => controller.close();
      },
    });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, status: 200, body } as unknown as Response),
    );
    renderPanel();
    await screen.findByPlaceholderText(/what are people saying about/i);

    await act(async () => {
      ask();
    });

    await act(async () => {
      push(FRAMES.tokenA);
    });
    // Only the first token has been sent, and it is already rendered.
    expect(await screen.findByText('Checkout')).toBeInTheDocument();
    expect(screen.queryByText(/fails at payment/)).not.toBeInTheDocument();

    await act(async () => {
      push(FRAMES.tokenB);
      push(FRAMES.citations);
      push(FRAMES.done);
      finish();
    });

    expect(await screen.findByText(/Checkout fails at payment \[1\]\./)).toBeInTheDocument();
  });

  it('skips `:` keepalive comment frames without breaking the stream', async () => {
    vi.stubGlobal(
      'fetch',
      streamingFetch([
        FRAMES.keepalive,
        FRAMES.tokenA,
        FRAMES.keepalive,
        FRAMES.tokenB,
        FRAMES.citations,
        FRAMES.done,
      ]),
    );
    renderPanel();
    await screen.findByPlaceholderText(/what are people saying about/i);

    await act(async () => {
      ask();
    });

    await waitFor(() => {
      expect(screen.getByText(/Checkout fails at payment/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/ping/)).not.toBeInTheDocument();
  });

  it('reassembles a citation marker split across chunk boundaries', async () => {
    vi.stubGlobal(
      'fetch',
      streamingFetch([
        'event: token\ndata: {"text":"See [1]."}\n\n'.slice(0, 20),
        'event: token\ndata: {"text":"See [1]."}\n\n'.slice(20),
        FRAMES.citations,
        FRAMES.done,
      ]),
    );
    renderPanel();
    await screen.findByPlaceholderText(/what are people saying about/i);

    await act(async () => {
      ask();
    });

    await waitFor(() => {
      expect(screen.getByText(/See \[1\]\./)).toBeInTheDocument();
    });
  });

  it('shows a citation chip and reveals the source item when clicked', async () => {
    vi.stubGlobal('fetch', streamingFetch([FRAMES.tokenB, FRAMES.citations, FRAMES.done]));
    renderPanel();
    await screen.findByPlaceholderText(/what are people saying about/i);

    await act(async () => {
      ask();
    });

    const chip = await screen.findByRole('button', { name: '[1]' });
    expect(screen.queryByText(/checkout failed with an error/)).not.toBeInTheDocument();

    fireEvent.click(chip);

    expect(await screen.findByText(/checkout failed with an error/)).toBeInTheDocument();
    expect(screen.getByText(/support ticket/)).toBeInTheDocument();
    expect(chip).toHaveAttribute('aria-expanded', 'true');
  });

  it('renders an error frame and stops streaming', async () => {
    vi.stubGlobal('fetch', streamingFetch([FRAMES.tokenA, FRAMES.error]));
    renderPanel();
    await screen.findByPlaceholderText(/what are people saying about/i);

    await act(async () => {
      ask();
    });

    expect(await screen.findByText(/API rate limit exceeded/)).toBeInTheDocument();
    // The partial answer is kept rather than discarded.
    expect(screen.getByText(/Checkout/)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^ask$/i })).toBeInTheDocument();
    });
  });

  it('surfaces a non-streaming HTTP error from the detail body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        json: async () => ({ detail: 'Anthropic API key not configured' }),
      } as unknown as Response),
    );
    renderPanel();
    await screen.findByPlaceholderText(/what are people saying about/i);

    await act(async () => {
      ask();
    });

    expect(await screen.findByText(/Anthropic API key not configured/)).toBeInTheDocument();
  });

  it('reports a stream that closes without done or error', async () => {
    vi.stubGlobal('fetch', streamingFetch([FRAMES.tokenA]));
    renderPanel();
    await screen.findByPlaceholderText(/what are people saying about/i);

    await act(async () => {
      ask();
    });

    expect(
      await screen.findByText(/connection closed before the answer finished/i),
    ).toBeInTheDocument();
  });

  it('sends the conversation id on the second turn', async () => {
    const fetchMock = streamingFetch([FRAMES.tokenB, FRAMES.citations, FRAMES.done]);
    vi.stubGlobal('fetch', fetchMock);
    renderPanel();
    await screen.findByPlaceholderText(/what are people saying about/i);

    await act(async () => {
      ask('first');
    });
    await screen.findByRole('button', { name: '[1]' });

    await act(async () => {
      ask('second');
    });

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
    const secondBody = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(secondBody.conversation_id).toBe('conv-1');
    expect(secondBody.message).toBe('second');
  });

  it('disables the ask button while a question is empty', async () => {
    renderPanel();
    await screen.findByPlaceholderText(/what are people saying about/i);

    expect(screen.getByRole('button', { name: /^ask$/i })).toBeDisabled();
  });

  it('posts to the chat endpoint with the dataset id', async () => {
    const fetchMock = streamingFetch([FRAMES.done]);
    vi.stubGlobal('fetch', fetchMock);
    renderPanel();
    await screen.findByPlaceholderText(/what are people saying about/i);

    await act(async () => {
      ask('why?');
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toContain('/chat/messages');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body as string).dataset_id).toBe('dataset-1');
  });
});
