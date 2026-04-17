import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Spin } from 'antd';

export function ProtectedRoute() {
  const { user, isLoading } = useAuth();

  if (isLoading) return <Spin fullscreen />;
  if (!user) return <Navigate to="/login" replace />;

  return <Outlet />;
}
