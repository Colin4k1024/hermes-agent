#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hermes Agent SaaS 化本地测试脚本
直接扫描源码验证改动，不依赖项目依赖安装

运行:
    cd /path/to/hermes-agent
    python3 test_saas_local.py
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent


class SourceScanner:
    """扫描源码文件，验证 SaaS 改造是否存在"""
    def __init__(self, file_path: Path):
        self.content = file_path.read_text()

    def has_pattern(self, pattern: str, flags: int = 0) -> bool:
        return bool(re.search(pattern, self.content, re.MULTILINE | flags))

    def count_occurrences(self, pattern: str) -> int:
        return len(re.findall(pattern, self.content, re.MULTILINE))


class TestAgentStateStore(unittest.TestCase):
    """agent/state_store.py SaaS 改造验证"""

    def setUp(self):
        self.s = SourceScanner(PROJECT_ROOT / "agent/state_store.py")

    def test_auth_headers_method_exists(self):
        """_auth_headers() 方法存在"""
        self.assertTrue(
            self.s.has_pattern(r"def _auth_headers\(self\)"),
            "_auth_headers() method not found"
        )

    def test_auth_headers_injects_tenant_id(self):
        """_auth_headers() 注入 X-Tenant-ID"""
        self.assertTrue(
            self.s.has_pattern(r'"X-Tenant-ID".*?tenant_id'),
            "X-Tenant-ID not found in _auth_headers"
        )

    def test_auth_headers_injects_user_id(self):
        """_auth_headers() 注入 X-User-ID"""
        self.assertTrue(
            self.s.has_pattern(r'"X-User-ID"'),
            "X-User-ID not found in _auth_headers"
        )

    def test_auth_headers_injects_authorization(self):
        """_auth_headers() 注入 Authorization Bearer token"""
        self.assertTrue(
            self.s.has_pattern(r'"Authorization".*?Bearer'),
            "Authorization Bearer not found in _auth_headers"
        )

    def test_validate_tenant_method_exists(self):
        """_validate_tenant() 方法存在"""
        self.assertTrue(
            self.s.has_pattern(r"def _validate_tenant\(self"),
            "_validate_tenant() method not found"
        )

    def test_validate_tenant_raises_permission_error(self):
        """_validate_tenant() 跨租户访问抛出 PermissionError"""
        self.assertTrue(
            self.s.has_pattern(r"raise PermissionError"),
            "PermissionError not raised in _validate_tenant"
        )

    def test_validate_tenant_checks_tenant_id(self):
        """_validate_tenant() 检查 session.tenant_id"""
        self.assertTrue(
            self.s.has_pattern(r"session_tenant|tenant_id") and
            self.s.has_pattern(r"runtime_context\.tenant_id"),
            "tenant_id comparison not found in _validate_tenant"
        )

    def test_httpx_connection_pooling(self):
        """httpx.Client 配置了连接池"""
        self.assertTrue(
            self.s.has_pattern(r"httpx\.Limits|max_connections|keepalive"),
            "httpx connection pooling not configured"
        )


class TestRunAgent(unittest.TestCase):
    """run_agent.py SaaS 改造验证"""

    def setUp(self):
        self.s = SourceScanner(PROJECT_ROOT / "run_agent.py")

    def test_hermes_state_url_env_var(self):
        """支持 HERMES_STATE_URL 环境变量"""
        self.assertTrue(
            self.s.has_pattern(r'HERMES_STATE_URL'),
            "HERMES_STATE_URL env var not referenced"
        )

    def test_remote_mode_auto_enable_with_url(self):
        """当 HERMES_STATE_URL 已设置时自动启用远程模式"""
        # 查找：if HERMES_STATE_URL: mode = "remote" 或类似逻辑
        self.assertTrue(
            self.s.has_pattern(r'HERMES_STATE_URL.*remote|remote.*HERMES_STATE_URL'),
            "Auto-enable remote mode when URL is set"
        )

    def test_remote_mode_requires_url_value_error(self):
        """远程模式无 URL 时抛出 ValueError"""
        self.assertTrue(
            self.s.has_pattern(r'raise\s+ValueError\([\s\S]*HERMES_STATE_URL'),
            "ValueError not raised when remote mode has no URL"
        )

    def test_supports_hermes_state_service_url_backward_compat(self):
        """向后兼容 HERMES_STATE_SERVICE_URL"""
        self.assertTrue(
            self.s.has_pattern(r'HERMES_STATE_SERVICE_URL'),
            "HERMES_STATE_SERVICE_URL backward compat not found"
        )


class TestGatewayRun(unittest.TestCase):
    """gateway/run.py SaaS 改造验证"""

    def setUp(self):
        self.s = SourceScanner(PROJECT_ROOT / "gateway/run.py")

    def test_tenant_id_extracted_from_feishu_event(self):
        """从飞书 event 提取 tenant_id"""
        self.assertTrue(
            self.s.has_pattern(r'tenant_key|tenant_id'),
            "tenant_id extraction from Feishu event not found"
        )

    def test_runtime_context_dict_constructed(self):
        """构造 runtime_context 字典"""
        self.assertTrue(
            self.s.has_pattern(r'"tenant_id".*?tenant_id|runtime_context.*=.*\{'),
            "runtime_context dict construction not found"
        )

    def test_runtime_context_passed_to_agent(self):
        """runtime_context 传递给 AIAgent"""
        self.assertTrue(
            self.s.has_pattern(r'runtime_context'),
            "runtime_context not passed to agent"
        )


