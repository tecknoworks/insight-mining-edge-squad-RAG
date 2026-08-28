import type { ReactNode } from 'react';

interface EmptyStateProps {
  title: string;
  message: string;
  action?: ReactNode;
}

function EmptyStateLayout({ title, message, action }: EmptyStateProps) {
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
      <h2 style={{ margin: '0 0 0.5rem 0', fontSize: '1.25rem' }}>{title}</h2>
      <p style={{ margin: '0 0 1.5rem 0', color: '#666' }}>{message}</p>
      {action}
    </div>
  );
}

export function NoDatasets() {
  return (
    <EmptyStateLayout
      title="No datasets yet"
      message="Upload a CSV to get started. Your feedback data will appear here."
    />
  );
}

export function NotClustered() {
  return (
    <EmptyStateLayout
      title="No clusters yet"
      message="This dataset has been ingested but not yet clustered. Start a clustering run to analyze patterns."
      action={<button>Start clustering</button>}
    />
  );
}

export function NoClusters() {
  return (
    <EmptyStateLayout
      title="No clusters found"
      message="The clustering run completed but found no clusters. Try adjusting the clustering parameters and running again."
    />
  );
}
