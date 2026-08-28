import { useLlmHealth } from '../hooks';

export function LlmHealthStatus() {
  const health = useLlmHealth();

  if (health.status === 'loading') {
    return (
      <div style={{ fontSize: '0.875rem', color: '#999', padding: '0.5rem 1rem' }}>
        Checking LLM health...
      </div>
    );
  }

  if (health.status === 'ok') {
    return (
      <div style={{ fontSize: '0.875rem', color: '#28a745', padding: '0.5rem 1rem' }}>
        ✓ LLM ready ({health.model})
        {health.inputTokens !== undefined && (
          <span style={{ marginLeft: '0.5rem', color: '#666' }}>
            ({health.inputTokens}→{health.outputTokens} tokens)
          </span>
        )}
      </div>
    );
  }

  return (
    <div style={{ fontSize: '0.875rem', color: '#d32f2f', padding: '0.5rem 1rem' }}>
      ✗ LLM unavailable: {health.error}
    </div>
  );
}
