import { useState } from 'react';
import { Table, Input, Select, Space, Tag, Typography, Card, Tooltip, Badge, Button, message } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useRequest } from '../../hooks/useRequest';
import { auditService } from '../../services/api';
import type { AuditLog } from '../../types';

const { Title, Text } = Typography;

const ACTION_COLORS: Record<string, string> = {
  login: 'blue',
  logout: 'cyan',
  api_call: 'green',
  llm_request: 'purple',
  token_create: 'gold',
  token_revoke: 'orange',
  skill_create: 'lime',
  skill_update: 'geekblue',
  skill_archive: 'default',
  user_create: 'magenta',
  user_update: 'volcano',
};

const ACTION_LABELS: Record<string, string> = {
  login: '登录',
  logout: '登出',
  api_call: 'API 调用',
  llm_request: 'LLM 请求',
  token_create: 'Token 创建',
  token_revoke: 'Token 撤销',
  skill_create: 'Skill 创建',
  skill_update: 'Skill 更新',
  skill_archive: 'Skill 归档',
  user_create: '用户创建',
  user_update: '用户更新',
};

export default function AuditPage() {
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [actionFilter, setActionFilter] = useState<string | undefined>(undefined);
  const [keyword, setKeyword] = useState('');
  const [userIdFilter] = useState<string | undefined>(undefined);

  const { data, loading, run } = useRequest(auditService.list, {
    defaultParams: [{ page, page_size: pageSize, action: actionFilter, keyword, user_id: userIdFilter }],
    onError: () => message.error('审计日志加载失败'),
  });

  const reload = () => {
    run({ page, page_size: pageSize, action: actionFilter, keyword, user_id: userIdFilter });
  };

  const columns: ColumnsType<AuditLog> = [
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 170,
      render: (t: string) => (
        <Tooltip title={t}>
          <Text style={{ fontSize: 12, fontFamily: 'monospace' }}>
            {new Date(t).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
          </Text>
        </Tooltip>
      ),
    },
    {
      title: '用户',
      dataIndex: 'username',
      key: 'username',
      width: 120,
      render: (u: string) => <Text code style={{ fontSize: 12 }}>{u}</Text>,
    },
    {
      title: '操作',
      dataIndex: 'action',
      key: 'action',
      width: 110,
      render: (action: string) => (
        <Tag color={ACTION_COLORS[action] ?? 'default'} style={{ fontSize: 11 }}>
          {ACTION_LABELS[action] ?? action}
        </Tag>
      ),
    },
    {
      title: '资源',
      dataIndex: 'resource',
      key: 'resource',
      ellipsis: true,
      render: (r: string) => (
        <Tooltip title={r}>
          <Text type="secondary" style={{ fontSize: 12, fontFamily: 'monospace' }}>{r}</Text>
        </Tooltip>
      ),
    },
    {
      title: '详情',
      dataIndex: 'detail',
      key: 'detail',
      ellipsis: true,
      render: (d: string) => (
        <Tooltip title={d}>
          <Text style={{ fontSize: 12 }}>{d}</Text>
        </Tooltip>
      ),
    },
    {
      title: 'IP',
      dataIndex: 'ip',
      key: 'ip',
      width: 110,
      render: (ip: string) => <Text type="secondary" style={{ fontSize: 12, fontFamily: 'monospace' }}>{ip}</Text>,
    },
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 110,
      render: (id: string) => <Text type="secondary" style={{ fontSize: 11 }}>{id}</Text>,
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>审计日志</Title>
        <Space>
          <Input.Search
            placeholder="搜索用户/详情"
            style={{ width: 200 }}
            onSearch={(v) => { setKeyword(v); setPage(1); }}
            allowClear
          />
          <Select
            placeholder="操作类型"
            style={{ width: 130 }}
            allowClear
            onChange={(v) => { setActionFilter(v); setPage(1); }}
            options={Object.entries(ACTION_LABELS).map(([k, v]) => ({ label: v, value: k }))}
          />
          <Button icon={<ReloadOutlined />} onClick={reload}>刷新</Button>
        </Space>
      </div>

      <Card style={{ borderRadius: 8 }} bodyStyle={{ padding: 12 }}>
        <Table
          columns={columns}
          dataSource={data?.data}
          loading={loading}
          rowKey="id"
          pagination={{
            current: page,
            pageSize,
            total: data?.total,
            onChange: (p) => { setPage(p); run({ page: p, page_size: pageSize, action: actionFilter, keyword, user_id: userIdFilter }); },
            showSizeChanger: false,
            showTotal: (total) => `共 ${total} 条记录`,
          }}
        />
      </Card>

      {/* Legend */}
      <div style={{ marginTop: 16, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        {Object.entries(ACTION_LABELS).map(([k, v]) => (
          <Space key={k} size={4}>
            <Badge color={ACTION_COLORS[k]} />
            <Text type="secondary" style={{ fontSize: 12 }}>{v}</Text>
          </Space>
        ))}
      </div>
    </div>
  );
}
