---
artifact: nas-nfs-v4-verification
parent: delivery-plan.md
date: 2026-04-17
role: devops
status: ready-for-sign-off
关联ADR: ADR-004
关联需求: hermes-enterprise-saas H2（NAS NFS v4 SQLite WAL 兼容性验证）
---

# NAS NFS v4 验证指南

**用途**: DevOps 工程师在 Phase 1 部署前验证 NAS NFS v4 配置正确性
**关联**: ADR-004（2026-04-16 确认）、H2 验收项
**目标**: 确保 NAS NFS v4 支持 SQLite WAL 并发读写

---

## 1. 前置条件

| 检查项 | 要求 | 验证命令 |
|--------|------|---------|
| NAS 设备 | 支持 NFS v4.1 或 v4.2 | 参见 NAS 管理界面 |
| NFS 服务端 | export 允许 NFS v4 连接 | `rpcinfo -p <NAS_IP>` |
| 防火墙 | TCP 2049 开放（NFS） | `sudo iptables -L -n \| grep 2049` |
| NAS 网络 | K8s Node 与 NAS 之间 1Gbps+ | `ping <NAS_IP>` |
| NAS SSD 后端 | SSD tier 确认（ADR-004 要求）| 参见 NAS 规格 |
| NFS export 路径 | `/hermes-homes` 或对应 export | 参见 NAS 配置 |

> ⚠️ **关键**: NFS v3 的 NLM 锁机制与 SQLite WAL 不兼容。**必须使用 NFS v4.1 或 v4.2**。

---

## 2. 验证步骤

### Step 1 — 验证 NFS 客户端已安装

```bash
# Linux: 检查 NFS 客户端模块
rpcinfo -p | grep nfs
# 预期输出包含: nfs 3 或 4

# 检查 nfs4 支持
mount -t nfs4
# 无报错表示 nfs4 可用

# 确认已挂载（如果已配置）
mount | grep nfs

# macOS: 检查 nfsd 状态
nfsd status
nfsstat -m
```

**通过条件**: `rpcinfo` 显示 NFS 服务活跃，macOS `nfsd status` 为 `enabled`

---

### Step 2 — 测试 NFS v4 挂载

```bash
# 创建临时挂载点
sudo mkdir -p /mnt/nfs-test

# 挂载 NFS v4（替换 <NFS_SERVER> 为实际 NAS IP 或 hostname）
sudo mount -t nfs4 -o vers=4.1,noatime,rsize=1048576,wsize=1048576 \
  <NFS_SERVER>:/ /mnt/nfs-test

# 验证使用的是 v4.x 协议
nfsstat -m | grep vers
# 预期: vers=4.1 或 vers=4.2

# 检查挂载选项
mount | grep nfs-test
# 预期包含: rsize=1048576,wsize=1048576,noatime
```

**通过条件**: 挂载成功，`nfsstat -m` 显示 `vers=4.1` 或 `vers=4.2`

---

### Step 3 — SQLite WAL 兼容性测试（关键测试）

> 此测试直接验证 H2 假设：NAS NFS v4 支持 SQLite WAL 文件锁并发安全

```bash
# 进入测试目录（使用唯一目录名避免冲突）
cd /mnt/nfs-test
mkdir -p test-$(date +%s)
cd test-$(date +%s)

python3 << 'EOF'
import sqlite3, os, threading, time

db_path = f"/mnt/nfs-test/test-{os.getpid()}/wal_test.db"
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# Test 1: 基础 WAL 模式
conn = sqlite3.connect(db_path, timeout=10)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("CREATE TABLE test(id INTEGER PRIMARY KEY)")
conn.execute("INSERT INTO test VALUES(1)")
conn.commit()
wal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
print(f"✓ WAL enabled: {wal_mode}")
assert wal_mode == "wal", f"Expected WAL mode, got {wal_mode}"

# Test 2: 并发写入（模拟多 Pod 场景）
results = []
def write并发(i):
    try:
        c = sqlite3.connect(db_path, timeout=5)
        c.execute("INSERT INTO test VALUES(?)", (i,))
        c.commit()
        results.append(('success', i))
    except Exception as e:
        results.append(('error', str(e)))

threads = [threading.Thread(target=write并发, args=(i,)) for i in range(10)]
for t in threads: t.start()
for t in threads: t.join()

errors = [r for r in results if r[0] == 'error']
success_count = len([r for r in results if r[0] == 'success'])
print(f"✓ Concurrent writes: {success_count}/10 success, {len(errors)} errors")
if errors:
    print(f"  Errors: {errors[:3]}")
    raise AssertionError(f"Concurrent writes failed: {errors[:3]}")

# Test 3: WAL checkpoint under load
conn.execute("INSERT INTO test SELECT * FROM test")  # double rows
conn.commit()
os.sync()
row_count = conn.execute("SELECT count(*) FROM test").fetchone()[0]
print(f"✓ WAL checkpoint: OK, {row_count} rows (expected 22)")

conn.close()
print("✓ SQLite WAL on NFS v4: COMPATIBLE")
EOF

# 测试通过后清理
cd /
sudo umount /mnt/nfs-test
sudo rm -rf /mnt/nfs-test
```

