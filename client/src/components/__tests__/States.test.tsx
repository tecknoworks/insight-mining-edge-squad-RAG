import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { NoDatasets, NotClustered, NoClusters } from '../EmptyStates';
import { MapError, DetailError } from '../ErrorStates';
import { MapLoadingSkeleton, DetailLoadingSkeleton, ListLoadingSkeleton } from '../LoadingStates';

describe('Empty States', () => {
  it('renders NoDatasets state', () => {
    render(<NoDatasets />);

    expect(screen.getByText('No datasets yet')).toBeInTheDocument();
    expect(
      screen.getByText('Upload a CSV to get started. Your feedback data will appear here.'),
    ).toBeInTheDocument();
  });

  it('renders NotClustered state', () => {
    render(<NotClustered />);

    expect(screen.getByText('No clusters yet')).toBeInTheDocument();
    expect(
      screen.getByText(/This dataset has been ingested but not yet clustered/),
    ).toBeInTheDocument();
    expect(screen.getByText('Start clustering')).toBeInTheDocument();
  });

  it('renders NoClusters state', () => {
    render(<NoClusters />);

    expect(screen.getByText('No clusters found')).toBeInTheDocument();
    expect(
      screen.getByText(
        /The clustering run completed but found no clusters. Try adjusting the clustering parameters/,
      ),
    ).toBeInTheDocument();
  });
});

describe('Error States', () => {
  it('renders MapError with retry button', () => {
    const mockRetry = vi.fn();
    render(<MapError onRetry={mockRetry} error="Network error" />);

    expect(screen.getByText('Failed to load cluster map')).toBeInTheDocument();
    expect(screen.getByText('Could not fetch cluster data. Please try again.')).toBeInTheDocument();
    expect(screen.getByText('Network error')).toBeInTheDocument();
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });

  it('renders DetailError with retry button', () => {
    const mockRetry = vi.fn();
    render(<DetailError onRetry={mockRetry} error="API error" />);

    expect(screen.getByText('Failed to load cluster details')).toBeInTheDocument();
    expect(screen.getByText('API error')).toBeInTheDocument();
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });

  it('handles missing error message gracefully', () => {
    const mockRetry = vi.fn();
    render(<MapError onRetry={mockRetry} />);

    expect(screen.getByText('Failed to load cluster map')).toBeInTheDocument();
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });
});

describe('Loading States', () => {
  it('renders MapLoadingSkeleton', () => {
    render(<MapLoadingSkeleton />);

    expect(screen.getByText('Loading cluster map…')).toBeInTheDocument();
  });

  it('renders DetailLoadingSkeleton', () => {
    render(<DetailLoadingSkeleton />);

    expect(screen.getByText('Loading cluster details…')).toBeInTheDocument();
  });

  it('renders ListLoadingSkeleton', () => {
    const { container } = render(<ListLoadingSkeleton />);

    // ListLoadingSkeleton renders skeleton divs without text
    const skeletonDivs = container.querySelectorAll('div[style*="background"]');
    expect(skeletonDivs.length).toBeGreaterThan(0);
  });
});
