import { useParams, useNavigate } from 'react-router-dom';
import { Card, Descriptions, Tag, Spin, Button, Typography, Space, Table, message, Breadcrumb } from 'antd';
import { ArrowLeftOutlined, ReloadOutlined } from '@ant-design/icons';
import { useRequest } from '../../../hooks/useRequest';
import { userService, dashboardService } from '../../../services/api';

const { Title } = Typography;

const roleMap: Record<string, string> = {
  admin: '管理员',
  power_user: '高级用户',
  user: '普通用户',
};

const statusColor: Record<string, string> = {
  active: 'green',
  disabled: 'default',
};

const formatNumber = (n: number) =>
  n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `${(n / 1_000).toFixed(1)}K` : String(n);

export default function UserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const {
    data: user,
    loading: userLoading,
    run: reloadUser,
  } = useRequest(() => (id ? userService.get(id) : Promise.reject()), {
    onError: () => message.error('用户信息加载失败'),
  });

  const { data: usage, loading: usageLoading } = useRequest(
    () => (id ? dashboardService.userUsage(id) : Promise.reject()),
    {
      onError: () => message.error('用量数据加载失败'),
    },
  );

  if (userLoading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: 300 }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!user) {
    return (
      <Card>
        <p style={{ color: '#ff4d4f' }}>用户不存在或已被删除。</p>
        <Button onClick={() => navigate('/users')}>返回用户列表</Button>
      </Card>
    );
  }

  const usageColumns = [
    { title: '日期', dataIndex: 'date', key: 'date', render: (v: string) => v },
    {
      title: 'Input Tokens',
      dataIndex: 'input_tokens',
      key: 'input_tokens',
      align: 'right' as const,
      render: (v: number) => formatNumber(v),
    },
    {
      title: 'Output Tokens',
      dataIndex: 'output_tokens',
      key: 'output_tokens',
      align: 'right' as const,
      render: (v: number) => formatNumber(v),
    },
    {
      title: 'Total',
      dataIndex: 'total_tokens',
      key: 'total_tokens',
      align: 'right' as const,
      render: (v: number) => formatNumber(v),
    },
    {
      title: '请求数',
      dataIndex: 'request_count',
      key: 'request_count',
      align: 'right' as const,
      render: (v: number) => formatNumber(v),
    },
  ];

  return (
    <div>
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { title: <a onClick={() => navigate('/users')}>用户管理</a> },
          { title: user.username },
        ]}
        style={{ marginBottom: 16 }}
      />

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          用户详情 — {user.display_name}
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => reloadUser()}>
            刷新
          </Button>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/users')}>
            返回列表
          </Button>
        </Space>
      </div>

      {/* User Info Card */}
      <Card title="基本信息" style={{ borderRadius: 8, marginBottom: 16 }}>
        <Descriptions column={{ xs: 1, sm: 2 }} size="small">
          <Descriptions.Item label="用户 ID">{user.id}</Descriptions.Item>
          <Descriptions.Item label="用户名">{user.username}</Descriptions.Item>
          <Descriptions.Item label="邮箱">{user.email}</Descriptions.Item>
          <Descriptions.Item label="姓名">{user.display_name}</Descriptions.Item>
          <Descriptions.Item label="角色">
            <Tag color={user.role === 'admin' ? 'red' : user.role === 'power_user' ? 'orange' : 'blue'}>
              {roleMap[user.role] ?? user.role}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag color={statusColor[user.status]}>
              {user.status === 'active' ? '活跃' : '已禁用'}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="配额组">{user.quota_group}</Descriptions.Item>
          <Descriptions.Item label="NAS 分片">{user.nas_shard}</Descriptions.Item>
          <Descriptions.Item label="飞书绑定">
            {user.feishu_bound ? '已绑定' : '未绑定'}
          </Descriptions.Item>
          <Descriptions.Item label="创建时间">
            {new Date(user.create_time).toLocaleString('zh-CN')}
          </Descriptions.Item>
          <Descriptions.Item label="更新时间">
            {new Date(user.update_time).toLocaleString('zh-CN')}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* Usage Card */}
      <Card
        title={`用量记录（配额: ${formatNumber(user.quota_group === 'unlimited' ? 0 : user.quota_group === 'premium' ? 500_000 : 100_000)} tokens/天）`}
        loading={usageLoading}
        style={{ borderRadius: 8 }}
      >
        {usage ? (
          <>
            <Descriptions column={3} size="small" style={{ marginBottom: 16 }}>
              <Descriptions.Item label="14 天总消耗">
                <strong>{formatNumber(usage.total_tokens)}</strong> tokens
              </Descriptions.Item>
              <Descriptions.Item label="日均消耗">
                {formatNumber(Math.round(usage.total_tokens / 14))} tokens
              </Descriptions.Item>
              <Descriptions.Item label="配额余量">
                {user.quota_group === 'unlimited'
                  ? '无限制'
                  : `${Math.max(0, Math.round((usage.quota_limit - usage.total_tokens / 14) * 100))}%`}
              </Descriptions.Item>
            </Descriptions>
            <Table
              columns={usageColumns}
              dataSource={usage.daily_usage}
              rowKey="date"
              size="small"
              pagination={false}
              scroll={{ x: 500 }}
            />
          </>
        ) : (
          <div style={{ textAlign: 'center', padding: 24, color: '#999' }}>暂无用量数据</div>
        )}
      </Card>
    </div>
  );
}
