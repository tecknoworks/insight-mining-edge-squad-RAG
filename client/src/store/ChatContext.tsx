import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from 'react';
import type { ChatCitation } from '../api';

/** One turn as the panel renders it. Assistant turns carry their citations. */
export interface ChatTurn {
  role: 'user' | 'assistant';
  content: string;
  citations?: ChatCitation[];
}

export interface ChatState {
  /** null until the first answer comes back with an assigned id. */
  conversationId: string | null;
  setConversationId: (id: string | null) => void;

  turns: ChatTurn[];
  setTurns: Dispatch<SetStateAction<ChatTurn[]>>;

  /** The answer currently arriving, token by token. null when idle. */
  streamingAnswer: string | null;
  setStreamingAnswer: Dispatch<SetStateAction<string | null>>;

  isStreaming: boolean;
  setIsStreaming: (streaming: boolean) => void;

  chatError: string | null;
  setChatError: (error: string | null) => void;

  /** Clear everything — used when the selected dataset changes. */
  resetConversation: () => void;
}

const ChatContext = createContext<ChatState | undefined>(undefined);

export function ChatProvider({ children }: { children: ReactNode }) {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [streamingAnswer, setStreamingAnswer] = useState<string | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);

  // A conversation is bound to one dataset server-side, so switching datasets
  // must start a new one rather than carry the old id across.
  const resetConversation = useCallback(() => {
    setConversationId(null);
    setTurns([]);
    setStreamingAnswer(null);
    setIsStreaming(false);
    setChatError(null);
  }, []);

  const value = useMemo(
    () => ({
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
    }),
    [conversationId, turns, streamingAnswer, isStreaming, chatError, resetConversation],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat(): ChatState {
  const ctx = useContext(ChatContext);
  if (ctx === undefined) {
    throw new Error('useChat must be used within a ChatProvider');
  }
  return ctx;
}
