import { useEffect, useRef, useState } from 'react';
import { useDataset } from '../store/DatasetContext';
import { useChat, type ChatTurn } from '../store/ChatContext';
import { streamChatMessage } from '../lib/chatStream';
import type { ChatCitation, ChatFilters } from '../api';

interface CitationChipsProps {
  citations: ChatCitation[];
}

/** Bracketed chips under an answer; clicking one reveals the feedback behind it. */
function CitationChips({ citations }: CitationChipsProps) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (citations.length === 0) return null;

  return (
    <div style={{ marginTop: '0.5rem' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
        {citations.map((citation, index) => (
          <button
            key={citation.feedback_item_id}
            type="button"
            onClick={() => setExpanded(expanded === index ? null : index)}
            aria-expanded={expanded === index}
            style={{
              fontSize: '0.75rem',
              padding: '0.125rem 0.5rem',
              borderRadius: 12,
              border: '1px solid #1976d2',
              background: expanded === index ? '#1976d2' : '#e3f2fd',
              color: expanded === index ? '#fff' : '#1976d2',
              cursor: 'pointer',
            }}
          >
            [{index + 1}]
          </button>
        ))}
      </div>

      {expanded !== null && (
        <blockquote
          style={{
            margin: '0.5rem 0 0 0',
            padding: '0.75rem',
            borderLeft: '3px solid #1976d2',
            background: '#f5f5f5',
            fontSize: '0.875rem',
            fontStyle: 'italic',
          }}
        >
          &quot;{citations[expanded].excerpt}&quot;
          <div
            style={{
              marginTop: '0.25rem',
              fontSize: '0.75rem',
              color: '#999',
              fontStyle: 'normal',
            }}
          >
            {citations[expanded].source ?? 'unknown source'}
            {citations[expanded].date ? ` · ${citations[expanded].date.slice(0, 10)}` : ''}
          </div>
        </blockquote>
      )}
    </div>
  );
}

function TurnBubble({ turn }: { turn: ChatTurn }) {
  const isUser = turn.role === 'user';
  return (
    <div style={{ marginBottom: '1rem' }}>
      <div
        style={{
          fontSize: '0.75rem',
          textTransform: 'uppercase',
          color: '#999',
          marginBottom: '0.25rem',
        }}
      >
        {isUser ? 'You' : 'Insight Miner'}
      </div>
      <p style={{ margin: 0, fontSize: '0.875rem', whiteSpace: 'pre-wrap' }}>{turn.content}</p>
      {!isUser && turn.citations && <CitationChips citations={turn.citations} />}
    </div>
  );
}

export function ChatPanel() {
  const { dataset, sourceFilter, dateRangeStart, dateRangeEnd } = useDataset();
  const {
    conversationId,
    setConversationId,
    turns,
    setTurns,
    streamingAnswer,
    setStreamingAnswer,
    isStreaming,
    setIsStreaming,
    chatError,
    setChatError,
    resetConversation,
  } = useChat();

  const [draft, setDraft] = useState('');
  const transcriptRef = useRef<HTMLDivElement>(null);

  // A conversation belongs to one dataset server-side, so switching datasets
  // has to start a fresh one.
  const datasetId = dataset?.id;
  useEffect(() => {
    resetConversation();
  }, [datasetId, resetConversation]);

  // Keep the newest content in view as tokens arrive. Assigning scrollTop
  // rather than calling scrollTo: the latter is absent in jsdom and in some
  // older engines, and this needs no smooth-scroll behaviour.
  useEffect(() => {
    const transcript = transcriptRef.current;
    if (transcript) transcript.scrollTop = transcript.scrollHeight;
  }, [turns, streamingAnswer]);

  if (!dataset) return null;

  const buildFilters = (): ChatFilters | undefined => {
    if (!sourceFilter && !dateRangeStart && !dateRangeEnd) return undefined;
    return {
      source: sourceFilter ? [sourceFilter] : null,
      date_from: dateRangeStart || null,
      date_to: dateRangeEnd || null,
    };
  };

  const handleSend = async () => {
    const question = draft.trim();
    if (!question || isStreaming) return;

    setDraft('');
    setChatError(null);
    setTurns((previous) => [...previous, { role: 'user', content: question }]);
    setStreamingAnswer('');
    setIsStreaming(true);

    let answer = '';
    let citations: ChatCitation[] = [];

    await streamChatMessage(
      {
        dataset_id: dataset.id,
        message: question,
        conversation_id: conversationId,
        filters: buildFilters(),
      },
      {
        onToken: (text) => {
          answer += text;
          setStreamingAnswer(answer);
        },
        onCitations: (items) => {
          citations = items;
        },
        onDone: (newConversationId) => {
          setConversationId(newConversationId);
          setTurns((previous) => [...previous, { role: 'assistant', content: answer, citations }]);
          setStreamingAnswer(null);
          setIsStreaming(false);
        },
        onError: (message) => {
          setChatError(message);
          // Keep whatever streamed before the failure — discarding it would
          // lose content the user already read.
          if (answer) {
            setTurns((previous) => [...previous, { role: 'assistant', content: answer }]);
          }
          setStreamingAnswer(null);
          setIsStreaming(false);
        },
      },
    );
  };

  return (
    <section
      style={{
        width: '30%',
        display: 'flex',
        flexDirection: 'column',
        borderLeft: '1px solid #e0e0e0',
        minHeight: 0,
      }}
    >
      <h2
        style={{
          fontSize: '0.875rem',
          textTransform: 'uppercase',
          color: '#999',
          margin: 0,
          padding: '1rem 1rem 0.5rem 1rem',
        }}
      >
        Ask the feedback
      </h2>

      <div ref={transcriptRef} style={{ flex: 1, overflowY: 'auto', padding: '0 1rem' }}>
        {turns.length === 0 && !streamingAnswer && (
          <p style={{ fontSize: '0.875rem', color: '#999' }}>
            Ask a question about this feedback — for example, “what are people saying about
            checkout?”. Answers are grounded in the feedback itself and cite the items they use.
          </p>
        )}

        {turns.map((turn, index) => (
          <TurnBubble key={index} turn={turn} />
        ))}

        {streamingAnswer !== null && (
          <div style={{ marginBottom: '1rem' }}>
            <div
              style={{
                fontSize: '0.75rem',
                textTransform: 'uppercase',
                color: '#999',
                marginBottom: '0.25rem',
              }}
            >
              Insight Miner
            </div>
            <p style={{ margin: 0, fontSize: '0.875rem', whiteSpace: 'pre-wrap' }}>
              {streamingAnswer || 'Thinking…'}
            </p>
          </div>
        )}

        {chatError && <p style={{ fontSize: '0.875rem', color: '#d32f2f' }}>✗ {chatError}</p>}
      </div>

      <div
        style={{
          display: 'flex',
          gap: '0.5rem',
          padding: '1rem',
          borderTop: '1px solid #f0f0f0',
        }}
      >
        <label htmlFor="chat-input" style={{ position: 'absolute', left: -9999 }}>
          Ask a question about this feedback
        </label>
        <input
          id="chat-input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              void handleSend();
            }
          }}
          placeholder="What are people saying about…"
          disabled={isStreaming}
          style={{
            flex: 1,
            padding: '0.5rem',
            borderRadius: 4,
            border: '1px solid #ccc',
            fontSize: '0.875rem',
          }}
        />
        <button
          type="button"
          onClick={() => void handleSend()}
          disabled={isStreaming || draft.trim() === ''}
          style={{
            padding: '0.5rem 1rem',
            borderRadius: 4,
            border: 'none',
            background: isStreaming || draft.trim() === '' ? '#e0e0e0' : '#1976d2',
            color: isStreaming || draft.trim() === '' ? '#999' : '#fff',
            cursor: isStreaming || draft.trim() === '' ? 'default' : 'pointer',
            fontSize: '0.875rem',
          }}
        >
          {isStreaming ? 'Asking…' : 'Ask'}
        </button>
      </div>
    </section>
  );
}
