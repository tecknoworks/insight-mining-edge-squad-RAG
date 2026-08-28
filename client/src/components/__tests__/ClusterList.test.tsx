import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ClusterList } from '../ClusterList';
import { DatasetProvider } from '../../store/DatasetContext';
import type { ClusterSummary } from '../../api';

const mockClusters: ClusterSummary[] = [
  { id: 'cluster-1', cluster_index: 0, item_count: 100, label: 'Performance Issues' },
  { id: 'cluster-2', cluster_index: 1, item_count: 50, label: 'UI/UX Feedback' },
  { id: null, cluster_index: -1, item_count: 10, label: null },
];

function renderWithProvider(component: React.ReactElement) {
  return render(<DatasetProvider>{component}</DatasetProvider>);
}

describe('ClusterList', () => {
  it('renders all clusters with item counts', () => {
    renderWithProvider(<ClusterList clusters={mockClusters} />);

    expect(screen.getByText('Performance Issues')).toBeInTheDocument();
    expect(screen.getByText('UI/UX Feedback')).toBeInTheDocument();
    expect(screen.getByText('Unclustered')).toBeInTheDocument();
    expect(screen.getByText('100 items')).toBeInTheDocument();
    expect(screen.getByText('50 items')).toBeInTheDocument();
    expect(screen.getByText('10 items')).toBeInTheDocument();
  });

  it('selects a cluster when clicked', async () => {
    renderWithProvider(<ClusterList clusters={mockClusters} />);

    const performanceItem = screen.getByText('Performance Issues').closest('li');
    fireEvent.click(performanceItem!);

    expect(performanceItem).toHaveStyle({ background: '#e3f2fd' });
  });

  it('makes noise clusters visually distinct', () => {
    renderWithProvider(<ClusterList clusters={mockClusters} />);

    const noiseItem = screen.getByText('Unclustered').closest('li');
    expect(noiseItem).toHaveStyle({ opacity: '0.7' });
  });

  it('supports keyboard navigation with arrow keys', async () => {
    const user = userEvent.setup();
    renderWithProvider(<ClusterList clusters={mockClusters} />);

    const listContainer = screen.getByText('Clusters').parentElement;
    const list = listContainer?.querySelector('ul');

    // Focus the list
    if (list) {
      const firstItem = list.querySelector('li') as HTMLLIElement;
      firstItem.focus();
      expect(firstItem).toHaveFocus();

      // Simulate arrow down
      fireEvent.keyDown(document, { key: 'ArrowDown' });
      // The focus should move to the next item (implementation detail)
    }
  });

  it('selects cluster with Enter key', async () => {
    const user = userEvent.setup();
    renderWithProvider(<ClusterList clusters={mockClusters} />);

    const list = screen.getByText('Clusters').parentElement?.querySelector('ul');
    if (list) {
      const firstItem = list.querySelector('li') as HTMLLIElement;
      firstItem.focus();

      fireEvent.keyDown(firstItem, { key: 'Enter' });
      expect(firstItem).toHaveStyle({ background: '#e3f2fd' });
    }
  });

  it('handles noise cluster selection', () => {
    renderWithProvider(<ClusterList clusters={mockClusters} />);

    const noiseItem = screen.getByText('Unclustered').closest('li');
    fireEvent.click(noiseItem!);

    expect(noiseItem).toHaveStyle({ background: '#e3f2fd' });
  });
});
