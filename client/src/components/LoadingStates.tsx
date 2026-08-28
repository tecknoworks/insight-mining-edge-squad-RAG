export function MapLoadingSkeleton() {
  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <div
        style={{
          height: 400,
          background: 'linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%)',
          backgroundSize: '200% 100%',
          animation: 'shimmer 2s infinite',
          borderRadius: 8,
          marginBottom: '1rem',
        }}
      />
      <p style={{ color: '#666' }}>Loading cluster map…</p>
      <style>{`
        @keyframes shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
    </div>
  );
}

export function DetailLoadingSkeleton() {
  return (
    <div style={{ padding: '2rem' }}>
      <div
        style={{
          height: 24,
          background: '#e0e0e0',
          borderRadius: 4,
          marginBottom: '1rem',
          width: '60%',
        }}
      />
      <div
        style={{
          height: 16,
          background: '#f0f0f0',
          borderRadius: 4,
          marginBottom: '0.5rem',
        }}
      />
      <div
        style={{
          height: 16,
          background: '#f0f0f0',
          borderRadius: 4,
          marginBottom: '0.5rem',
          width: '80%',
        }}
      />
      <p style={{ color: '#666', marginTop: '1rem' }}>Loading cluster details…</p>
    </div>
  );
}

export function ListLoadingSkeleton() {
  return (
    <div style={{ padding: '1rem' }}>
      {[1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          style={{
            height: 24,
            background: '#f0f0f0',
            borderRadius: 4,
            marginBottom: '0.5rem',
          }}
        />
      ))}
    </div>
  );
}
