// Placeholder landing page. Its only job right now is to prove the full stack is
// wired: it calls the backend's /health endpoint through the generated typed
// client and reflects the result in app-wide state.
import { useEffect, useState } from 'react';
import { health } from '../api';
import { useAppState } from '../store/AppContext';

type Status = 'checking' | 'ok' | 'error';

export function HomePage() {
  const { apiReady, setApiReady } = useAppState();
  const [status, setStatus] = useState<Status>('checking');

  useEffect(() => {
    health()
      .then((res) => {
        const ok = res.data?.status === 'ok';
        setStatus(ok ? 'ok' : 'error');
        setApiReady(ok);
      })
      .catch(() => setStatus('error'));
  }, [setApiReady]);

  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: '2rem', maxWidth: 640 }}>
      <h1>Insight Miner</h1>
      <p>Semantic customer feedback &amp; insight mining.</p>
      <p>
        Backend: {status === 'checking' && 'checking…'}
        {status === 'ok' && `connected (apiReady=${String(apiReady)})`}
        {status === 'error' && 'unreachable — is the API running on :8000?'}
      </p>
    </main>
  );
}
