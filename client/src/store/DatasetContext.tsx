import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';
import type { ClusterMap, ClusterSummaryResponse, DatasetDetail } from '../api';

export interface DatasetState {
  dataset: DatasetDetail | null;
  setDataset: (dataset: DatasetDetail | null) => void;

  clusterMap: ClusterMap | null;
  setClusterMap: (map: ClusterMap | null) => void;

  selectedClusterId: string | null;
  setSelectedClusterId: (id: string | null) => void;

  clusterSummary: ClusterSummaryResponse | null;
  setClusterSummary: (summary: ClusterSummaryResponse | null) => void;

  sourceFilter: string | null;
  setSourceFilter: (source: string | null) => void;

  dateRangeStart: string | null;
  setDateRangeStart: (date: string | null) => void;

  dateRangeEnd: string | null;
  setDateRangeEnd: (date: string | null) => void;

  isMapLoading: boolean;
  setIsMapLoading: (loading: boolean) => void;

  mapError: string | null;
  setMapError: (error: string | null) => void;

  isSummaryLoading: boolean;
  setIsSummaryLoading: (loading: boolean) => void;

  summaryError: string | null;
  setSummaryError: (error: string | null) => void;
}

const DatasetContext = createContext<DatasetState | undefined>(undefined);

export function DatasetProvider({ children }: { children: ReactNode }) {
  const [dataset, setDataset] = useState<DatasetDetail | null>(null);
  const [clusterMap, setClusterMap] = useState<ClusterMap | null>(null);
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);
  const [clusterSummary, setClusterSummary] = useState<ClusterSummaryResponse | null>(null);
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);
  const [dateRangeStart, setDateRangeStart] = useState<string | null>(null);
  const [dateRangeEnd, setDateRangeEnd] = useState<string | null>(null);
  const [isMapLoading, setIsMapLoading] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);
  const [isSummaryLoading, setIsSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const value = useMemo(
    () => ({
      dataset,
      setDataset,
      clusterMap,
      setClusterMap,
      selectedClusterId,
      setSelectedClusterId,
      clusterSummary,
      setClusterSummary,
      sourceFilter,
      setSourceFilter,
      dateRangeStart,
      setDateRangeStart,
      dateRangeEnd,
      setDateRangeEnd,
      isMapLoading,
      setIsMapLoading,
      mapError,
      setMapError,
      isSummaryLoading,
      setIsSummaryLoading,
      summaryError,
      setSummaryError,
    }),
    [
      dataset,
      clusterMap,
      selectedClusterId,
      clusterSummary,
      sourceFilter,
      dateRangeStart,
      dateRangeEnd,
      isMapLoading,
      mapError,
      isSummaryLoading,
      summaryError,
    ],
  );

  return <DatasetContext.Provider value={value}>{children}</DatasetContext.Provider>;
}

export function useDataset(): DatasetState {
  const ctx = useContext(DatasetContext);
  if (ctx === undefined) {
    throw new Error('useDataset must be used within a DatasetProvider');
  }
  return ctx;
}
