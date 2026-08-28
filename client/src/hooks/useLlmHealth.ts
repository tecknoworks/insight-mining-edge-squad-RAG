import { useEffect, useState } from 'react';

interface LlmHealthStatus {
  status: 'ok' | 'error' | 'loading';
  model?: string;
  error?: string;
  inputTokens?: number;
  outputTokens?: number;
}

export function useLlmHealth() {
  const [health, setHealth] = useState<LlmHealthStatus>({ status: 'loading' });

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout

        try {
          const response = await fetch(`${baseUrl}/health/llm`, {
            signal: controller.signal,
          });
          clearTimeout(timeoutId);

          const data = await response.json();

          if (response.ok) {
            setHealth({
              status: 'ok',
              model: data.model,
              inputTokens: data.input_tokens,
              outputTokens: data.output_tokens,
            });
          } else {
            setHealth({ status: 'error', error: data.detail || 'Unknown API error' });
          }
        } catch (fetchError) {
          clearTimeout(timeoutId);
          if (fetchError instanceof Error && fetchError.name === 'AbortError') {
            setHealth({ status: 'error', error: 'Health check timed out (10s)' });
          } else {
            throw fetchError;
          }
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : 'Unknown error';
        console.error('[LLM Health Check] Error:', error);
        setHealth({
          status: 'error',
          error: message,
        });
      }
    };

    checkHealth();
  }, []);

  return health;
}
