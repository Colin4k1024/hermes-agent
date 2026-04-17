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
  SkillSummary,
  SkillDetail,
  SkillListResponse,
  SkillResponse,
  CreateSkillRequest,
  UpdateSkillRequest,
  AuditLog,
  AuditLogResponse,
  QuotaConfig,
  QuotaUsage,
  QuotaDashboard,
  UpdateQuotaConfigRequest,
} from '../types';

// ============================================================
// Skills Service
// ============================================================

// Simulated network delay
const delay = (ms: number) => new Promise((r) => setTimeout(r, ms));

const mockSkills: SkillSummary[] = [
  { name: 'github', description: 'GitHub workflow automation', version: '1.2.0', status: 'active', tags: ['devops', 'github'], author: 'hermes-team', update_time: '2026-04-10T10:00:00Z' },
  { name: 'jira', description: 'Jira issue management', version: '1.0.3', status: 'active', tags: ['project', 'management'], author: 'hermes-team', update_time: '2026-04-08T14:30:00Z' },
  { name: 'web-search', description: 'Web search and content extraction', version: '2.1.0', status: 'active', tags: ['search', 'web'], author: 'hermes-team', update_time: '2026-04-12T09:15:00Z' },
  { name: 'slack-notify', description: 'Send notifications to Slack channels', version: '1.5.0', status: 'active', tags: ['notification', 'slack'], author: 'community', update_time: '2026-04-05T16:45:00Z' },
  { name: 'data-analysis', description: 'Data analysis and visualization', version: '0.9.0', status: 'active', tags: ['data', 'analysis'], author: 'community', update_time: '2026-04-11T11:20:00Z' },
  { name: 'legacy-report', description: 'Deprecated legacy reporting skill', version: '0.5.0', status: 'archived', tags: ['deprecated'], author: 'hermes-team', update_time: '2026-03-20T08:00:00Z' },
];

export const skillService = {
  async list(params?: { status?: string; keyword?: string }): Promise<SkillListResponse> {
    await delay(400 + Math.random() * 200);
    let filtered = [...mockSkills];
    if (params?.status) filtered = filtered.filter((s) => s.status === params.status);
    if (params?.keyword) {
      const kw = params.keyword.toLowerCase();
      filtered = filtered.filter(
        (s) => s.name.toLowerCase().includes(kw) || s.description.toLowerCase().includes(kw),
      );
    }
    return { data: filtered, total: filtered.length };
  },

  async get(name: string): Promise<SkillDetail> {
    await delay(300 + Math.random() * 200);
    const skill = mockSkills.find((s) => s.name === name);
    if (!skill) throw new Error(`Skill '${name}' not found`);
    return {
      ...skill,
      id: `skill-${name}`,
      nas_path: `/nas/skills/${name}/SKILL.md`,
      published_by: 'admin@corp.example.com',
      related_skills: [],
      license: 'MIT',
      create_time: '2026-03-01T00:00:00Z',
    };
  },

  async create(req: CreateSkillRequest): Promise<SkillResponse> {
    await delay(500);
    const newSkill: SkillSummary = {
      name: req.name,
      description: req.description ?? '',
      version: '1.0.0',
      status: 'active',
      tags: req.tags ?? [],
      author: req.published_by ?? '',
      update_time: new Date().toISOString(),
    };
    mockSkills.push(newSkill);
    return {
      success: true,
      skill: { ...newSkill, id: `skill-${req.name}`, nas_path: `/nas/skills/${req.name}/SKILL.md`, published_by: req.published_by ?? null, related_skills: [], license: '', create_time: new Date().toISOString() },
      message: `Skill '${req.name}' created successfully`,
    };
  },

  async update(name: string, req: UpdateSkillRequest): Promise<SkillResponse> {
    await delay(400);
    const skill = mockSkills.find((s) => s.name === name);
    if (!skill) throw new Error(`Skill '${name}' not found`);
    if (req.description !== undefined) skill.description = req.description;
    if (req.tags !== undefined) skill.tags = req.tags;
    if (req.status !== undefined) skill.status = req.status;
    skill.update_time = new Date().toISOString();
    if (req.skill_md) {
      const versionParts = skill.version.split('.').map(Number);
      versionParts[2] += 1;
      skill.version = versionParts.join('.');
    }
    return {
      success: true,
      skill: { ...skill, id: `skill-${name}`, nas_path: `/nas/skills/${name}/SKILL.md`, published_by: null, related_skills: [], license: '', create_time: '2026-03-01T00:00:00Z' },
      message: `Skill '${name}' updated to version ${skill.version}`,
    };
  },

  async archive(name: string): Promise<void> {
    await delay(300);
    const skill = mockSkills.find((s) => s.name === name);
    if (skill) skill.status = 'archived';
  },
};

// ============================================================
// Audit Log Service
// ============================================================
const AUDIT_ACTIONS = ['login', 'logout', 'api_call', 'llm_request', 'token_create', 'token_revoke'] as const;
const AUDIT_USERS = ['zhang.wei', 'wang.fang', 'li.ming', 'liu.yang', 'chen.jing'];
const AUDIT_IPS = ['10.0.1.15', '10.0.2.31', '10.0.1.88', '10.0.3.5', '10.0.1.42'];

