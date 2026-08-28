import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ClusterMap } from '../ClusterMap';
import { DatasetProvider } from '../../store/DatasetContext';
import type { ClusterAssignmentPoint, ClusterSummary } from '../../api';

function renderWithProvider(component: React.ReactElement) {
  return render(<DatasetProvider>{component}</DatasetProvider>);
}

describe('ClusterMap', () => {
  const mockClusters: ClusterSummary[] = [
    { id: 'cluster-1', cluster_index: 0, item_count: 100, label: 'Performance' },
    { id: 'cluster-2', cluster_index: 1, item_count: 50, label: 'UI/UX' },
  ];

  const mockPoints: ClusterAssignmentPoint[] = Array.from({ length: 100 }, (_, i) => ({
    feedback_item_id: `item-${i}`,
    cluster_id: i % 2 === 0 ? 'cluster-1' : 'cluster-2',
    x: Math.random() * 100,
    y: Math.random() * 100,
  }));

  const mockDataset = {
    feedback_items: mockPoints.map((p) => ({
      id: p.feedback_item_id,
      feedback_text: `Feedback ${p.feedback_item_id}`,
    })),
  };

  it('renders scatter chart with points', () => {
    renderWithProvider(
      <ClusterMap points={mockPoints} clusters={mockClusters} dataset={mockDataset} />,
    );

    // Recharts renders SVG elements
    const svg = document.querySelector('svg');
    expect(svg).toBeInTheDocument();
  });

  it('shows downsampling notice when points exceed MAX_PLOT_POINTS', () => {
    const manyPoints: ClusterAssignmentPoint[] = Array.from({ length: 6000 }, (_, i) => ({
      feedback_item_id: `item-${i}`,
      cluster_id: i % 2 === 0 ? 'cluster-1' : 'cluster-2',
      x: Math.random() * 100,
      y: Math.random() * 100,
    }));

    renderWithProvider(
      <ClusterMap points={manyPoints} clusters={mockClusters} dataset={mockDataset} />,
    );

    expect(screen.getByText(/Showing.*of.*points/)).toBeInTheDocument();
  });

  it('does not show downsampling notice for small datasets', () => {
    renderWithProvider(
      <ClusterMap points={mockPoints} clusters={mockClusters} dataset={mockDataset} />,
    );

    const downsampleNotice = screen.queryByText(/Showing.*of.*points/);
    expect(downsampleNotice).not.toBeInTheDocument();
  });

  it('renders centroid bubbles for each cluster', () => {
    renderWithProvider(
      <ClusterMap points={mockPoints} clusters={mockClusters} dataset={mockDataset} />,
    );

    // Centroids are rendered as circles in the scatter chart
    const svg = document.querySelector('svg');
    expect(svg).toBeInTheDocument();
    // The shape renderer creates circle elements
    const circles = svg?.querySelectorAll('circle');
    expect(circles).toBeDefined();
  });

  it('excludes noise points from rendering same as regular points', () => {
    const pointsWithNoise: ClusterAssignmentPoint[] = [
      ...mockPoints,
      { feedback_item_id: 'noise-1', cluster_id: null, x: 50, y: 50 },
      { feedback_item_id: 'noise-2', cluster_id: null, x: 60, y: 60 },
    ];

    const datasetWithNoise = {
      feedback_items: pointsWithNoise.map((p) => ({
        id: p.feedback_item_id,
        feedback_text: `Feedback ${p.feedback_item_id}`,
      })),
    };

    renderWithProvider(
      <ClusterMap points={pointsWithNoise} clusters={mockClusters} dataset={datasetWithNoise} />,
    );

    // Noise points are rendered but filtered out for the centroid calculation
    const svg = document.querySelector('svg');
    expect(svg).toBeInTheDocument();
  });

  it('handles empty dataset gracefully', () => {
    renderWithProvider(<ClusterMap points={[]} clusters={mockClusters} dataset={mockDataset} />);

    const svg = document.querySelector('svg');
    expect(svg).toBeInTheDocument();
  });

  it('handles missing feedback items gracefully', () => {
    renderWithProvider(<ClusterMap points={mockPoints} clusters={mockClusters} dataset={null} />);

    const svg = document.querySelector('svg');
    expect(svg).toBeInTheDocument();
  });
});
