import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FilterBar } from '../FilterBar';
import { DatasetProvider } from '../../store/DatasetContext';
import type { DatasetDetail } from '../../api';

function renderWithProvider(component: React.ReactElement) {
  return render(<DatasetProvider>{component}</DatasetProvider>);
}

describe('FilterBar', () => {
  it('renders null when dataset is not provided', () => {
    const { container } = renderWithProvider(<FilterBar />);

    // FilterBar returns null when dataset is null
    expect(container.firstChild).toBeNull();
  });

  // Full FilterBar testing requires DashboardPage context integration
  // These are tested end-to-end as part of the DashboardPage
});
