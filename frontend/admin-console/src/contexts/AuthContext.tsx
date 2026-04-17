import { createContext, useContext, useState, useEffect, ReactNode } from 'react';

interface User {
  user_id: string;
  email: string;
  role: string;
}

interface AuthContextType {
  user: User | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

const AUTH_SERVICE_URL = import.meta.env.VITE_AUTH_SERVICE_URL || 'http://localhost:8001';

// Decode JWT to check expiration (base64url decode)
function decodeJWT(token: string): { exp: number; [key: string]: unknown } | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = parts[1];
    // Replace URL-safe chars and add padding
    const decoded = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(decoded);
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // On mount, check localStorage for token
  useEffect(() => {
    const stored = localStorage.getItem('hermes_token');
    const storedUser = localStorage.getItem('hermes_user');
    if (stored && storedUser) {
      // Validate token is not expired
      const payload = decodeJWT(stored);
      if (payload && payload.exp * 1000 > Date.now()) {
        setToken(stored);
        setUser(JSON.parse(storedUser));
      } else {
        // Token expired, clear storage
        localStorage.removeItem('hermes_token');
        localStorage.removeItem('hermes_user');
      }
    }
    setIsLoading(false);
  }, []);

  // Auto-refresh token before expiration
  useEffect(() => {
    if (!token) return;

    const payload = decodeJWT(token);
    if (!payload || !payload.exp) return;

    const expTime = payload.exp * 1000;
    const now = Date.now();
    const timeUntilExpiry = expTime - now;

    // Refresh 5 minutes before expiration
    const refreshBuffer = 5 * 60 * 1000;
    if (timeUntilExpiry <= refreshBuffer) {
      refreshToken().catch(() => {
        logout();
      });
    } else {
      // Schedule refresh
      const timeoutId = setTimeout(() => {
        refreshToken().catch(() => {
          logout();
        });
      }, timeUntilExpiry - refreshBuffer);
      return () => clearTimeout(timeoutId);
    }
  }, [token]);

  const refreshToken = async (): Promise<void> => {
    if (!token) throw new Error('No token to refresh');
    
    const res = await fetch(`${AUTH_SERVICE_URL}/auth/refresh`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
    });
    
    if (!res.ok) {
      throw new Error('Token refresh failed');
    }
    
    const data = await res.json();
    setToken(data.access_token);
    localStorage.setItem('hermes_token', data.access_token);
    if (data.user) {
      setUser(data.user);
      localStorage.setItem('hermes_user', JSON.stringify(data.user));
    }
  };

  const login = async (email: string, password: string) => {
    const res = await fetch(`${AUTH_SERVICE_URL}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Login failed' }));
      throw new Error((err as { detail?: string }).detail || 'Login failed');
    }
    const data = await res.json();
    setToken(data.access_token);
    setUser(data.user);
    localStorage.setItem('hermes_token', data.access_token);
    localStorage.setItem('hermes_user', JSON.stringify(data.user));
  };

  const logout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem('hermes_token');
    localStorage.removeItem('hermes_user');
  };

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

// Export for use in API calls
export { AUTH_SERVICE_URL };