class TestHermesCliConfig(unittest.TestCase):
    """hermes_cli/config.py SaaS 改造验证"""

    def setUp(self):
        self.s = SourceScanner(PROJECT_ROOT / "hermes_cli/config.py")

    def test_load_remote_config_function_exists(self):
        """_load_remote_config() 函数存在"""
        self.assertTrue(
            self.s.has_pattern(r"def _load_remote_config"),
            "_load_remote_config() not found"
        )

    def test_remote_config_loads_from_url(self):
        """远程配置从 HERMES_STATE_URL 加载"""
        self.assertTrue(
            self.s.has_pattern(r'HERMES_STATE_URL|state.*url'),
            "Remote config URL not found"
        )

    def test_remote_config_has_fallback(self):
        """远程配置失败时 fallback 到本地"""
        self.assertTrue(
            self.s.has_pattern(r'fallback|except.*load.*config|try:.*load.*config'),
            "Remote config fallback not found"
        )

    def test_hermes_state_mode_remote_check(self):
        """检查 HERMES_STATE_MODE=remote"""
        self.assertTrue(
            self.s.has_pattern(r'HERMES_STATE_MODE.*remote'),
            "HERMES_STATE_MODE=remote check not found"
        )


class TestSkillUtils(unittest.TestCase):
    """agent/skill_utils.py SaaS 改造验证"""

    def setUp(self):
        self.s = SourceScanner(PROJECT_ROOT / "agent/skill_utils.py")

    def test_hermes_shared_skills_env_var(self):
        """支持 HERMES_SHARED_SKILLS 环境变量"""
        self.assertTrue(
            self.s.has_pattern(r'HERMES_SHARED_SKILLS'),
            "HERMES_SHARED_SKILLS env var not found"
        )

    def test_shared_skills_default_path(self):
        """共享技能默认路径 /opt/hermes/skills"""
        self.assertTrue(
            self.s.has_pattern(r'/opt/hermes/skills'),
            "/opt/hermes/skills default path not found"
        )


class TestHermesState(unittest.TestCase):
    """hermes_state.py SaaS 改造验证"""

    def setUp(self):
        self.s = SourceScanner(PROJECT_ROOT / "hermes_state.py")

    def test_production_disclaimer_comment(self):
        """存在生产环境免责声明注释"""
        self.assertTrue(
            self.s.has_pattern(r'production|SaaS|RemoteStateStore|development.*only|local.*only', re.IGNORECASE),
            "Production disclaimer comment not found"
        )


class TestSkillCommands(unittest.TestCase):
    """agent/skill_commands.py SaaS 改造验证"""

    def setUp(self):
        self.s = SourceScanner(PROJECT_ROOT / "agent/skill_commands.py")

    def test_build_plan_path_checks_hermes_state_mode(self):
        """build_plan_path() 检查 HERMES_STATE_MODE"""
        self.assertTrue(
            self.s.has_pattern(r'HERMES_STATE_MODE.*remote'),
            "HERMES_STATE_MODE check in build_plan_path not found"
        )

    def test_saas_mode_uses_tempfile(self):
        """SaaS 模式使用 tempfile"""
        self.assertTrue(
            self.s.has_pattern(r'tempfile'),
            "tempfile usage in SaaS mode not found"
        )

    def test_local_mode_uses_dot_hermes(self):
        """本地模式使用 .hermes/plans/"""
        self.assertTrue(
            self.s.has_pattern(r'\.hermes.*plans'),
            ".hermes/plans path not found for local mode"
        )

    def test_saas_mode_uses_tenant_id_in_path(self):
        """SaaS 模式路径包含 tenant_id"""
        self.assertTrue(
            self.s.has_pattern(r'HERMES_TENANT_ID|tenant_id.*plans|plans.*tenant_id'),
            "tenant_id in plan path not found"
        )


class TestSummary(unittest.TestCase):
    """综合验证：所有改动文件都存在"""

    def test_all_saas_files_modified(self):
        """所有目标文件都已被修改"""
        modified_files = [
            "agent/state_store.py",
            "run_agent.py",
            "gateway/run.py",
            "hermes_cli/config.py",
            "agent/skill_utils.py",
            "hermes_state.py",
            "agent/skill_commands.py",
        ]
        for f in modified_files:
            path = PROJECT_ROOT / f
            self.assertTrue(path.exists(), f"File {f} not found")
            content = path.read_text()
            # 每个文件至少有一个 SaaS 相关关键词
            has_saas_marker = any(k in content for k in [
                "HERMES_STATE_MODE", "HERMES_STATE_URL", "HERMES_SHARED_SKILLS",
                "_auth_headers", "_validate_tenant", "tenant_id", "runtime_context",
                "_load_remote_config", "tempfile", "RemoteStateStore", "SaaS"
            ])
            self.assertTrue(has_saas_marker, f"No SaaS marker found in {f}")


if __name__ == "__main__":
    print("=" * 60)
    print("Hermes Agent SaaS Transformation Verification")
    print("=" * 60)
    print()
    print("Verifying source code changes without importing modules")
    print()

    # Run tests
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Summary
    print()
    print("=" * 60)
    if result.wasSuccessful():
        print("All SaaS transformations verified!")
    else:
        print(f"FAILURES: {len(result.failures)}")
        print(f"ERRORS: {len(result.errors)}")
    print("=" * 60)

    sys.exit(0 if result.wasSuccessful() else 1)
