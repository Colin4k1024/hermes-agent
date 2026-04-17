// ============================================================
// User Types
// ============================================================
export type UserRole = 'admin' | 'power_user' | 'user';
export type UserStatus = 'active' | 'disabled';

export interface User {
  id: string;
  username: string;
  email: string;
  display_name: string;
  role: UserRole;
  status: UserStatus;
  quota_group: string;
  nas_shard: string;
  create_time: string;
  update_time: string;
  feishu_bound: boolean;
}

export interface UserListItem {
  id: string;
  username: string;
  email: string;
  display_name: string;
  role: UserRole;
  status: UserStatus;
  create_time: string;
}

export interface UserListResponse {
  data: UserListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface CreateUserRequest {
  username: string;
  email: string;
  display_name: string;
  role: UserRole;
  quota_group?: string;
}

// ============================================================
// Quota / Usage Types
// ============================================================
export interface DailyUsage {
  date: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  request_count: number;
}

export interface UserUsage {
  user_id: string;
  username: string;
  daily_usage: DailyUsage[];
  total_tokens: number;
  quota_limit: number;
}

export interface DashboardStats {
  total_users: number;
  active_users: number;
  total_tokens_today: number;
  total_tokens_week: number;
  total_requests_today: number;
}

export interface DashboardUsage {
  labels: string[];
  input_tokens: number[];
  output_tokens: number[];
  total_tokens: number[];
  requests: number[];
}

// ============================================================
// API Token Types
// ============================================================
export type TokenStatus = 'active' | 'revoked';

export interface ApiToken {
  id: string;
  user_id: string;
  username: string;
  name: string;
  token_preview: string; // e.g., "hms_xxxx...xxxx"
  last_used_at: string | null;
  expires_at: string | null;
  status: TokenStatus;
  create_time: string;
}

export interface TokenListResponse {
  data: ApiToken[];
  total: number;
}

export interface CreateTokenRequest {
  user_id: string;
  name: string;
  expires_days?: number;
}

// ============================================================
// Common
// ============================================================
export interface ApiResponse<T> {
  data: T;
  message?: string;
}

export interface PageParams {
  page?: number;
  page_size?: number;
}