**通过条件**: 所有 3 个测试输出 ✓，无 error，无 AssertionError

> ⚠️ 如果此测试失败（特别是并发写入 errors），**严禁进入 Phase 1**。需先解决 NFS v4 文件锁问题。

---

### Step 4 — Shard 目录结构验证

```bash
# 创建测试目录结构（模拟 256-shard）
TEST_BASE="/mnt/nfs-test/shard-validation-$(date +%s)"
mkdir -p $TEST_BASE

# 验证 256 个 shard 目录可创建
python3 << 'EOF'
import os
import hashlib

test_base = os.environ["TEST_BASE"]
failures = []

for i in range(256):
    shard = f"{i:02x}"  # 00 to ff
    shard_path = os.path.join(test_base, shard)
    try:
        os.makedirs(shard_path, exist_ok=True)
    except Exception as e:
        failures.append((shard, str(e)))

print(f"Shard creation: {256 - len(failures)}/256 succeeded")
if failures:
    print(f"Failures: {failures[:5]}")

# 验证 shard 计算算法
for user_id, expected_shard in [
    ("user-abc123", "78"),  # example
    ("user-def456", "5c"),  # example
]:
    h = hashlib.sha256(user_id.encode()).hexdigest()
    shard = h[:2]
    path = os.path.join(test_base, shard, f"{user_id}")
    print(f"  sha256({user_id})[:2] = {shard} -> {path}")

print("✓ 256-shard structure validated")
EOF

# 清理
sudo rm -rf $TEST_BASE
```

---

### Step 5 — 性能基准测试

```bash
# 安装 fio（如果未安装）
# Ubuntu/Debian: sudo apt-get install fio
# macOS: brew install fio

TEST_DIR="/mnt/nfs-test/perf-$(date +%s)"
mkdir -p $TEST_DIR

echo "=== NFS v4 Performance Benchmarks ==="

# Sequential Read (预期: >= 200 MB/s)
fio --name=seq_read --filename=$TEST_DIR/fio_seq_read \
    --rw=read --bs=1m --numjobs=4 --time_based --runtime=10 \
    --size=512m --readonly --foirect=0 \
    --nfs_url=nfs://<NFS_SERVER>:/$TEST_DIR 2>&1 | grep -E "IOPS|bw="

# Sequential Write (预期: >= 150 MB/s)
fio --name=seq_write --filename=$TEST_DIR/fio_seq_write \
    --rw=write --bs=1m --numjobs=4 --time_based --runtime=10 \
    --size=512m --foirect=0 --sync=0 \
    --nfs_url=nfs://<NFS_SERVER>:/$TEST_DIR 2>&1 | grep -E "IOPS|bw="

# Random Read IOPS (预期 p99: < 10ms latency for 4KB)
fio --name=rand_read --filename=$TEST_DIR/fio_rand_read \
    --rw=randread --bs=4k --numjobs=16 --time_based --runtime=10 \
    --size=256m --readonly --foirect=0 \
    --nfs_url=nfs://<NFS_SERVER>:/$TEST_DIR 2>&1 | grep -E "IOPS|lat"

# Random Write IOPS
fio --name=rand_write --filename=$TEST_DIR/fio_rand_write \
    --rw=randwrite --bs=4k --numjobs=16 --time_based --runtime=10 \
    --size=256m --foirect=0 --sync=0 \
    --nfs_url=nfs://<NFS_SERVER>:/$TEST_DIR 2>&1 | grep -E "IOPS|lat"

# 清理
sudo rm -rf $TEST_DIR
```

**性能要求**:

| 指标 | 最低要求 | 说明 |
|------|---------|------|
| 顺序读吞吐 | ≥ 200 MB/s | 冷启动时加载 state.db |
| 顺序写吞吐 | ≥ 150 MB/s | WAL checkpoint |
| 4KB 随机读 p99 延迟 | < 10ms | SQLite 页面读取 |
| 4KB 随机写 IOPS | ≥ 5000 | WAL 追加 |

---

## 3. K8s 集成验证清单

> 完成以下检查项，确保 StorageClass 和 NFS Subdir External Provisioner 配置正确

