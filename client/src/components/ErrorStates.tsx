interface ErrorStateProps {
  title: string;
  message: string;
  error?: string;
  onRetry: () => void;
}

function ErrorStateLayout({ title, message, error, onRetry }: ErrorStateProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: 400,
        padding: '2rem',
        textAlign: 'center',
      }}
    >
      <h2 style={{ margin: '0 0 0.5rem 0', fontSize: '1.25rem', color: '#d32f2f' }}>{title}</h2>
      <p style={{ margin: '0 0 0.5rem 0', color: '#666' }}>{message}</p>
      {error && (
        <p style={{ margin: '0 0 1.5rem 0', color: '#999', fontSize: '0.875rem' }}>{error}</p>
      )}
      <button onClick={onRetry} style={{ padding: '0.5rem 1rem', cursor: 'pointer' }}>
        Retry
      </button>
    </div>
  );
}

export function MapError({ onRetry, error }: { onRetry: () => void; error?: string }) {
  return (
    <ErrorStateLayout
      title="Failed to load cluster map"
      message="Could not fetch cluster data. Please try again."
      error={error}
      onRetry={onRetry}
    />
  );
}

export function DetailError({ onRetry, error }: { onRetry: () => void; error?: string }) {
  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <p style={{ color: '#d32f2f', marginBottom: '1rem' }}>Failed to load cluster details</p>
      {error && (
        <p style={{ color: '#999', fontSize: '0.875rem', marginBottom: '1rem' }}>{error}</p>
      )}
      <button onClick={onRetry} style={{ padding: '0.5rem 1rem', cursor: 'pointer' }}>
        Retry
      </button>
    </div>
  );
}
