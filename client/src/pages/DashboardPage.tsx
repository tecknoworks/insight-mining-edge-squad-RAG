import { useEffect, useState } from 'react';
import { listDatasets, getDataset, getClusterMap } from '../api';
import { useDataset } from '../store/DatasetContext';
import { ClusterList } from '../components/ClusterList';
import { ClusterMap } from '../components/ClusterMap';
import { ClusterDetail } from '../components/ClusterDetail';
import { FilterBar } from '../components/FilterBar';
import { LlmHealthStatus } from '../components/LlmHealthStatus';
import { MapLoadingSkeleton } from '../components/LoadingStates';
import { NoDatasets, NotClustered, NoClusters } from '../components/EmptyStates';
import { MapError } from '../components/ErrorStates';
import type { DatasetSummary } from '../api';

export function DashboardPage() {
  const {
    dataset,
    setDataset,
    clusterMap,
    setClusterMap,
    selectedClusterId,
    isMapLoading,
    setIsMapLoading,
    mapError,
    setMapError,
    sourceFilter,
    dateRangeStart,
    dateRangeEnd,
  } = useDataset();

  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [datasetsLoading, setDatasetsLoading] = useState(true);

  // Load available datasets
  useEffect(() => {
    listDatasets()
      .then((res) => {
        if (res.data) {
          setDatasets(res.data);
          if (res.data.length > 0 && !dataset) {
            // Fetch the full detail for the first dataset
            getDataset({ path: { dataset_id: res.data[0].id } }).then((detailRes) => {
              if (detailRes.data) {
                setDataset(detailRes.data);
              }
            });
          }
        }
      })
      .catch(() => {
        setDatasets([]);
      })
      .finally(() => setDatasetsLoading(false));
  }, [dataset, setDataset]);

  // Load cluster map when dataset changes
  useEffect(() => {
    if (!dataset) return;

    setIsMapLoading(true);
    setMapError(null);

    getClusterMap({ query: { dataset_id: dataset.id } })
      .then((res) => {
        if (res.data) {
          setClusterMap(res.data);
        }
      })
      .catch((err) => {
        const message = err?.message || 'Failed to load cluster map';
        setMapError(message);
        // Check if the dataset is not clustered (would have 0 clusters)
        if (message.includes('404') || message.includes('not found')) {
          setClusterMap(null);
        }
      })
      .finally(() => setIsMapLoading(false));
  }, [dataset, setIsMapLoading, setMapError, setClusterMap]);

  if (datasetsLoading) {
    return (
      <main style={{ padding: '2rem', textAlign: 'center' }}>
        <h1>Loading datasets…</h1>
      </main>
    );
  }

  if (datasets.length === 0) {
    return (
      <main style={{ padding: '2rem' }}>
        <h1>Insight Miner</h1>
        <NoDatasets />
      </main>
    );
  }

  // Apply client-side filtering to clusters and points
  const filteredClusterMap = clusterMap
    ? {
        ...clusterMap,
        points: clusterMap.points.filter((p) => {
          const item = dataset?.feedback_items?.find((fi) => fi.id === p.feedback_item_id);
          if (!item) return false;
          if (sourceFilter && item.source !== sourceFilter) return false;
          if (dateRangeStart && item.submitted_at && item.submitted_at < dateRangeStart)
            return false;
          if (dateRangeEnd && item.submitted_at && item.submitted_at > dateRangeEnd) return false;
          return true;
        }),
      }
    : null;

  const isNotClustered =
    dataset &&
    clusterMap &&
    (!clusterMap.clusters || clusterMap.clusters.length === 0) &&
    !mapError;
  const hasNoData = mapError && mapError.includes('not found');

  return (
    <main style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <div style={{ padding: '1rem', borderBottom: '1px solid #e0e0e0' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '1rem',
          }}
        >
          <h1 style={{ margin: 0 }}>Insight Miner</h1>
          <LlmHealthStatus />
        </div>
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          <label htmlFor="dataset-select" style={{ fontWeight: 500 }}>
            Dataset:
          </label>
          <select
            id="dataset-select"
            value={dataset?.id || ''}
            onChange={(e) => {
              getDataset({ path: { dataset_id: e.target.value } }).then((res) => {
                if (res.data) {
                  setDataset(res.data);
                }
              });
            }}
            style={{ padding: '0.5rem', borderRadius: 4, border: '1px solid #ccc' }}
          >
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename} ({d.row_count_accepted} items)
              </option>
            ))}
          </select>
        </div>
      </div>

      {dataset && clusterMap && <FilterBar />}

      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {isMapLoading && (
          <div style={{ flex: 1 }}>
            <MapLoadingSkeleton />
          </div>
        )}

        {!isMapLoading && mapError && (
          <div style={{ flex: 1 }}>
            <MapError onRetry={() => {}} error={mapError} />
          </div>
        )}

        {!isMapLoading && !mapError && isNotClustered && <NotClustered />}

        {!isMapLoading && !mapError && hasNoData && <NoClusters />}

        {!isMapLoading &&
          !mapError &&
          filteredClusterMap &&
          filteredClusterMap.clusters &&
          filteredClusterMap.clusters.length > 0 && (
            <>
              <ClusterList clusters={filteredClusterMap.clusters} />
              <ClusterMap
                points={filteredClusterMap.points}
                clusters={filteredClusterMap.clusters}
                dataset={dataset}
              />
              <ClusterDetail
                cluster={
                  selectedClusterId && clusterMap
                    ? clusterMap.clusters.find((c) => c.id === selectedClusterId) || null
                    : null
                }
              />
            </>
          )}
      </div>
    </main>
  );
}