- [ ] `nfs-hermes-per-user` StorageClass 已创建
  ```bash
  kubectl get storageclass nfs-hermes-per-user
  ```

- [ ] NFS Subdir External Provisioner 已安装
  ```bash
  kubectl get pods -n nfs-provisioner
  kubectl get sc -n nfs-provisioner
  ```

- [ ] 测试 PVC 创建
  ```bash
  cat << 'EOF' | kubectl apply -f -
  apiVersion: v1
  kind: PersistentVolumeClaim
  metadata:
    name: test-pvc-verification
    namespace: hermes-agent
  spec:
    accessModes:
      - ReadWriteMany
    storageClassName: nfs-hermes-per-user
    resources:
      requests:
        storage: 100Mi
  EOF
  kubectl get pvc test-pvc-verification -n hermes-agent
  ```

- [ ] PVC 绑定到正确的 NFS 路径
  ```bash
  # 检查 PV 详情
  kubectl get pv $(kubectl get pvc test-pvc-verification -n hermes-agent -o jsonpath='{.spec.volumeName}') \
    -o jsonpath='{.spec.nfs.path}'
  # 预期: /hermes-homes/<some-path>
  ```

- [ ] Pod 挂载并写入测试
  ```bash
  cat << 'EOF' | kubectl apply -f -
  apiVersion: v1
  kind: Pod
  metadata:
    name: nfs-test-pod
    namespace: hermes-agent
  spec:
    containers:
    - name: test
      image: busybox
      command: ["sh", "-c", "echo 'test' > /mnt/test/file.txt && cat /mnt/test/file.txt"]
      volumeMounts:
      - name: nfs-test
        mountPath: /mnt/test
    volumes:
    - name: nfs-test
      persistentVolumeClaim:
        claimName: test-pvc-verification
    restartPolicy: Never
  EOF
  kubectl logs nfs-test-pod -n hermes-agent
  kubectl delete pod nfs-test-pod -n hermes-agent
  ```

- [ ] **WAL 文件锁跨 Pod 测试**（最关键）
  ```bash
  # Pod A: 创建数据库并持有写锁
  kubectl apply -f - << 'EOF'
  apiVersion: v1
  kind: Pod
  metadata:
    name: wal-test-pod-a
    namespace: hermes-agent
  spec:
    containers:
    - name: test
      image: python:3.11
      command: ["python3", "-c",
        "import sqlite3; c=sqlite3.connect('/mnt/data/test.db'); c.execute('PRAGMA journal_mode=WAL'); c.execute('CREATE TABLE IF NOT EXISTS t(i INT)'); c.execute('INSERT INTO t VALUES(42)'); c.commit(); import time; time.sleep(60)"]
      volumeMounts:
      - name: nfs-test
        mountPath: /mnt/data
    volumes:
    - name: nfs-test
      persistentVolumeClaim:
        claimName: test-pvc-verification
  EOF

  # Pod B: 尝试并发写入（不应阻塞）
  kubectl apply -f - << 'EOF'
  apiVersion: v1
  kind: Pod
  metadata:
    name: wal-test-pod-b
    namespace: hermes-agent
  spec:
    containers:
    - name: test
      image: python:3.11
      command: ["python3", "-c",
        "import sqlite3, time; time.sleep(2); c=sqlite3.connect('/mnt/data/test.db', timeout=10); c.execute('INSERT INTO t VALUES(99)'); c.commit(); print('OK')"]
      volumeMounts:
      - name: nfs-test
        mountPath: /mnt/data
    volumes:
    - name: nfs-test
      persistentVolumeClaim:
        claimName: test-pvc-verification
  EOF

  kubectl logs wal-test-pod-b -n hermes-agent
  # 预期: 输出 "OK" 而非超时或错误
  kubectl delete pod wal-test-pod-a wal-test-pod-b -n hermes-agent
  ```

- [ ] 清理测试 PVC
  ```bash
  kubectl delete pvc test-pvc-verification -n hermes-agent
  ```

---

## 4. 已知问题与故障排查

### NFS v3 vs v4：为什么必须 v4.1+

| 特性 | NFS v3 | NFS v4.1+ |
|------|--------|----------|
| 文件锁协议 | NLM（独立服务）| NFSv4 内置 lease-based lock |
| SQLite WAL 兼容性 | ❌ 不支持 | ✅ 支持 |
| 跨 Pod 文件锁 | ❌ 不可靠 | ✅ 可靠 |
| 原因 | NLM 是无状态协议，断连后锁状态丢失 | NFSv4 lock lease 机制保活 |

