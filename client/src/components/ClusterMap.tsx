import { useMemo, useCallback, useRef, useEffect, useState } from 'react';
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  Cell,
} from 'recharts';
import { useDataset } from '../store/DatasetContext';
import type { ClusterAssignmentPoint, ClusterSummary } from '../api';

const MAX_PLOT_POINTS = 5000;

// Categorical palette, colorblind-friendly
const CLUSTER_COLORS = [
  '#1f77b4', // blue
  '#ff7f0e', // orange
  '#2ca02c', // green
  '#d62728', // red
  '#9467bd', // purple
  '#8c564b', // brown
  '#e377c2', // pink
  '#7f7f7f', // gray
  '#bcbd22', // olive
  '#17becf', // cyan
  '#aec7e8', // light blue
  '#ffbb78', // light orange
];

interface ChartPoint {
  x: number;
  y: number;
  feedback_text?: string;
  cluster_id?: string | null;
  is_centroid?: boolean;
  item_count?: number;
}

interface ClusterMapProps {
  points: ClusterAssignmentPoint[];
  clusters: ClusterSummary[];
  dataset: { feedback_items?: Array<{ id: string; feedback_text: string }> } | null;
}

export function ClusterMap({ points, clusters, dataset }: ClusterMapProps) {
  const { setSelectedClusterId } = useDataset();
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerSize, setContainerSize] = useState({ width: 600, height: 400 });

  useEffect(() => {
    const updateSize = () => {
      if (containerRef.current) {
        const { width, height } = containerRef.current.getBoundingClientRect();
        setContainerSize({
          width: Math.max(width - 40, 400),
          height: Math.max(height - 40, 300),
        });
      }
    };

    updateSize();
    window.addEventListener('resize', updateSize);
    return () => window.removeEventListener('resize', updateSize);
  }, []);

  const feedbackMap = useMemo(() => {
    const map = new Map<string, string>();
    dataset?.feedback_items?.forEach((item) => {
      map.set(item.id, item.feedback_text);
    });
    return map;
  }, [dataset]);

  const { chartData, downsampleCount, totalPoints } = useMemo(() => {
    const feedbackPoints: ChartPoint[] = points.map((p) => ({
      x: p.x,
      y: p.y,
      feedback_text: feedbackMap.get(p.feedback_item_id) || '',
      cluster_id: p.cluster_id,
    }));

    let sampled = feedbackPoints;
    let downsampleCount = 0;

    if (feedbackPoints.length > MAX_PLOT_POINTS) {
      downsampleCount = feedbackPoints.length - MAX_PLOT_POINTS;
      const step = Math.ceil(feedbackPoints.length / MAX_PLOT_POINTS);
      sampled = feedbackPoints.filter((_, i) => i % step === 0).slice(0, MAX_PLOT_POINTS);
    }

    // Add centroid bubbles for each cluster
    const centroids: ChartPoint[] = clusters
      .filter((c) => c.id !== null)
      .map((c) => {
        const clusterPoints = feedbackPoints.filter((p) => p.cluster_id === c.id);
        const avgX = clusterPoints.reduce((sum, p) => sum + p.x, 0) / clusterPoints.length;
        const avgY = clusterPoints.reduce((sum, p) => sum + p.y, 0) / clusterPoints.length;

        return {
          x: avgX,
          y: avgY,
          cluster_id: c.id,
          is_centroid: true,
          item_count: c.item_count,
        };
      });

    return {
      chartData: [...sampled, ...centroids],
      downsampleCount,
      totalPoints: feedbackPoints.length,
    };
  }, [points, clusters, feedbackMap]);

  const getColor = useCallback(
    (clusterId: string | null | undefined) => {
      if (clusterId === null || clusterId === undefined) {
        return '#cccccc'; // noise points in muted grey
      }
      const clusterIndex = clusters.findIndex((c) => c.id === clusterId);
      return CLUSTER_COLORS[clusterIndex % CLUSTER_COLORS.length];
    },
    [clusters],
  );

  const handlePointClick = useCallback(
    (data: ChartPoint) => {
      if (data.cluster_id !== null && data.cluster_id !== undefined) {
        setSelectedClusterId(data.cluster_id);
      }
    },
    [setSelectedClusterId],
  );

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }} ref={containerRef}>
      {downsampleCount > 0 && (
        <div
          style={{
            padding: '0.75rem 1rem',
            background: '#fff3cd',
            borderBottom: '1px solid #ffc107',
            fontSize: '0.875rem',
            color: '#856404',
          }}
        >
          Showing {totalPoints - downsampleCount} of {totalPoints} points
        </div>
      )}

      <div style={{ flex: 1, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
        <ScatterChart
          width={containerSize.width}
          height={containerSize.height}
          margin={{ top: 20, right: 20, bottom: 20, left: 20 }}
        >
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="x" type="number" name="X" unit="" />
          <YAxis dataKey="y" type="number" name="Y" />
          <Tooltip
            cursor={{ strokeDasharray: '3 3' }}
            content={({ active, payload }) => {
              if (active && payload && payload[0]) {
                const data = payload[0].payload as ChartPoint;
                if (data.is_centroid) {
                  return (
                    <div
                      style={{
                        background: 'white',
                        padding: '0.5rem',
                        border: '1px solid #ccc',
                        borderRadius: 4,
                      }}
                    >
                      <p style={{ margin: 0, fontWeight: 500 }}>
                        {clusters.find((c) => c.id === data.cluster_id)?.label || `Cluster`}
                      </p>
                      <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.875rem', color: '#666' }}>
                        {data.item_count} items
                      </p>
                    </div>
                  );
                }
                return (
                  <div
                    style={{
                      background: 'white',
                      padding: '0.5rem',
                      border: '1px solid #ccc',
                      borderRadius: 4,
                    }}
                  >
                    <p style={{ margin: 0, fontWeight: 500 }}>
                      {clusters.find((c) => c.id === data.cluster_id)?.label || 'Unclustered'}
                    </p>
                    <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.875rem', color: '#666' }}>
                      {data.feedback_text?.substring(0, 60)}...
                    </p>
                  </div>
                );
              }
              return null;
            }}
          />
          <Legend />
          <Scatter
            name="Feedback items"
            data={chartData.filter((d) => !d.is_centroid)}
            fill="#8884d8"
          >
            {chartData
              .filter((d) => !d.is_centroid)
              .map((entry, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={getColor(entry.cluster_id)}
                  onClick={() => handlePointClick(entry)}
                  style={{ cursor: 'pointer' }}
                />
              ))}
          </Scatter>
          <Scatter
            name="Cluster centroids"
            data={chartData.filter((d) => d.is_centroid)}
            fill="transparent"
            shape={(props: unknown) => {
              const { cx, cy, payload } = props as { cx: number; cy: number; payload?: ChartPoint };
              const data = payload as ChartPoint;
              if (!data) {
                return <circle cx={cx} cy={cy} r={0} />;
              }
              const size = Math.sqrt(data.item_count || 10) * 3;
              return (
                <circle
                  cx={cx}
                  cy={cy}
                  r={size}
                  fill={getColor(data.cluster_id)}
                  opacity={0.3}
                  stroke={getColor(data.cluster_id)}
                  strokeWidth={2}
                  onClick={() => handlePointClick(data)}
                  style={{ cursor: 'pointer' } as React.CSSProperties}
                />
              );
            }}
          />
        </ScatterChart>
      </div>
    </div>
  );
}
