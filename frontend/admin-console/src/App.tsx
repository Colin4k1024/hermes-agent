import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { ProtectedRoute } from './components/ProtectedRoute';
import AppLayout from './components/Layout/AppLayout';
import UserListPage from './pages/user/ListPage';
import UserDetailPage from './pages/user/detail/DetailPage';
import DashboardPage from './pages/dashboard/DashboardPage';
import TokenPage from './pages/token/TokenPage';
import SkillsPage from './pages/skills/SkillsPage';
import AuditPage from './pages/audit/AuditPage';
import QuotaConfigPage from './pages/quota/QuotaConfigPage';
import LoginPage from './pages/login/LoginPage';

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<AppLayout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="users" element={<UserListPage />} />
          <Route path="users/:id" element={<UserDetailPage />} />
          <Route path="tokens" element={<TokenPage />} />
          <Route path="skills" element={<SkillsPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="quota" element={<QuotaConfigPage />} />
        </Route>
      </Route>
    </Routes>
  );
}

function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}

export default App;
