import { useDataset } from '../store/DatasetContext';

export function FilterBar() {
  const {
    dataset,
    sourceFilter,
    setSourceFilter,
    dateRangeStart,
    setDateRangeStart,
    dateRangeEnd,
    setDateRangeEnd,
  } = useDataset();

  if (!dataset) return null;

  const sources = Array.from(
    new Set(
      (dataset.feedback_items ?? [])
        .map((item) => item.source)
        .filter((s): s is string => s !== null && s !== undefined),
    ),
  );

  return (
    <div
      style={{
        display: 'flex',
        gap: '1rem',
        padding: '1rem',
        borderBottom: '1px solid #e0e0e0',
        flexWrap: 'wrap',
        alignItems: 'center',
      }}
    >
      {sources.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <label htmlFor="source-filter" style={{ fontSize: '0.875rem', fontWeight: 500 }}>
            Source:
          </label>
          <select
            id="source-filter"
            value={sourceFilter || ''}
            onChange={(e) => setSourceFilter(e.target.value || null)}
            style={{ padding: '0.25rem 0.5rem', borderRadius: 4, border: '1px solid #ccc' }}
          >
            <option value="">All sources</option>
            {sources.map((source) => (
              <option key={source} value={source}>
                {source}
              </option>
            ))}
          </select>
        </div>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <label htmlFor="date-start" style={{ fontSize: '0.875rem', fontWeight: 500 }}>
          From:
        </label>
        <input
          id="date-start"
          type="date"
          value={dateRangeStart || ''}
          onChange={(e) => setDateRangeStart(e.target.value || null)}
          style={{ padding: '0.25rem 0.5rem', borderRadius: 4, border: '1px solid #ccc' }}
        />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
        <label htmlFor="date-end" style={{ fontSize: '0.875rem', fontWeight: 500 }}>
          To:
        </label>
        <input
          id="date-end"
          type="date"
          value={dateRangeEnd || ''}
          onChange={(e) => setDateRangeEnd(e.target.value || null)}
          style={{ padding: '0.25rem 0.5rem', borderRadius: 4, border: '1px solid #ccc' }}
        />
      </div>

      {(sourceFilter || dateRangeStart || dateRangeEnd) && (
        <button
          onClick={() => {
            setSourceFilter(null);
            setDateRangeStart(null);
            setDateRangeEnd(null);
          }}
          style={{
            padding: '0.25rem 0.75rem',
            borderRadius: 4,
            border: '1px solid #ccc',
            background: '#f5f5f5',
            cursor: 'pointer',
            fontSize: '0.875rem',
          }}
        >
          Clear filters
        </button>
      )}
    </div>
  );
}
