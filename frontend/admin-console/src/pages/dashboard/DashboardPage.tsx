import { Card, Row, Col, Statistic, Spin, Descriptions, Typography } from 'antd';
import { UserOutlined, RiseOutlined, MessageOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { useRequest } from '../../hooks/useRequest';
import { dashboardService } from '../../services/api';

const { Title } = Typography;

const formatNumber = (n: number) =>
  n >= 1_000_000
    ? `${(n / 1_000_000).toFixed(1)}M`
    : n >= 1_000
    ? `${(n / 1_000).toFixed(1)}K`
    : String(n);

function StatCard({
  title,
  value,
  icon,
  suffix,
  loading,
}: {
  title: string;
  value: number;
  icon: React.ReactNode;
  suffix?: string;
  loading?: boolean;
}) {
  return (
    <Card loading={loading} style={{ borderRadius: 8 }}>
      <Statistic
        title={title}
        value={value}
        suffix={suffix}
        prefix={icon}
        formatter={(v) => (typeof v === 'number' ? formatNumber(v) : v)}
      />
    </Card>
  );
}

export default function DashboardPage() {
  const { data: stats, loading: statsLoading } = useRequest(dashboardService.stats);
  const { data: usage, loading: usageLoading } = useRequest(() => dashboardService.usage(14));

  if (statsLoading || usageLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 300 }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!stats || !usage) {
    return (
      <Card>
        <p style={{ color: '#ff4d4f' }}>数据加载失败，请刷新页面重试。</p>
      </Card>
    );
  }

  const maxTokens = Math.max(...usage.total_tokens);

  return (
    <div>
      <Title level={4} style={{ marginBottom: 24 }}>
        用量看板
      </Title>

      {/* Stat Cards */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title="总用户数"
            value={stats.total_users}
            icon={<UserOutlined />}
            loading={statsLoading}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title="活跃用户"
            value={stats.active_users}
            icon={<ThunderboltOutlined />}
            loading={statsLoading}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title="今日 Token 消耗"
            value={stats.total_tokens_today}
            icon={<RiseOutlined />}
            suffix="tokens"
            loading={statsLoading}
          />
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <StatCard
            title="今日请求数"
            value={stats.total_requests_today}
            icon={<MessageOutlined />}
            loading={statsLoading}
          />
        </Col>
      </Row>

      {/* Chart */}
      <Card title="近 14 天 Token 消耗趋势" style={{ borderRadius: 8 }}>
        <div style={{ fontFamily: 'monospace', fontSize: 12, overflowX: 'auto' }}>
          <div style={{ marginBottom: 4, color: '#888' }}>
            Max: {formatNumber(maxTokens)} tokens
          </div>
          {usage.labels.map((label, i) => {
            const totalH = Math.max(10, Math.round((usage.total_tokens[i] / maxTokens) * 20));
            const inpH = Math.round((usage.input_tokens[i] / maxTokens) * 20);
            const outH = totalH - inpH;
            return (
              <div
                key={label}
                style={{ display: 'flex', alignItems: 'flex-end', gap: 4, marginBottom: 2 }}
              >
                <span style={{ width: 40, color: '#666', fontSize: 11 }}>{label}</span>
                <span style={{ color: '#1677ff' }}>{'█'.repeat(inpH)}</span>
                <span style={{ color: '#52c41a' }}>{'█'.repeat(Math.max(0, outH))}</span>
                <span style={{ color: '#888', marginLeft: 4 }}>
                  {formatNumber(usage.total_tokens[i])}
                </span>
              </div>
            );
          })}
          <div style={{ marginTop: 8, display: 'flex', gap: 16, color: '#666', fontSize: 11 }}>
            <span>
              <span style={{ color: '#1677ff' }}>█</span> Input tokens
            </span>
            <span>
              <span style={{ color: '#52c41a' }}>█</span> Output tokens
            </span>
          </div>
        </div>

        {/* Data table below chart */}
        <div style={{ marginTop: 16, overflowX: 'auto' }}>
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 13,
            }}
          >
            <thead>
              <tr style={{ borderBottom: '2px solid #f0f0f0', color: '#666' }}>
                <th style={{ textAlign: 'left', padding: '8px 12px' }}>日期</th>
                <th style={{ textAlign: 'right', padding: '8px 12px' }}>Input</th>
                <th style={{ textAlign: 'right', padding: '8px 12px' }}>Output</th>
                <th style={{ textAlign: 'right', padding: '8px 12px' }}>Total</th>
                <th style={{ textAlign: 'right', padding: '8px 12px' }}>请求数</th>
              </tr>
            </thead>
            <tbody>
              {[...usage.labels].reverse().map((_label, i) => {
                const ri = usage.labels.length - 1 - i;
                return (
                  <tr key={ri} style={{ borderBottom: '1px solid #f5f5f5' }}>
                    <td style={{ padding: '6px 12px' }}>{usage.labels[ri]}</td>
                    <td style={{ textAlign: 'right', padding: '6px 12px' }}>
                      {formatNumber(usage.input_tokens[ri])}
                    </td>
                    <td style={{ textAlign: 'right', padding: '6px 12px' }}>
                      {formatNumber(usage.output_tokens[ri])}
                    </td>
                    <td style={{ textAlign: 'right', padding: '6px 12px' }}>
                      {formatNumber(usage.total_tokens[ri])}
                    </td>
                    <td style={{ textAlign: 'right', padding: '6px 12px' }}>
                      {formatNumber(usage.requests[ri])}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {/* System Info */}
      <Card title="系统信息" style={{ borderRadius: 8, marginTop: 16 }}>
        <Descriptions column={{ xs: 1, sm: 2 }} size="small">
          <Descriptions.Item label="NAS 存储">
            已挂载 (256-shard NFS v4)
          </Descriptions.Item>
          <Descriptions.Item label="Agent Pod Pool">600 (HPA 400–800)</Descriptions.Item>
          <Descriptions.Item label="LLM 代理">LiteLLM Proxy × 3</Descriptions.Item>
          <Descriptions.Item label="Redis 路由表">
            {stats.active_users} 活跃路由
          </Descriptions.Item>
        </Descriptions>
      </Card>
    </div>
  );
}
