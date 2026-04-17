import { useState } from 'react';
import { Table, Button, Input, Space, Tag, Typography, Card, Tabs, Progress, Modal, Form, InputNumber, message } from 'antd';
import { ReloadOutlined, EditOutlined, SaveOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useRequest } from '../../hooks/useRequest';
import { quotaService } from '../../services/api';
import type { QuotaConfig, QuotaUsage, UpdateQuotaConfigRequest } from '../../types';

const { Title, Text } = Typography;

const roleTagColor: Record<string, string> = {
  admin: 'red',
  power_user: 'orange',
  user: 'blue',
};

const GROUP_LABELS: Record<string, string> = {
  user: '普通用户',
  power_user: '高级用户',
  admin: '管理员',
};

function formatTokens(n: number): string {
  if (n < 0) return '无限制';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

export default function QuotaConfigPage() {
  const [tab, setTab] = useState('configs');
  const [editConfig, setEditConfig] = useState<QuotaConfig | null>(null);
  const [form] = Form.useForm();

  const { data: configs, loading: configsLoading, run: reloadConfigs } = useRequest(quotaService.listConfigs, {
    onError: () => message.error('配额配置加载失败'),
  });

  const { data: dashboard, loading: _, run: reloadDashboard } = useRequest(quotaService.dashboard, {
    onError: () => message.error('仪表盘加载失败'),
  });

  const { data: usageData, loading: usageLoading, run: reloadUsage } = useRequest(
    () => quotaService.usage({ limit: 20 }),
    { onError: () => message.error('用量数据加载失败') },
  );

  const handleEdit = (config: QuotaConfig) => {
    setEditConfig(config);
    form.setFieldsValue({
      daily_token_limit: config.daily_token_limit,
      daily_request_limit: config.daily_request_limit,
      model_allowlist: config.model_allowlist?.join(', ') ?? '',
    });
  };

  const handleSave = async () => {
    if (!editConfig) return;
    try {
      const values = await form.validateFields();
      const req: UpdateQuotaConfigRequest = {
        daily_token_limit: values.daily_token_limit,
        daily_request_limit: values.daily_request_limit,
        model_allowlist: values.model_allowlist ? values.model_allowlist.split(',').map((t: string) => t.trim()).filter(Boolean) : null,
      };
      await quotaService.updateConfig(editConfig.quota_group, req);
      message.success(`配额配置已更新`);
      setEditConfig(null);
      reloadConfigs();
    } catch {
      message.error('保存失败');
    }
  };

  const configColumns: ColumnsType<QuotaConfig> = [
    {
      title: '角色组',
      dataIndex: 'quota_group',
      key: 'quota_group',
      render: (g: string) => (
        <Tag color={roleTagColor[g]} style={{ fontSize: 13, padding: '2px 8px' }}>
          {GROUP_LABELS[g] ?? g}
        </Tag>
      ),
    },
    {
      title: '每日 Token 上限',
      dataIndex: 'daily_token_limit',
      key: 'daily_token_limit',
      render: (v: number) => (
        <Text style={{ fontFamily: 'monospace' }}>{v < 0 ? '无限制' : formatTokens(v)}</Text>
      ),
    },
    {
      title: '每日请求上限',
      dataIndex: 'daily_request_limit',
      key: 'daily_request_limit',
      render: (v: number) => (
        <Text style={{ fontFamily: 'monospace' }}>{v >= 9999999 ? '无限制' : formatTokens(v)}</Text>
      ),
    },
    {
      title: '模型白名单',
      dataIndex: 'model_allowlist',
      key: 'model_allowlist',
      render: (v: string[] | null) => (
        v === null || v.length === 0
          ? <Tag>全部模型</Tag>
          : v.slice(0, 3).map((m) => <Tag key={m}>{m}</Tag>)
      ),
    },
    {
      title: '更新时间',
      dataIndex: 'update_time',
      key: 'update_time',
      render: (t: string) => new Date(t).toLocaleDateString('zh-CN'),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_, record) =>
        record.quota_group !== 'admin' && (
          <Button type="text" size="small" icon={<EditOutlined />} onClick={() => handleEdit(record)}>
            编辑
          </Button>
        ),
    },
  ];

  const usageColumns: ColumnsType<QuotaUsage> = [
    {
      title: '用户',
      dataIndex: 'username',
      key: 'username',
      render: (u: string | null, r) => (
        <Space direction="vertical" size={0}>
          <Text code style={{ fontSize: 12 }}>{u ?? r.user_id}</Text>
          <Tag color={roleTagColor[r.role]} style={{ fontSize: 10 }}>{GROUP_LABELS[r.role] ?? r.role}</Tag>
        </Space>
      ),
    },
    {
      title: '今日用量',
      key: 'used',
      render: (_, r) => {
        if (r.daily_limit < 0) return <Text type="secondary">无限制</Text>;
        const pct = Math.min(100, r.usage_percentage);
        return (
          <Space direction="vertical" size={2} style={{ width: 120 }}>
            <Progress percent={pct} size="small" status={pct >= 90 ? 'exception' : undefined} strokeColor={pct >= 90 ? '#ff4d4f' : undefined} />
            <Text type="secondary" style={{ fontSize: 11 }}>{formatTokens(r.used_tokens)} / {formatTokens(r.daily_limit)}</Text>
          </Space>
        );
      },
    },
    {
      title: '请求数',
      dataIndex: 'used_requests',
      key: 'used_requests',
      render: (v: number) => formatTokens(v),
    },
    {
      title: '用量占比',
      dataIndex: 'usage_percentage',
      key: 'usage_percentage',
      render: (p: number, r) =>
        r.daily_limit < 0 ? <Text type="secondary">—</Text> : <Text style={{ color: p >= 90 ? '#ff4d4f' : undefined }}>{p}%</Text>,
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>配额配置</Title>
        <Button icon={<ReloadOutlined />} onClick={() => { reloadConfigs(); reloadDashboard(); reloadUsage(); }}>刷新</Button>
      </div>

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'configs',
            label: '配额配置',
            children: (
              <Card style={{ borderRadius: 8 }} bodyStyle={{ padding: 0 }}>
                <Table
                  columns={configColumns}
                  dataSource={configs}
                  loading={configsLoading}
                  rowKey="id"
                  pagination={false}
                  style={{ borderRadius: 8, overflow: 'hidden' }}
                />
              </Card>
            ),
          },
          {
            key: 'dashboard',
            label: '用量概览',
            children: (
              <Space direction="vertical" style={{ width: '100%' }} size={16}>
                {dashboard && (
                  <Space wrap style={{ width: '100%' }} size={16}>
                    <Card style={{ borderRadius: 8, minWidth: 160 }} bodyStyle={{ padding: '16px 24px' }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>今日 Token</Text>
                      <div style={{ fontSize: 24, fontWeight: 700, fontFamily: 'monospace' }}>{formatTokens(dashboard.total_tokens_today)}</div>
                    </Card>
                    <Card style={{ borderRadius: 8, minWidth: 160 }} bodyStyle={{ padding: '16px 24px' }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>今日请求</Text>
                      <div style={{ fontSize: 24, fontWeight: 700, fontFamily: 'monospace' }}>{formatTokens(dashboard.total_requests_today)}</div>
                    </Card>
                    <Card style={{ borderRadius: 8, minWidth: 160 }} bodyStyle={{ padding: '16px 24px' }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>达限用户</Text>
                      <div style={{ fontSize: 24, fontWeight: 700, fontFamily: 'monospace', color: dashboard.users_at_limit > 0 ? '#ff4d4f' : undefined }}>{dashboard.users_at_limit}</div>
                    </Card>
                    <Card style={{ borderRadius: 8, minWidth: 160 }} bodyStyle={{ padding: '16px 24px' }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>总用户</Text>
                      <div style={{ fontSize: 24, fontWeight: 700, fontFamily: 'monospace' }}>{dashboard.total_users}</div>
                    </Card>
                  </Space>
                )}
                <Card title="Top 用户用量" style={{ borderRadius: 8 }} bodyStyle={{ padding: 0 }}>
                  <Table
                    columns={usageColumns}
                    dataSource={usageData?.data}
                    loading={usageLoading}
                    rowKey="user_id"
                    pagination={false}
                  />
                </Card>
              </Space>
            ),
          },
        ]}
      />

      {/* Edit Modal */}
      <Modal
        title={`编辑配额 — ${editConfig ? GROUP_LABELS[editConfig.quota_group] ?? editConfig.quota_group : ''}`}
        open={!!editConfig}
        onCancel={() => setEditConfig(null)}
        onOk={handleSave}
        okText="保存"
        cancelText="取消"
        okButtonProps={{ icon: <SaveOutlined /> }}
      >
        <Form form={form} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="daily_token_limit"
            label="每日 Token 上限"
            rules={[{ required: true, message: '请输入 Token 上限' }]}
          >
            <InputNumber min={-1} style={{ width: '100%' }} placeholder="-1 表示无限制" />
          </Form.Item>
          <Form.Item
            name="daily_request_limit"
            label="每日请求上限"
            rules={[{ required: true, message: '请输入请求上限' }]}
          >
            <InputNumber min={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="model_allowlist" label="模型白名单">
            <Input placeholder="逗号分隔，留空表示全部模型可用" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
