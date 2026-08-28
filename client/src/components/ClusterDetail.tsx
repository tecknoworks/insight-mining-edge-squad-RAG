import { useEffect, useState } from 'react';
import { useDataset } from '../store/DatasetContext';
import { listClusterItems, getClusterSummary } from '../api';
import { DetailLoadingSkeleton } from './LoadingStates';
import { DetailError } from './ErrorStates';
import type { ClusterItemPage, ClusterSummary } from '../api';

interface ClusterDetailProps {
  cluster: ClusterSummary | null;
}

export function ClusterDetail({ cluster }: ClusterDetailProps) {
  const {
    clusterSummary,
    setClusterSummary,
    isSummaryLoading,
    setIsSummaryLoading,
    summaryError,
    setSummaryError,
  } = useDataset();

  const [items, setItems] = useState<ClusterItemPage[]>([]);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [itemsError, setItemsError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(0);
  const itemsPerPage = 5;

  const isNoise = cluster?.id === null;

  useEffect(() => {
    if (!cluster || isNoise) return;

    setIsSummaryLoading(true);
    setSummaryError(null);

    getClusterSummary({ path: { cluster_id: cluster.id } })
      .then((res) => {
        if (res.data) {
          setClusterSummary(res.data);
        }
      })
      .catch((err) => {
        setSummaryError(err?.message || 'Failed to load cluster summary');
      })
      .finally(() => setIsSummaryLoading(false));
  }, [cluster, isNoise, setIsSummaryLoading, setSummaryError, setClusterSummary]);

  useEffect(() => {
    if (!cluster || isNoise) return;

    setItemsLoading(true);
    setItemsError(null);
    setCurrentPage(0);

    listClusterItems({ path: { cluster_id: cluster.id } })
      .then((res) => {
        if (res.data?.items) {
          setItems(res.data.items);
        }
      })
      .catch((err) => {
        setItemsError(err?.message || 'Failed to load cluster items');
      })
      .finally(() => setItemsLoading(false));
  }, [cluster, isNoise]);

  if (!cluster) {
    return (
      <div style={{ width: '50%', padding: '2rem', textAlign: 'center', color: '#999' }}>
        Select a cluster to view details
      </div>
    );
  }

  const label = cluster.label || (isNoise ? 'Unclustered' : `Cluster ${cluster.cluster_index}`);

  if (isNoise) {
    return (
      <div
        style={{
          width: '50%',
          padding: '2rem',
        }}
      >
        <h2 style={{ margin: '0 0 1rem 0' }}>{label}</h2>
        <p style={{ color: '#666', marginBottom: '1.5rem' }}>
          These {cluster.item_count} feedback items did not belong to any cluster.
        </p>
        {itemsLoading && <DetailLoadingSkeleton />}
        {itemsError && <DetailError onRetry={() => setItemsLoading(true)} error={itemsError} />}
        {!itemsLoading && !itemsError && (
          <div>
            <h3
              style={{
                fontSize: '0.875rem',
                textTransform: 'uppercase',
                color: '#999',
                marginTop: '1.5rem',
              }}
            >
              Items
            </h3>
            {items
              .slice(currentPage * itemsPerPage, (currentPage + 1) * itemsPerPage)
              .map((item) => (
                <div
                  key={item.id}
                  style={{ padding: '0.75rem 0', borderBottom: '1px solid #f0f0f0' }}
                >
                  <p style={{ margin: '0 0 0.25rem 0', fontSize: '0.875rem' }}>
                    {item.feedback_text}
                  </p>
                  {item.source && (
                    <p style={{ margin: 0, fontSize: '0.75rem', color: '#999' }}>
                      Source: {item.source}
                    </p>
                  )}
                </div>
              ))}
            {items.length > itemsPerPage && (
              <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
                <button
                  onClick={() => setCurrentPage(Math.max(0, currentPage - 1))}
                  disabled={currentPage === 0}
                  style={{
                    padding: '0.5rem 1rem',
                    cursor: currentPage === 0 ? 'not-allowed' : 'pointer',
                  }}
                >
                  ← Previous
                </button>
                <span style={{ alignSelf: 'center', fontSize: '0.875rem', color: '#666' }}>
                  Page {currentPage + 1} of {Math.ceil(items.length / itemsPerPage)}
                </span>
                <button
                  onClick={() =>
                    setCurrentPage(
                      Math.min(Math.ceil(items.length / itemsPerPage) - 1, currentPage + 1),
                    )
                  }
                  disabled={currentPage >= Math.ceil(items.length / itemsPerPage) - 1}
                  style={{
                    padding: '0.5rem 1rem',
                    cursor:
                      currentPage >= Math.ceil(items.length / itemsPerPage) - 1
                        ? 'not-allowed'
                        : 'pointer',
                  }}
                >
                  Next →
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      style={{
        width: '50%',
        padding: '2rem',
        overflowY: 'auto',
        maxHeight: 'calc(100vh - 200px)',
      }}
    >
      {isSummaryLoading && <DetailLoadingSkeleton />}
      {summaryError && <DetailError onRetry={() => {}} error={summaryError} />}
      {!isSummaryLoading && !summaryError && (
        <>
          <h2 style={{ margin: '0 0 0.5rem 0' }}>{label}</h2>
          <p style={{ margin: '0 0 1.5rem 0', color: '#666', fontSize: '0.875rem' }}>
            {cluster.item_count} item{cluster.item_count !== 1 ? 's' : ''}
          </p>

          {clusterSummary && (
            <>
              <div style={{ marginBottom: '1.5rem' }}>
                <h3
                  style={{
                    fontSize: '0.875rem',
                    textTransform: 'uppercase',
                    color: '#999',
                    margin: '0 0 0.5rem 0',
                  }}
                >
                  Summary
                </h3>
                <p style={{ margin: 0, lineHeight: 1.5 }}>{clusterSummary.summary}</p>
              </div>

              {clusterSummary.quotes && clusterSummary.quotes.length > 0 && (
                <div style={{ marginBottom: '1.5rem' }}>
                  <h3
                    style={{
                      fontSize: '0.875rem',
                      textTransform: 'uppercase',
                      color: '#999',
                      margin: '0 0 0.5rem 0',
                    }}
                  >
                    Representative Quotes
                  </h3>
                  {clusterSummary.quotes.map((quote, i) => (
                    <blockquote
                      key={i}
                      style={{
                        margin: '0.75rem 0',
                        padding: '0.75rem',
                        borderLeft: '3px solid #1976d2',
                        background: '#f5f5f5',
                        fontSize: '0.875rem',
                        fontStyle: 'italic',
                      }}
                    >
                      "{quote.text}"
                    </blockquote>
                  ))}
                </div>
              )}
            </>
          )}

          <div>
            <h3
              style={{
                fontSize: '0.875rem',
                textTransform: 'uppercase',
                color: '#999',
                margin: '1.5rem 0 0.5rem 0',
              }}
            >
              Items
            </h3>
            {itemsLoading && <DetailLoadingSkeleton />}
            {itemsError && <DetailError onRetry={() => setItemsLoading(true)} error={itemsError} />}
            {!itemsLoading && !itemsError && (
              <>
                {items
                  .slice(currentPage * itemsPerPage, (currentPage + 1) * itemsPerPage)
                  .map((item) => (
                    <div
                      key={item.id}
                      style={{ padding: '0.75rem 0', borderBottom: '1px solid #f0f0f0' }}
                    >
                      <p style={{ margin: '0 0 0.25rem 0', fontSize: '0.875rem' }}>
                        {item.feedback_text}
                      </p>
                      {item.source && (
                        <p style={{ margin: 0, fontSize: '0.75rem', color: '#999' }}>
                          Source: {item.source}
                        </p>
                      )}
                    </div>
                  ))}
                {items.length > itemsPerPage && (
                  <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
                    <button
                      onClick={() => setCurrentPage(Math.max(0, currentPage - 1))}
                      disabled={currentPage === 0}
                      style={{
                        padding: '0.5rem 1rem',
                        cursor: currentPage === 0 ? 'not-allowed' : 'pointer',
                      }}
                    >
                      ← Previous
                    </button>
                    <span style={{ alignSelf: 'center', fontSize: '0.875rem', color: '#666' }}>
                      Page {currentPage + 1} of {Math.ceil(items.length / itemsPerPage)}
                    </span>
                    <button
                      onClick={() =>
                        setCurrentPage(
                          Math.min(Math.ceil(items.length / itemsPerPage) - 1, currentPage + 1),
                        )
                      }
                      disabled={currentPage >= Math.ceil(items.length / itemsPerPage) - 1}
                      style={{
                        padding: '0.5rem 1rem',
                        cursor:
                          currentPage >= Math.ceil(items.length / itemsPerPage) - 1
                            ? 'not-allowed'
                            : 'pointer',
                      }}
                    >
                      Next →
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}
