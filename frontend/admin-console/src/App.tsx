import { Routes, Route, Navigate } from 'react-router-dom';
import AppLayout from './components/Layout/AppLayout';
import UserListPage from './pages/user/ListPage';
import UserDetailPage from './pages/user/detail/DetailPage';
import DashboardPage from './pages/dashboard/DashboardPage';
import TokenPage from './pages/token/TokenPage';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<AppLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="users" element={<UserListPage />} />
        <Route path="users/:id" element={<UserDetailPage />} />
        <Route path="tokens" element={<TokenPage />} />
      </Route>
    </Routes>
  );
}
