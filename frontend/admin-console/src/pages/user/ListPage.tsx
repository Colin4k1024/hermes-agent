import { useState } from 'react';
import { Table, Button, Input, Select, Space, Tag, Popconfirm, message, Modal, Form, Typography, Card } from 'antd';
import { SearchOutlined, UserAddOutlined, ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useRequest } from '../../hooks/useRequest';
import { userService } from '../../services/api';
import type { UserListItem, CreateUserRequest } from '../../types';
import { useNavigate } from 'react-router-dom';

const { Title } = Typography;

const roleColor: Record<string, string> = {
  admin: 'red',
  power_user: 'orange',
  user: 'blue',
};

const statusColor: Record<string, string> = {
  active: 'green',
  disabled: 'default',
};

export default function UserListPage() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [keyword, setKeyword] = useState('');
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [roleFilter, setRoleFilter] = useState<string | undefined>();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [form] = Form.useForm();

  const { data, loading, run } = useRequest(userService.list, {
    defaultParams: [{ page, page_size: pageSize }],
    onError: () => message.error('用户列表加载失败'),
  });

  const reload = (p = page, ps = pageSize) => {
    setPage(p);
    setPageSize(ps);
    run({ page: p, page_size: ps, keyword: keyword || undefined, status: statusFilter, role: roleFilter });
  };

  const handleSearch = () => {
    setPage(1);
    run({ page: 1, page_size: pageSize, keyword: keyword || undefined, status: statusFilter, role: roleFilter });
  };

  const handleDisable = async (id: string) => {
    try {
      await userService.updateStatus(id, 'disabled');
      message.success('已禁用用户');
      reload();
    } catch {
      message.error('操作失败');
    }
  };

  const handleEnable = async (id: string) => {
    try {
      await userService.updateStatus(id, 'active');
      message.success('已启用用户');
      reload();
    } catch {
      message.error('操作失败');
    }
  };

  const handleCreateUser = async (values: Record<string, string>) => {
    try {
      const req: CreateUserRequest = {
        username: values.username,
        email: values.email,
        display_name: values.display_name,
        role: values.role as 'admin' | 'power_user' | 'user',
      };
      await userService.create(req);
      message.success('用户创建成功');
      setIsModalOpen(false);
      form.resetFields();
      reload(1);
    } catch {
      message.error('创建失败');
    }
  };

  const columns: ColumnsType<UserListItem> = [
    {
      title: '用户名',
      dataIndex: 'username',
      key: 'username',
      render: (v, record) => (
        <a onClick={() => navigate(`/users/${record.id}`)}>{v}</a>
      ),
    },
    {
      title: '邮箱',
      dataIndex: 'email',
      key: 'email',
      ellipsis: true,
    },
    {
      title: '姓名',
      dataIndex: 'display_name',
      key: 'display_name',
    },
    {
      title: '角色',
      dataIndex: 'role',
      key: 'role',
      render: (v: string) => (
        <Tag color={roleColor[v] ?? 'default'}>
          {v === 'admin' ? '管理员' : v === 'power_user' ? '高级用户' : '普通用户'}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      render: (v: string) => (
        <Tag color={statusColor[v] ?? 'default'}>
          {v === 'active' ? '活跃' : '已禁用'}
        </Tag>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'create_time',
      key: 'create_time',
      render: (v: string) => new Date(v).toLocaleDateString('zh-CN'),
      sorter: (a, b) => new Date(a.create_time).getTime() - new Date(b.create_time).getTime(),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: unknown, record: UserListItem) => (
        <Space size="small">
          <Button size="small" type="link" onClick={() => navigate(`/users/${record.id}`)}>
            详情
          </Button>
          {record.status === 'active' ? (
            <Popconfirm
              title="确认禁用该用户？"
              onConfirm={() => handleDisable(record.id)}
              okText="确认"
              cancelText="取消"
            >
              <Button size="small" danger type="link">
                禁用
              </Button>
            </Popconfirm>
          ) : (
            <Button size="small" type="link" onClick={() => handleEnable(record.id)}>
              启用
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <Title level={4} style={{ margin: 0 }}>
          用户管理
        </Title>
        <Button type="primary" icon={<UserAddOutlined />} onClick={() => setIsModalOpen(true)}>
          添加用户
        </Button>
      </div>

      {/* Filters */}
      <Card size="small" style={{ marginBottom: 16, borderRadius: 8 }}>
        <Space wrap>
          <Input
            placeholder="搜索用户名 / 邮箱 / 姓名"
            prefix={<SearchOutlined />}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={handleSearch}
            style={{ width: 240 }}
            allowClear
          />
          <Select
            placeholder="状态"
            value={statusFilter}
            onChange={(v) => { setStatusFilter(v); setPage(1); }}
            allowClear
            style={{ width: 100 }}
            options={[
              { label: '活跃', value: 'active' },
              { label: '已禁用', value: 'disabled' },
            ]}
          />
          <Select
            placeholder="角色"
            value={roleFilter}
            onChange={(v) => { setRoleFilter(v); setPage(1); }}
            allowClear
            style={{ width: 120 }}
            options={[
              { label: '管理员', value: 'admin' },
              { label: '高级用户', value: 'power_user' },
              { label: '普通用户', value: 'user' },
            ]}
          />
          <Button icon={<SearchOutlined />} onClick={handleSearch}>
            搜索
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => { setKeyword(''); setStatusFilter(undefined); setRoleFilter(undefined); reload(1); }}>
            重置
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
            onChange: (p, ps) => reload(p, ps),
          }}
          locale={{
            emptyText: (
              <div style={{ padding: 40, textAlign: 'center' }}>
                <p style={{ color: '#999' }}>暂无用户数据</p>
              </div>
            ),
          }}
        />
      </Card>

      {/* Create User Modal */}
      <Modal
        title="添加用户"
        open={isModalOpen}
        onCancel={() => { setIsModalOpen(false); form.resetFields(); }}
        onOk={() => form.submit()}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" onFinish={handleCreateUser}>
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input placeholder="user1" />
          </Form.Item>
          <Form.Item
            name="email"
            label="邮箱"
            rules={[
              { required: true, message: '请输入邮箱' },
              { type: 'email', message: '请输入有效邮箱' },
            ]}
          >
            <Input placeholder="user1@corp.example.com" />
          </Form.Item>
          <Form.Item
            name="display_name"
            label="姓名"
            rules={[{ required: true, message: '请输入姓名' }]}
          >
            <Input placeholder="张三" />
          </Form.Item>
          <Form.Item
            name="role"
            label="角色"
            rules={[{ required: true, message: '请选择角色' }]}
            initialValue="user"
          >
            <Select
              options={[
                { label: '普通用户', value: 'user' },
                { label: '高级用户', value: 'power_user' },
                { label: '管理员', value: 'admin' },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
