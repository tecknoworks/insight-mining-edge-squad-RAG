import { DashboardPage } from './pages/DashboardPage';
import { DatasetProvider } from './store/DatasetContext';
import { ChatProvider } from './store/ChatContext';

export function App() {
  return (
    <DatasetProvider>
      <ChatProvider>
        <DashboardPage />
      </ChatProvider>
    </DatasetProvider>
  );
}
