import type {
  User,
  UserListItem,
  UserListResponse,
  CreateUserRequest,
  UserUsage,
  DashboardStats,
  DashboardUsage,
  ApiToken,
  TokenListResponse,
  CreateTokenRequest,
} from '../types';

// Simulated network delay
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ============================================================
// Mock Data Generators
// ============================================================
const NAMES = [
  '张伟', '王芳', '李明', '刘洋', '陈静', '杨帆', '赵雷', '周琳',
  '吴昊', '郑鹏', '孙丽', '马超', '朱婷', '胡磊', '林峰', '何雪',
  '高健', '罗燕', '郭强', '梁慧',
];
const DOMAINS = ['corp.example.com', 'internal.example.com'];

let mockUsers: UserListItem[] = Array.from({ length: 47 }, (_, i) => ({
  id: `u-${String(i + 1).padStart(5, '0')}`,
  username: `user${i + 1}`,
  email: `user${i + 1}@${DOMAINS[i % DOMAINS.length]}`,
  display_name: NAMES[i % NAMES.length] + (i >= NAMES.length ? ` ${Math.floor(i / NAMES.length) + 1}` : ''),
  role: i === 0 ? 'admin' : i < 5 ? 'power_user' : 'user',
  status: i < 43 ? 'active' : 'disabled',
  create_time: new Date(2026, 3, 1 + (i % 15)).toISOString(),
}));

const mockTokenNames = ['生产密钥', '测试密钥', 'CI/CD 密钥', '本地开发', '飞书集成'];

let mockTokens: ApiToken[] = mockUsers
  .filter((u) => u.role !== 'user')
  .map((u, i) => ({
    id: `tok-${String(i + 1).padStart(5, '0')}`,
    user_id: u.id,
    username: u.username,
    name: mockTokenNames[i % mockTokenNames.length],
    token_preview: `hms_${'x'.repeat(8)}...${'y'.repeat(4)}`,
    last_used_at: i % 3 === 0 ? new Date(2026, 3, 15, 10 + i).toISOString() : null,
    expires_at: i % 5 === 0 ? new Date(2026, 6, 15).toISOString() : null,
    status: i < mockUsers.filter((u) => u.role !== 'user').length - 2 ? 'active' : 'revoked',
    create_time: u.create_time,
  }));

// Generate last 14 days of usage data
const generateDailyUsage = (baseTokens: number) =>
  Array.from({ length: 14 }, (_, i) => {
    const factor = 0.5 + Math.random();
    const total = Math.floor(baseTokens * factor);
    return {
      date: new Date(2026, 3, 2 + i).toISOString().split('T')[0],
      input_tokens: Math.floor(total * 0.6),
      output_tokens: Math.floor(total * 0.4),
      total_tokens: total,
      request_count: Math.floor(10 + Math.random() * 40),
    };
  });

// ============================================================
// User Service
// ============================================================
export const userService = {
  async list(params: {
    page?: number;
    page_size?: number;
    status?: string;
    role?: string;
    keyword?: string;
  }): Promise<UserListResponse> {
    await delay(400 + Math.random() * 200);

    let filtered = [...mockUsers];

    if (params.keyword) {
      const kw = params.keyword.toLowerCase();
      filtered = filtered.filter(
        (u) =>
          u.username.toLowerCase().includes(kw) ||
          u.email.toLowerCase().includes(kw) ||
          u.display_name.includes(params.keyword!),
      );
    }
    if (params.status) filtered = filtered.filter((u) => u.status === params.status);
    if (params.role) filtered = filtered.filter((u) => u.role === params.role);

    const page = params.page ?? 1;
    const page_size = params.page_size ?? 10;
    const start = (page - 1) * page_size;
    const data = filtered.slice(start, start + page_size);

    return { data, total: filtered.length, page, page_size };
  },

  async get(id: string): Promise<User> {
    await delay(300 + Math.random() * 200);

    const item = mockUsers.find((u) => u.id === id);
    if (!item) throw new Error(`User ${id} not found`);

    return {
      ...item,
      quota_group: item.role === 'admin' ? 'unlimited' : item.role === 'power_user' ? 'premium' : 'default',
      nas_shard: item.id.slice(-2),
      update_time: item.create_time,
      feishu_bound: Math.random() > 0.2,
    };
  },

  async create(req: CreateUserRequest): Promise<User> {
    await delay(500);
    const newUser: UserListItem = {
      id: `u-${String(mockUsers.length + 1).padStart(5, '0')}`,
      username: req.username,
      email: req.email,
      display_name: req.display_name,
      role: req.role,
      status: 'active',
      create_time: new Date().toISOString(),
    };
    mockUsers = [newUser, ...mockUsers];
    return { ...newUser, quota_group: 'default', nas_shard: newUser.id.slice(-2), update_time: newUser.create_time, feishu_bound: false };
  },

  async updateStatus(id: string, status: 'active' | 'disabled'): Promise<void> {
    await delay(300);
    const user = mockUsers.find((u) => u.id === id);
    if (user) user.status = status;
  },

  async updateRole(id: string, role: string): Promise<void> {
    await delay(300);
    const user = mockUsers.find((u) => u.id === id);
    if (user) user.role = role as typeof user.role;
  },
};

