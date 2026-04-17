import { useState } from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Layout, Menu, Typography, theme } from 'antd';
import {
  DashboardOutlined,
  UserOutlined,
  KeyOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  ToolOutlined,
  AuditOutlined,
  SettingOutlined,
} from '@ant-design/icons';

const { Header, Sider, Content } = Layout;
const { Title } = Typography;

const menuItems = [
  { key: '/dashboard', icon: <DashboardOutlined />, label: '用量看板' },
  { key: '/users', icon: <UserOutlined />, label: '用户管理' },
  { key: '/tokens', icon: <KeyOutlined />, label: 'API Token' },
  { key: '/skills', icon: <ToolOutlined />, label: 'Skills 管理' },
  { key: '/audit', icon: <AuditOutlined />, label: '审计日志' },
  { key: '/quota', icon: <SettingOutlined />, label: '配额配置' },
];

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { token } = theme.useToken();

  const selectedKey = menuItems.find((m) => location.pathname.startsWith(m.key))?.key ?? '/dashboard';

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        trigger={null}
        width={220}
        style={{
          background: token.colorBgContainer,
          borderRight: `1px solid ${token.colorBorderSecondary}`,
        }}
      >
        <div
          style={{
            height: 64,
            display: 'flex',
            alignItems: 'center',
            justifyContent: collapsed ? 'center' : 'flex-start',
            padding: collapsed ? 0 : '0 20px',
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
            gap: 8,
          }}
        >
          {collapsed ? (
            <span style={{ fontSize: 18, fontWeight: 700, color: token.colorPrimary }}>H</span>
          ) : (
            <>
              <span style={{ fontSize: 18, fontWeight: 700, color: token.colorPrimary }}>H</span>
              <Title level={5} style={{ margin: 0, lineHeight: 1 }}>
                Admin Console
              </Title>
            </>
          )}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ border: 'none', marginTop: 8 }}
        />
      </Sider>

      <Layout>
        <Header
          style={{
            padding: '0 16px',
            background: token.colorBgContainer,
            borderBottom: `1px solid ${token.colorBorderSecondary}`,
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <button
            onClick={() => setCollapsed(!collapsed)}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: '4px 8px',
              fontSize: 16,
              color: token.colorText,
              borderRadius: token.borderRadius,
            }}
            aria-label={collapsed ? '展开菜单' : '收起菜单'}
          >
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </button>
          <span style={{ color: token.colorTextSecondary, fontSize: 13 }}>
            Hermes 企业内部 SaaS — 管理控制台
          </span>
        </Header>
        <Content
          style={{
            margin: 24,
            minHeight: 280,
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