function generateAuditLogs(count: number, offset = 0): AuditLog[] {
  return Array.from({ length: count }, (_, i) => {
    const idx = (offset + i) % 50;
    const action = AUDIT_ACTIONS[idx % AUDIT_ACTIONS.length];
    const user = AUDIT_USERS[idx % AUDIT_USERS.length];
    const daysAgo = Math.floor(idx / 5);
    const hoursAgo = (idx * 3) % 24;
    const timestamp = new Date(2026, 3, 16 - daysAgo, hoursAgo, (idx * 7) % 60, (idx * 13) % 60);
    return {
      id: `audit-${String(idx + 1).padStart(6, '0')}`,
      user_id: `u-${String((idx % 5) + 1).padStart(5, '0')}`,
      username: user,
      action,
      resource: action === 'llm_request' ? '/v1/chat/completions' : action === 'api_call' ? '/api/users' : action === 'login' ? '/auth/login' : `/${action.replace('_', '/')}`,
      detail: action === 'login' ? 'SSO login via Keycloak' : action === 'llm_request' ? `model: claude-3-5-sonnet, tokens: ${1000 + idx * 150}` : `${action} on ${user} at ${timestamp.toISOString()}`,
      ip: AUDIT_IPS[idx % AUDIT_IPS.length],
      timestamp: timestamp.toISOString(),
    };
  });
}

export const auditService = {
  async list(params?: { page?: number; page_size?: number; action?: string; user_id?: string; keyword?: string }): Promise<AuditLogResponse> {
    await delay(400 + Math.random() * 200);
    const page = params?.page ?? 1;
    const page_size = params?.page_size ?? 20;
    const allLogs = generateAuditLogs(50);
    let filtered = [...allLogs];
    if (params?.action) filtered = filtered.filter((l) => l.action === params.action);
    if (params?.user_id) filtered = filtered.filter((l) => l.user_id === params.user_id);
    if (params?.keyword) {
      const kw = params.keyword.toLowerCase();
      filtered = filtered.filter((l) => l.username.includes(kw) || l.detail.toLowerCase().includes(kw));
    }
    const start = (page - 1) * page_size;
    return { data: filtered.slice(start, start + page_size), total: filtered.length, page, page_size };
  },
};

// ============================================================
// Quota Service
// ============================================================
const mockConfigs: QuotaConfig[] = [
  { id: 'cfg-1', quota_group: 'user', daily_token_limit: 100_000, daily_request_limit: 500, model_allowlist: null, create_time: '2026-03-01T00:00:00Z', update_time: '2026-04-01T10:00:00Z' },
  { id: 'cfg-2', quota_group: 'power_user', daily_token_limit: 500_000, daily_request_limit: 2000, model_allowlist: null, create_time: '2026-03-01T00:00:00Z', update_time: '2026-04-01T10:00:00Z' },
  { id: 'cfg-3', quota_group: 'admin', daily_token_limit: -1, daily_request_limit: 9999999, model_allowlist: [], create_time: '2026-03-01T00:00:00Z', update_time: '2026-03-01T00:00:00Z' },
];

export const quotaService = {
  async listConfigs(): Promise<QuotaConfig[]> {
    await delay(300 + Math.random() * 200);
    return [...mockConfigs];
  },

  async updateConfig(quota_group: string, req: UpdateQuotaConfigRequest): Promise<QuotaConfig> {
    await delay(400);
    const config = mockConfigs.find((c) => c.quota_group === quota_group);
    if (!config) throw new Error(`Quota config '${quota_group}' not found`);
    if (req.daily_token_limit !== undefined) config.daily_token_limit = req.daily_token_limit;
    if (req.daily_request_limit !== undefined) config.daily_request_limit = req.daily_request_limit;
    if (req.model_allowlist !== undefined) config.model_allowlist = req.model_allowlist;
    config.update_time = new Date().toISOString();
    return { ...config };
  },

  async dashboard(): Promise<QuotaDashboard> {
    await delay(400 + Math.random() * 200);
    return {
      total_users: 47,
      total_tokens_today: 12_845_320,
      total_requests_today: 3_847,
      users_at_limit: 2,
      top_users: [
        { user_id: 'u-00001', username: 'zhang.wei', role: 'power_user', quota_group: 'power_user', record_date: '2026-04-16', used_tokens: 480_000, used_requests: 1890, daily_limit: 500_000, usage_percentage: 96 },
        { user_id: 'u-00002', username: 'wang.fang', role: 'power_user', quota_group: 'power_user', record_date: '2026-04-16', used_tokens: 465_000, used_requests: 1720, daily_limit: 500_000, usage_percentage: 93 },
        { user_id: 'u-00003', username: 'li.ming', role: 'user', quota_group: 'user', record_date: '2026-04-16', used_tokens: 98_000, used_requests: 490, daily_limit: 100_000, usage_percentage: 98 },
      ],
    };
  },

  async usage(params?: { limit?: number }): Promise<{ data: QuotaUsage[]; total: number }> {
    await delay(400 + Math.random() * 200);
    const NAMES2 = ['zhang.wei', 'wang.fang', 'li.ming', 'liu.yang', 'chen.jing', 'yang.fan', 'zhao.lei', 'zhou.lin'];
    const usage: QuotaUsage[] = Array.from({ length: params?.limit ?? 20 }, (_, i) => {
      const role = i < 5 ? 'power_user' : i === 5 ? 'admin' : 'user';
      const group = role === 'admin' ? 'admin' : role === 'power_user' ? 'power_user' : 'user';
      const limit = group === 'admin' ? -1 : group === 'power_user' ? 500_000 : 100_000;
      const used = Math.floor(limit * (0.3 + Math.random() * 0.7));
      return {
        user_id: `u-${String(i + 1).padStart(5, '0')}`,
        username: NAMES2[i % NAMES2.length],
        role,
        quota_group: group,
        record_date: '2026-04-16',
        used_tokens: used,
        used_requests: Math.floor(used / 300),
        daily_limit: limit,
        usage_percentage: limit === -1 ? 0 : Math.round((used / limit) * 100),
      };
    });
    return { data: usage, total: usage.length };
  },
};

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