// ============================================================
// Dashboard Service
// ============================================================
export const dashboardService = {
  async stats(): Promise<DashboardStats> {
    await delay(300);
    return {
      total_users: 47,
      active_users: 43,
      total_tokens_today: 12_845_320,
      total_tokens_week: 87_234_560,
      total_requests_today: 3_847,
    };
  },

  async usage(_days = 14): Promise<DashboardUsage> {
    await delay(400 + Math.random() * 300);
    const labels: string[] = [];
    const input_tokens: number[] = [];
    const output_tokens: number[] = [];
    const total_tokens: number[] = [];
    const requests: number[] = [];

    for (let i = 13; i >= 0; i--) {
      const d = new Date(2026, 3, 2 + i);
      labels.push(`${d.getMonth() + 1}/${d.getDate()}`);
      const base = 5_000_000 + Math.random() * 5_000_000;
      const inp = Math.floor(base * 0.6);
      const out = Math.floor(base * 0.4);
      input_tokens.push(inp);
      output_tokens.push(out);
      total_tokens.push(inp + out);
      requests.push(Math.floor(1500 + Math.random() * 2000));
    }
    return { labels, input_tokens, output_tokens, total_tokens, requests };
  },

  async userUsage(userId: string): Promise<UserUsage> {
    await delay(400);
    const user = mockUsers.find((u) => u.id === userId);
    const baseTokens = user?.role === 'power_user' ? 80_000 : user?.role === 'admin' ? 0 : 40_000;
    return {
      user_id: userId,
      username: user?.username ?? userId,
      daily_usage: generateDailyUsage(baseTokens),
      total_tokens: baseTokens * 14,
      quota_limit: baseTokens,
    };
  },
};

// ============================================================
// Token Service
// ============================================================
export const tokenService = {
  async list(params?: { user_id?: string; status?: string }): Promise<TokenListResponse> {
    await delay(400);
    let filtered = [...mockTokens];
    if (params?.user_id) filtered = filtered.filter((t) => t.user_id === params.user_id);
    if (params?.status) filtered = filtered.filter((t) => t.status === params.status);
    return { data: filtered, total: filtered.length };
  },

  async create(req: CreateTokenRequest): Promise<ApiToken> {
    await delay(500);
    const user = mockUsers.find((u) => u.id === req.user_id);
    const newToken: ApiToken = {
      id: `tok-${String(mockTokens.length + 1).padStart(5, '0')}`,
      user_id: req.user_id,
      username: user?.username ?? req.user_id,
      name: req.name,
      token_preview: `hms_${Math.random().toString(36).slice(2, 10)}...${Math.random().toString(36).slice(2, 6)}`,
      last_used_at: null,
      expires_at: req.expires_days
        ? new Date(Date.now() + req.expires_days * 86400 * 1000).toISOString()
        : null,
      status: 'active',
      create_time: new Date().toISOString(),
    };
    mockTokens = [newToken, ...mockTokens];
    return newToken;
  },

  async revoke(id: string): Promise<void> {
    await delay(300);
    const token = mockTokens.find((t) => t.id === id);
    if (token) token.status = 'revoked';
  },
};
