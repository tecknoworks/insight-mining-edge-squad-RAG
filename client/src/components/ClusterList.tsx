import { useEffect, useRef } from 'react';
import { useDataset } from '../store/DatasetContext';
import type { ClusterSummary } from '../api';

interface ClusterListProps {
  clusters: ClusterSummary[];
}

export function ClusterList({ clusters }: ClusterListProps) {
  const { selectedClusterId, setSelectedClusterId } = useDataset();
  const listRef = useRef<HTMLUListElement>(null);
  const itemRefs = useRef<Record<string, HTMLLIElement | null>>({});

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!listRef.current?.contains(document.activeElement)) return;

      // Find which cluster is currently focused
      let focusedId: string | null = null;
      for (const [id, el] of Object.entries(itemRefs.current)) {
        if (el === document.activeElement) {
          focusedId = id;
          break;
        }
      }

      if (!focusedId) return;

      const currentIndex = clusters.findIndex((c) => (c.id ?? 'noise') === focusedId);

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        const nextIndex = (currentIndex + 1) % clusters.length;
        const nextCluster = clusters[nextIndex];
        const nextId = nextCluster.id ?? 'noise';
        itemRefs.current[nextId]?.focus();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        const prevIndex = (currentIndex - 1 + clusters.length) % clusters.length;
        const prevCluster = clusters[prevIndex];
        const prevId = prevCluster.id ?? 'noise';
        itemRefs.current[prevId]?.focus();
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        setSelectedClusterId(focusedId === 'noise' ? null : focusedId);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [clusters, setSelectedClusterId]);

  return (
    <div
      style={{
        width: '25%',
        minWidth: 250,
        borderRight: '1px solid #e0e0e0',
        display: 'flex',
        flexDirection: 'column',
        maxHeight: 'calc(100vh - 200px)',
        overflowY: 'auto',
      }}
    >
      <h3 style={{ padding: '1rem', margin: 0, borderBottom: '1px solid #e0e0e0' }}>Clusters</h3>
      <ul
        ref={listRef}
        style={{
          listStyle: 'none',
          margin: 0,
          padding: 0,
          flex: 1,
          overflowY: 'auto',
        }}
      >
        {clusters.map((cluster) => {
          const isNoise = cluster.id === null;
          const label =
            cluster.label || (isNoise ? 'Unclustered' : `Cluster ${cluster.cluster_index}`);
          const clusterId = cluster.id ?? 'noise';

          return (
            <li
              key={clusterId}
              ref={(el) => {
                if (el) {
                  itemRefs.current[clusterId] = el;
                }
              }}
              onClick={() => setSelectedClusterId(cluster.id)}
              style={
                {
                  padding: '0.75rem 1rem',
                  borderBottom: '1px solid #f0f0f0',
                  cursor: 'pointer',
                  background: selectedClusterId === cluster.id ? '#e3f2fd' : 'white',
                  outline: selectedClusterId === cluster.id ? '2px solid #1976d2' : 'none',
                  opacity: isNoise ? 0.7 : 1,
                } as React.CSSProperties
              }
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  setSelectedClusterId(cluster.id);
                }
              }}
            >
              <div style={{ fontWeight: 500, marginBottom: '0.25rem' }}>{label}</div>
              <div style={{ fontSize: '0.875rem', color: '#666' }}>
                {cluster.item_count} item{cluster.item_count !== 1 ? 's' : ''}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