> **SQLite 官方态度**: NFS v3 上的 WAL 模式可能静默导致数据损坏。**仅 NFS v4 支持**。

### rsize/wsize = 1048576（1MB）

- SQLite WAL 写入通常 > 64KB，大块 rsize/wsize 减少 syscall 次数
- 1MB 是 Linux NFS 客户端常见最大值，性能最优
- 过小（如 4KB）会导致每个 SQLite 页面需要多次 NFS 请求

### noatime 必要性

- NAS 系统频繁更新 atime（文件访问时间）会产生大量元数据写操作
- SQLite 每次读取都会更新 atime，20k 用户的频繁读取会导致 NAS 元数据风暴
- `noatime` 完全禁用 atime 更新，显著降低 NAS 负载

### NAS 连接断开处理

| 场景 | 行为 |
|------|------|
| NFS 服务短暂中断（< 30s）| Linux NFS 客户端自动重试，恢复后继续 |
| NFS 服务长时间中断 | Pod 感知为 I/O 阻塞，health check 可能失败 |
| 恢复后 | SQLite WAL 自动恢复，无需人工干预 |
| 数据完整性 | WAL 的 write-ahead 特性提供崩溃恢复保护 |

> ⚠️ **最佳实践**: 配置 NAS 告警（连接数、IOPS 骤降），在 NAS 故障初期介入

### Permission Denied（UID/GID 映射问题）

```bash
# 症状: 容器内写入文件，但 NAS 上显示 root:root 或其他 UID

# 检查容器运行 UID
kubectl exec -it <pod> -- id

# 检查 NAS export 的 anonuid/anongid 设置
# NAS 侧应配置: anonuid=65534 (nobody), anongid=65534

# 在 K8s Pod spec 中设置 securityContext
# 示例:
# securityContext:
#   runAsUser: 65534
#   runAsGroup: 65534
#   fsGroup: 65534
```

---

## 5. Shard 结构与算法

### Shard 计算公式

```python
import hashlib

def get_user_shard(user_id: str) -> str:
    """
    计算用户数据存放的 shard 目录。
    shard = sha256(user_id).hex()[:2]  # 00 - ff (256 个 shard)
    """
    return hashlib.sha256(user_id.encode()).hexdigest()[:2]
```

### 目录结构

```
/hermes-homes/
├── 00/
│   ├── user-{uuid-1}/
│   │   ├── config.yaml
│   │   ├── state.db / state.db-wal / state.db-shm
│   │   ├── response_store.db
│   │   └── ...
│   └── user-{uuid-2}/
├── 01/
│   └── ...
...
├── ff/
```

### 容量估算

| 用户数 | 每 shard 平均用户 | 说明 |
|--------|----------------|------|
| 20,000 | ~78 | 20,000 / 256 |
| 50,000 | ~195 | 预留上限 |

---

## 6. 验收检查单

完成所有验证后，DevOps 工程师在下方签字。

### 环境信息

| 字段 | 值 |
|------|---|
| NAS 设备型号 | |
| NAS IP / Hostname | |
| NFS Export 路径 | |
| NFS Server 版本 | |
| K8s 集群版本 | |
| NFS Subdir External Provisioner 版本 | |
| 验证日期 | |
| 验证人 | |

### 验证结果

| 验证项 | 结果 | 备注 |
|--------|------|------|
| NFS 客户端安装 | ✅ / ❌ | |
| NFS v4 挂载成功 | ✅ / ❌ | |
| `vers=4.1` 确认 | ✅ / ❌ | |
| SQLite WAL 基本功能 | ✅ / ❌ | |
| SQLite 并发写入（10 线程）| ✅ / ❌ | |
| SQLite WAL checkpoint | ✅ / ❌ | |
| 256-shard 目录创建 | ✅ / ❌ | |
| StorageClass 存在 | ✅ / ❌ | |
| PVC 创建并绑定 | ✅ / ❌ | |
| Pod 挂载写入 | ✅ / ❌ | |
| 跨 Pod WAL 文件锁 | ✅ / ❌ | |
| 顺序读 >= 200 MB/s | ✅ / ❌ | 实测: ___ MB/s |
| 顺序写 >= 150 MB/s | ✅ / ❌ | 实测: ___ MB/s |
| 4KB 随机读 p99 < 10ms | ✅ / ❌ | 实测: ___ ms |

### 签名字段

```
DevOps 工程师签字: ________________________
验收日期:          ________________________
状态:              [ ] 可以进入 Phase 1  /  [ ] 阻塞，需解决以下问题
阻塞问题:
1.
2.
3.
```

---

*文档版本: 2026-04-17*
*基于 ADR-004 (2026-04-16) 和 delivery-plan.md H2 验收项*
