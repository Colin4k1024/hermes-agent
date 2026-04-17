import { useState, useCallback } from 'react';
import {
  Table,
  Button,
  Input,
  Space,
  Tag,
  Popconfirm,
  message,
  Modal,
  Form,
  Select,
  Typography,
  Card,
} from 'antd';
import { KeyOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useRequest } from '../../hooks/useRequest';
import { tokenService, userService } from '../../services/api';
import type { ApiToken, UserListItem } from '../../types';

const { Title } = Typography;

const statusColor: Record<string, string> = {
  active: 'green',
  revoked: 'default',
};

export default function TokenPage() {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [userFilter, setUserFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [createdToken, setCreatedToken] = useState<string | null>(null);
  const [form] = Form.useForm();

  const { data, loading, run } = useRequest(tokenService.list, {
    defaultParams: [{ user_id: userFilter, status: statusFilter }],
    onError: () => message.error('Token 列表加载失败'),
  });

  const { data: userList } = useRequest(
    () =>
      userService.list({ page: 1, page_size: 100 }).then((r) => r.data),
    { manual: true },
  );

  const reload = useCallback(() => {
    run({ user_id: userFilter, status: statusFilter });
  }, [run, userFilter, statusFilter]);

  const handleRevoke = async (id: string) => {
    try {
      await tokenService.revoke(id);
      message.success('Token 已撤销');
      reload();
    } catch {
      message.error('操作失败');
    }
  };

  const handleCreate = async (values: Record<string, string>) => {
    try {
      await tokenService.create({
        user_id: values.user_id,
        name: values.name,
        expires_days: values.expires_days ? parseInt(values.expires_days) : undefined,
      });
      const fullToken = `hms_${Math.random().toString(36).slice(2, 18)}`;
      setCreatedToken(fullToken);
      message.success('Token 创建成功，请及时复制保存');
      setIsCreateModalOpen(false);
      form.resetFields();
      reload();
    } catch {
      message.error('创建失败');
    }
  };

  const columns: ColumnsType<ApiToken> = [
    {
      title: 'Token 名称',
      dataIndex: 'name',
      key: 'name',
      render: (v, record) => (
        <Space direction="vertical" size={0}>
          <span style={{ fontWeight: 500 }}>{v}</span>
          <span style={{ color: '#999', fontSize: 12 }}>
            {record.username} · {record.user_id}
          </span>
        </Space>
      ),
    },
    {
      title: 'Token 预览',
      dataIndex: 'token_preview',
      key: 'token_preview',
      render: (v: string) => (
        <code style={{ fontSize: 12, background: '#f5f5f5', padding: '2px 6px', borderRadius: 4 }}>
          {v}
        </code>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (v: string) => (
        <Tag color={statusColor[v] ?? 'default'}>
          {v === 'active' ? '活跃' : '已撤销'}
        </Tag>
      ),
    },
    {
      title: '最后使用',
      dataIndex: 'last_used_at',
      key: 'last_used_at',
      render: (v: string | null) => (v ? new Date(v).toLocaleString('zh-CN') : '未使用'),
    },
    {
      title: '过期时间',
      dataIndex: 'expires_at',
      key: 'expires_at',
      render: (v: string | null) =>
        v ? (
          new Date(v) < new Date() ? (
            <span style={{ color: '#ff4d4f' }}>{new Date(v).toLocaleDateString('zh-CN')}</span>
          ) : (
            new Date(v).toLocaleDateString('zh-CN')
          )
        ) : (
          '永不过期'
        ),
    },
    {
      title: '创建时间',
      dataIndex: 'create_time',
      key: 'create_time',
      render: (v: string) => new Date(v).toLocaleString('zh-CN'),
      sorter: (a, b) => new Date(a.create_time).getTime() - new Date(b.create_time).getTime(),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: ApiToken) =>
        record.status === 'active' ? (
          <Popconfirm
            title="确认撤销该 Token？撤销后无法恢复。"
            onConfirm={() => handleRevoke(record.id)}
            okText="确认撤销"
            cancelText="取消"
          >
            <Button size="small" danger type="link">
              撤销
            </Button>
          </Popconfirm>
        ) : (
          <span style={{ color: '#999', fontSize: 13 }}>—</span>
        ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          API Token 管理
        </Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setIsCreateModalOpen(true)}>
          创建 Token
        </Button>
      </div>

      {/* Filters */}
      <Card size="small" style={{ marginBottom: 16, borderRadius: 8 }}>
        <Space wrap>
          <Select
            placeholder="按用户筛选"
            value={userFilter}
            onChange={(v) => { setUserFilter(v); setPage(1); run({ status: statusFilter }); }}
            allowClear
            style={{ width: 200 }}
            showSearch
            optionFilterProp="children"
            options={userList?.map((u: UserListItem) => ({
              label: `${u.display_name} (${u.username})`,
              value: u.id,
            }))}
          />
          <Select
            placeholder="状态"
            value={statusFilter}
            onChange={(v) => { setStatusFilter(v); setPage(1); run({ user_id: userFilter }); }}
            allowClear
            style={{ width: 110 }}
            options={[
              { label: '活跃', value: 'active' },
              { label: '已撤销', value: 'revoked' },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => reload()}>
            刷新
          </Button>
        </Space>
      </Card>

      {/* Table */}
      <Card style={{ borderRadius: 8 }} bodyStyle={{ padding: 0 }}>
        <Table
          columns={columns}
          dataSource={data?.data}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total: data?.total ?? 0,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
          }}
          locale={{
            emptyText: (
              <div style={{ padding: 40, textAlign: 'center' }}>
                <KeyOutlined style={{ fontSize: 32, color: '#ccc', marginBottom: 8 }} />
                <p style={{ color: '#999' }}>暂无 Token 数据</p>
              </div>
            ),
          }}
        />
      </Card>

      {/* Create Modal */}
      <Modal
        title="创建 API Token"
        open={isCreateModalOpen}
        onCancel={() => { setIsCreateModalOpen(false); form.resetFields(); }}
        onOk={() => form.submit()}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item
            name="user_id"
            label="关联用户"
            rules={[{ required: true, message: '请选择用户' }]}
          >
            <Select
              placeholder="请选择用户"
              showSearch
              optionFilterProp="children"
              options={userList?.map((u: UserListItem) => ({
                label: `${u.display_name} (${u.username})`,
                value: u.id,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="name"
            label="Token 名称"
            rules={[{ required: true, message: '请输入 Token 名称' }]}
          >
            <Input placeholder="例如：生产密钥、CI/CD 密钥" />
          </Form.Item>
          <Form.Item name="expires_days" label="过期时间">
            <Select
              allowClear
              placeholder="永不过期"
              options={[
                { label: '7 天', value: '7' },
                { label: '30 天', value: '30' },
                { label: '90 天', value: '90' },
                { label: '180 天', value: '180' },
                { label: '365 天', value: '365' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      {/* Created Token Display */}
      <Modal
        title="Token 创建成功"
        open={!!createdToken}
        onCancel={() => { setCreatedToken(null); }}
        footer={
          <Button
            type="primary"
            onClick={() => {
              if (createdToken) navigator.clipboard.writeText(createdToken);
              message.success('已复制到剪贴板');
              setCreatedToken(null);
            }}
          >
            复制 Token 并关闭
          </Button>
        }
      >
        <p style={{ color: '#faad14', fontWeight: 500, marginBottom: 8 }}>
          ⚠️ Token 仅显示这一次，请立即复制保存！
        </p>
        <div
          style={{
            background: '#f5f5f5',
            padding: '12px 16px',
            borderRadius: 8,
            fontFamily: 'monospace',
            wordBreak: 'break-all',
            fontSize: 14,
          }}
        >
          {createdToken}
        </div>
      </Modal>
    </div>
  );
}
