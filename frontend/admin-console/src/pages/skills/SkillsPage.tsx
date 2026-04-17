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
  Tooltip,
  Badge,
  Spin,
} from 'antd';
import {
  PlusOutlined,
  ReloadOutlined,
  EditOutlined,
  DeleteOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import { useRequest } from '../../hooks/useRequest';
import { skillService } from '../../services/api';
import type { SkillSummary, SkillDetail, CreateSkillRequest, UpdateSkillRequest } from '../../types';

const { Title, Text } = Typography;

const SAMPLE_SKILL_MD = `---
name: \${name}
description: \${description}
version: 1.0.0
author: \${author}
license: MIT
tags: [\${tags}]
related_skills: []
---

# \${name}

This is a sample skill for demonstration purposes.
`;

export default function SkillsPage() {
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [keyword, setKeyword] = useState('');

  // Create modal
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);

  // Edit modal
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editSkill, setEditSkill] = useState<SkillSummary | null>(null);
  const [editLoading, setEditLoading] = useState(false);
  const [editSkillMd, setEditSkillMd] = useState('');

  // View modal
  const [isViewModalOpen, setIsViewModalOpen] = useState(false);
  const [viewSkill, setViewSkill] = useState<SkillDetail | null>(null);

  const [form] = Form.useForm();
  const [editForm] = Form.useForm();

  const { data, loading, run } = useRequest(skillService.list, {
    defaultParams: [{ status: statusFilter, keyword }],
    onError: () => message.error('Skills 列表加载失败'),
  });

  const reload = useCallback(() => {
    run({ status: statusFilter, keyword });
  }, [run, statusFilter, keyword]);

  const handleCreate = async (values: Record<string, string>) => {
    setCreateLoading(true);
    try {
      const tags = values.tags
        ? values.tags.split(',').map((t) => t.trim()).filter(Boolean)
        : [];
      const skillMd = values.skill_md || SAMPLE_SKILL_MD
        .replace('\${name}', values.name)
        .replace('\${description}', values.description || '')
        .replace('\${author}', values.author || '')
        .replace('\${tags}', tags.join(', '));

      const req: CreateSkillRequest = {
        name: values.name,
        description: values.description,
        published_by: values.author,
        tags,
        skill_md: skillMd,
      };
      await skillService.create(req);
      message.success(`Skill '${values.name}' 创建成功`);
      setIsCreateModalOpen(false);
      form.resetFields();
      setPage(1);
      reload();
    } catch (err) {
      message.error(`创建失败: ${err instanceof Error ? err.message : err}`);
    } finally {
      setCreateLoading(false);
    }
  };

  const handleEdit = async (skill: SkillSummary) => {
    setEditSkill(skill);
    setEditSkillMd(SAMPLE_SKILL_MD
      .replace('\${name}', skill.name)
      .replace('\${description}', skill.description)
      .replace('\${author}', skill.author || '')
      .replace('\${tags}', skill.tags.join(', ')));
    editForm.setFieldsValue({
      name: skill.name,
      description: skill.description,
      author: skill.author,
      tags: skill.tags.join(', '),
    });
    setIsEditModalOpen(true);
  };

  const handleEditSave = async (values: Record<string, string>) => {
    if (!editSkill) return;
    setEditLoading(true);
    try {
      const tags = values.tags
        ? values.tags.split(',').map((t) => t.trim()).filter(Boolean)
        : [];

      const req: UpdateSkillRequest = {
        description: values.description,
        tags,
        skill_md: values.skill_md || undefined,
      };
      await skillService.update(editSkill.name, req);
      message.success(`Skill '${editSkill.name}' 更新成功`);
      setIsEditModalOpen(false);
      editForm.resetFields();
      setEditSkill(null);
      reload();
    } catch (err) {
      message.error(`更新失败: ${err instanceof Error ? err.message : err}`);
    } finally {
      setEditLoading(false);
    }
  };

  const handleArchive = async (name: string) => {
    try {
      await skillService.archive(name);
      message.success(`Skill '${name}' 已归档`);
      reload();
    } catch (err) {
      message.error(`归档失败: ${err instanceof Error ? err.message : err}`);
    }
  };

  const handlePreview = async (skill: SkillSummary) => {
    try {
      const detail = await skillService.get(skill.name);
      setViewSkill(detail);
      setIsViewModalOpen(true);
    } catch (err) {
      message.error(`加载详情失败: ${err instanceof Error ? err.message : err}`);
    }
  };

  const columns: ColumnsType<SkillSummary> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string) => (
        <Text strong style={{ fontFamily: 'monospace' }}>{name}</Text>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (desc: string) => (
        <Tooltip title={desc}>
          <span style={{ color: '#666' }}>{desc || '—'}</span>
        </Tooltip>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 90,
      render: (status: string) => (
        <Badge
          status={status === 'active' ? 'success' : 'default'}
          text={status === 'active' ? '活跃' : '已归档'}
        />
      ),
    },
    {
      title: '版本',
      dataIndex: 'version',
      key: 'version',
      width: 80,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '标签',
      dataIndex: 'tags',
      key: 'tags',
      render: (tags: string[]) => (
        <>
          {tags.slice(0, 3).map((t) => (
            <Tag key={t} style={{ marginBottom: 2 }}>{t}</Tag>
          ))}
          {tags.length > 3 && <Tag style={{ marginBottom: 2 }}>+{tags.length - 3}</Tag>}
        </>
      ),
    },
    {
      title: '更新',
      dataIndex: 'update_time',
      key: 'update_time',
      width: 100,
      render: (t: string) => new Date(t).toLocaleDateString('zh-CN'),
    },
    {
      title: '操作',
      key: 'action',
      width: 140,
      render: (_, record) => (
        <Space size="small">
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => handlePreview(record)}
          />
          <Button
            type="text"
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
            disabled={record.status === 'archived'}
          />
          {record.status === 'active' && (
            <Popconfirm
              title="归档此 Skill？"
              description="归档后可重新激活，不会删除文件"
              onConfirm={() => handleArchive(record.name)}
              okText="归档"
              cancelText="取消"
            >
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
              />
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>Skills 管理</Title>
        <Space>
          <Input.Search
            placeholder="搜索名称/描述"
            style={{ width: 200 }}
            onSearch={(v) => { setKeyword(v); setPage(1); }}
            allowClear
          />
          <Select
            placeholder="状态筛选"
            style={{ width: 120 }}
            allowClear
            onChange={(v) => { setStatusFilter(v); setPage(1); }}
            options={[
              { label: '活跃', value: 'active' },
              { label: '已归档', value: 'archived' },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={reload}>刷新</Button>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setIsCreateModalOpen(true)}
          >
            新建 Skill
          </Button>
        </Space>
      </div>

      <Card style={{ borderRadius: 8 }} bodyStyle={{ padding: 12 }}>
        <Spin spinning={loading}>
          <Table
            columns={columns}
            dataSource={data?.data}
            loading={loading}
            rowKey="name"
            pagination={{
              current: page,
              pageSize,
              total: data?.total,
              onChange: setPage,
              showSizeChanger: false,
              showTotal: (total) => `共 ${total} 个 Skill`,
            }}
          />
        </Spin>
      </Card>

      {/* Create Modal */}
      <Modal
        title="新建 Skill"
        open={isCreateModalOpen}
        onCancel={() => { setIsCreateModalOpen(false); form.resetFields(); }}
        footer={null}
        width={640}
        destroyOnClose
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={handleCreate}
        >
          <Form.Item
            name="name"
            label="Skill 名称"
            rules={[
              { required: true, message: '请输入名称' },
              { pattern: /^[a-zA-Z0-9_-]+$/, message: '仅支持字母、数字、下划线和连字符' },
            ]}
          >
            <Input placeholder="如: github, jira, web-search" />
          </Form.Item>

          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="简要描述此 Skill 的功能" />
          </Form.Item>

          <Form.Item name="author" label="作者">
            <Input placeholder="admin@corp.example.com" />
          </Form.Item>

          <Form.Item name="tags" label="标签">
            <Input placeholder="用逗号分隔，如: devops, github, automation" />
          </Form.Item>

          <Form.Item name="skill_md" label="SKILL.md 内容">
            <Input.TextArea
              rows={12}
              placeholder="输入 SKILL.md 的原始内容（YAML frontmatter + Markdown）"
              style={{ fontFamily: 'monospace', fontSize: 12 }}
            />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0 }}>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button onClick={() => { setIsCreateModalOpen(false); form.resetFields(); }}>
                取消
              </Button>
              <Button type="primary" htmlType="submit" loading={createLoading}>
                创建
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* Edit Modal */}
      <Modal
        title={`编辑 Skill: ${editSkill?.name}`}
        open={isEditModalOpen}
        onCancel={() => { setIsEditModalOpen(false); editForm.resetFields(); setEditSkill(null); }}
        footer={null}
        width={720}
        destroyOnClose
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={handleEditSave}
          initialValues={{
            name: editSkill?.name,
            description: editSkill?.description,
            author: editSkill?.author,
            tags: editSkill?.tags?.join(', '),
          }}
        >
          <Form.Item name="name" label="Skill 名称">
            <Input disabled />
          </Form.Item>

          <Form.Item name="description" label="描述">
            <Input.TextArea rows={2} placeholder="简要描述此 Skill 的功能" />
          </Form.Item>

          <Form.Item name="author" label="作者">
            <Input placeholder="admin@corp.example.com" />
          </Form.Item>

          <Form.Item name="tags" label="标签">
            <Input placeholder="用逗号分隔，如: devops, github, automation" />
          </Form.Item>

          <Form.Item name="skill_md" label="SKILL.md 内容">
            <Input.TextArea
              rows={16}
              placeholder="输入 SKILL.md 的原始内容"
              value={editSkillMd}
              onChange={(e) => setEditSkillMd(e.target.value)}
              style={{ fontFamily: 'monospace', fontSize: 12 }}
            />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0 }}>
            <Space style={{ width: '100%', justifyContent: 'flex-end' }}>
              <Button onClick={() => { setIsEditModalOpen(false); editForm.resetFields(); setEditSkill(null); }}>
                取消
              </Button>
              <Button type="primary" htmlType="submit" loading={editLoading}>
                保存
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* Preview Modal */}
      <Modal
        title={`Skill: ${viewSkill?.name}`}
        open={isViewModalOpen}
        onCancel={() => setIsViewModalOpen(false)}
        footer={null}
        width={640}
      >
        {viewSkill && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '80px 1fr', gap: 8 }}>
              <Text type="secondary">描述：</Text>
              <Text>{viewSkill.description}</Text>
              <Text type="secondary">状态：</Text>
              <Badge status={viewSkill.status === 'active' ? 'success' : 'default'} text={viewSkill.status === 'active' ? '活跃' : '已归档'} />
              <Text type="secondary">版本：</Text>
              <Tag>{viewSkill.version}</Tag>
              <Text type="secondary">作者：</Text>
              <Text>{viewSkill.author || '—'}</Text>
              <Text type="secondary">标签：</Text>
              <div>{viewSkill.tags.map((t) => <Tag key={t}>{t}</Tag>)}</div>
              <Text type="secondary">更新时间：</Text>
              <Text>{new Date(viewSkill.update_time).toLocaleString('zh-CN')}</Text>
              <Text type="secondary">NAS 路径：</Text>
              <Text style={{ fontFamily: 'monospace', fontSize: 11 }}>{viewSkill.nas_path}</Text>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
