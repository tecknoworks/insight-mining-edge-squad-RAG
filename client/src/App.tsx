import { DashboardPage } from './pages/DashboardPage';
import { DatasetProvider } from './store/DatasetContext';

export function App() {
  return (
    <DatasetProvider>
      <DashboardPage />
    </DatasetProvider>
  );
}
