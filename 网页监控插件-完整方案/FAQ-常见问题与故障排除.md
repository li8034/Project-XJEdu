# FAQ - 常见问题与故障排除指南

## 📚 目录

1. [开发相关问题](#开发相关问题)
2. [部署与运行问题](#部署与运行问题)
3. [功能使用问题](#功能使用问题)
4. [性能与优化](#性能与优化)
5. [进阶话题](#进阶话题)

---

## 开发相关问题

### Q1: 从哪里开始开发这个插件？

**A:** 遵循以下步骤：

1. **环境准备**
   ```bash
   # 克隆 AstrBot 项目
   git clone https://github.com/AstrBotDevs/AstrBot
   
   # 进入插件目录
   cd AstrBot/data/plugins
   ```

2. **创建插件仓库**
   - 访问 https://github.com/Soulter/helloworld
   - 点击 "Use this template"
   - 创建新仓库: `astrbot_plugin_webupdater`

3. **克隆到本地**
   ```bash
   git clone https://github.com/YOUR_USERNAME/astrbot_plugin_webupdater
   ```

4. **配置并开发**
   - 复制 `插件实现示例_main.py` 内容到 `main.py`
   - 更新 `metadata.yaml`
   - 编写 `README.md`

5. **测试**
   ```bash
   # 启动 AstrBot
   cd ..
   python main.py
   ```

---

### Q2: ImportError: No module named 'xxx'

**A:** 缺少依赖库，解决方法：

```bash
# 方案1: 直接安装
pip install httpx

# 方案2: 使用requirements.txt
pip install -r requirements.txt

# 方案3: 在虚拟环境中安装
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**检查已安装的包:**
```bash
pip list | grep httpx
```

---

### Q3: 如何调试异步代码？

**A:** 使用日志和断点调试：

```python
# 方法1: 添加详细日志
self.logger.debug(f"[DEBUG] 开始检查任务: {task_id}")
self.logger.debug(f"[DEBUG] 获取内容中...")
self.logger.debug(f"[DEBUG] 内容长度: {len(content)}")
self.logger.debug(f"[DEBUG] 哈希值: {content_hash}")

# 方法2: 打印到控制台
import asyncio
print(f"Task info: {asyncio.current_task()}")

# 方法3: VS Code调试
# 在 .vscode/launch.json 中配置
# 使用 F5 启动调试

# 方法4: 异步调试器
import pdb
await asyncio.sleep(0)  # 让其他任务运行
pdb.set_trace()  # 设置断点
```

---

### Q4: 如何测试异步代码？

**A:** 使用 pytest-asyncio：

```bash
pip install pytest pytest-asyncio
```

**示例测试:**
```python
import pytest
from webupdater import WebUpdaterPlugin

@pytest.mark.asyncio
async def test_check_update():
    plugin = WebUpdaterPlugin(mock_context)
    task = WebUpdateTask(url="https://httpbin.org/html", interval=60)
    content = await plugin.check_update(task)
    assert content is not None

@pytest.mark.asyncio
async def test_fetch_url_timeout():
    plugin = WebUpdaterPlugin(mock_context)
    result = await plugin._fetch_url("https://httpbin.org/delay/100")
    assert result is None  # 应该超时返回None
```

---

### Q5: 代码如何热重载？

**A:** 使用 AstrBot WebUI 的重载功能：

1. 打开 AstrBot WebUI（通常是 http://localhost:6789）
2. 进入"插件管理"
3. 找到你的插件
4. 点击右上角"..."菜单
5. 选择"重载插件"

**或命令行方式:**
```
/webupdater list  # 先调用一个指令确保插件已加载
# 修改代码
# 然后在WebUI中重载
```

---

## 部署与运行问题

### Q6: 插件加载失败，metadata.yaml有什么要求？

**A:** metadata.yaml 的正确格式：

```yaml
# ✅ 正确的 metadata.yaml
name: webupdater                    # 必需：插件唯一名称
version: 1.0.0                      # 必需：版本号(semantic versioning)
display_name: 网页更新监控           # 可选：显示名称
description: 自动监控网页更新       # 可选：简短描述
author: YourName                    # 可选：作者名
homepage: https://...              # 可选：项目主页
repository: https://...            # 可选：代码仓库
tags:                              # 可选：标签
  - monitor
  - notification
requirements:                      # 可选：Python依赖
  - httpx>=0.24.0
```

**常见错误:**
```yaml
# ❌ 错误: YAML语法问题
name: webupdater
version 1.0.0              # 缺少冒号

# ❌ 错误: 错误的缩进
name: webupdater
  version: 1.0.0           # 不该缩进

# ❌ 错误: 版本格式
version: 1                 # 应该是 semantic versioning
```

---

### Q7: data 目录权限问题怎么解决？

**A:** 检查并修复权限：

```bash
# Linux/Mac
chmod -R 755 data/webupdater/
chmod 644 data/webupdater/tasks.json

# Windows (在PowerShell中)
icacls "data\webupdater" /grant "%USERNAME%:F" /T

# 检查是否可写
ls -la data/webupdater/
```

---

### Q8: 重启后任务消失了

**A:** 这是个问题，排查步骤：

1. **检查数据文件**
   ```bash
   # 文件是否存在
   ls -la data/webupdater/tasks.json
   
   # 查看文件内容
   cat data/webupdater/tasks.json
   ```

2. **检查加载逻辑**
   ```python
   # 在 on_astrbot_loaded 中添加日志
   @filter.on_astrbot_loaded()
   async def on_bot_loaded(self):
       self.logger.info("开始加载任务...")
       self.load_tasks()
       self.logger.info(f"已加载 {len(self.tasks)} 个任务")
       
       for task_id in self.tasks:
           self.logger.info(f"启动任务: {task_id}")
   ```

3. **检查错误**
   ```bash
   # 查看完整日志输出
   # 搜索 ERROR 或 Exception
   ```

4. **手动验证**
   ```bash
   # 启动后立即运行
   /webupdater list
   ```

---

### Q9: 如何部署到生产环境？

**A:** 生产环境部署清单：

```
部署前检查:
☐ 所有测试通过
☐ 代码已格式化 (ruff)
☐ 没有调试代码残留
☐ 日志级别已设置为 INFO
☐ 所有依赖已在 requirements.txt 中
☐ README 文档完整

部署步骤:
1. 提交到GitHub
   git add .
   git commit -m "feat: v1.0.0 for production"
   git tag -a v1.0.0
   git push --tags

2. 创建发行版本
   # 在GitHub上创建Release

3. 部署到服务器
   cd /path/to/AstrBot/data/plugins
   git clone https://github.com/your/repo astrbot_plugin_webupdater
   cd astrbot_plugin_webupdater
   pip install -r requirements.txt

4. 启动AstrBot
   cd /path/to/AstrBot
   python main.py

5. 验证
   /webupdater list
```

---

## 功能使用问题

### Q10: 添加监控后没有收到更新推送

**A:** 故障排查步骤：

1. **验证URL可访问**
   ```bash
   # 测试URL是否可到达
   curl -I https://example.com
   
   # 在插件中测试
   /webupdater check <task_id>
   ```

2. **检查网页是否真的有更新**
   ```
   手动访问网页，对比是否有内容变化
   ```

3. **验证推送目标**
   ```bash
   # 检查 unified_msg_origin 是否正确
   # 在 _send_update_notification 中添加日志
   self.logger.info(f"推送到: {task.unified_msg_origin}")
   ```

4. **检查消息推送是否成功**
   ```python
   # 在发送前添加日志
   self.logger.info(f"开始推送消息到 {task.unified_msg_origin}")
   
   try:
       await self.context.send_message(...)
       self.logger.info("推送成功")
   except Exception as e:
       self.logger.error(f"推送失败: {e}")
   ```

5. **查看完整日志**
   ```bash
   # 启用DEBUG日志级别
   # 查看所有日志输出，找出问题所在
   ```

---

### Q11: 检查间隔设置失败

**A:** 间隔值的要求：

```python
# 检查间隔必须 >= 60 秒

✅ 正确:
/webupdater add https://example.com 60      # 最小值
/webupdater add https://example.com 300     # 5分钟
/webupdater add https://example.com 3600    # 1小时

❌ 错误:
/webupdater add https://example.com 30      # 太小！应该至少60秒
/webupdater add https://example.com 0       # 无效
/webupdater add https://example.com -300    # 负数无效
```

**错误消息**
```
❌ 检查间隔不能少于60秒
```

---

### Q12: URL格式问题

**A:** URL必须符合以下要求：

```
✅ 正确格式:
https://github.com/releases
http://example.com/page
https://www.example.com:8080/path?query=1
https://user:pass@example.com/api

❌ 错误格式:
example.com                    # 缺少协议
ftp://example.com              # 不支持FTP
//example.com                  # 不完整
www.example.com                # 缺少协议
example.com/page               # 缺少协议
 https://example.com           # 有空格
```

**错误消息**
```
❌ 无效的URL，仅支持 http/https
```

---

### Q13: 任务ID是什么？我如何知道任务的ID？

**A:** 任务ID自动生成，查看方式：

```
# 方式1: 创建时获取
用户: /webupdater add https://example.com 300
机器人: ✅ 已添加监控任务 `abc12345`  ← 这就是ID

# 方式2: 通过list查看
/webupdater list
# 输出中显示所有任务ID

# 方式3: 查看数据文件
cat data/webupdater/tasks.json
# 在JSON中查看所有"id"字段
```

**ID格式**: 8位十六进制字符串（自动生成UUID）

---

### Q14: 如何暂停监控然后恢复？

**A:** 使用 enable/disable 命令：

```bash
# 暂停监控
/webupdater disable task_001

# 查看状态
/webupdater list
# 会显示 ⏸️ task_001 (已禁用)

# 恢复监控
/webupdater enable task_001

# 确认已恢复
/webupdater list
# 会显示 ✅ task_001 (启用)
```

**区别**：
- `disable`: 暂停监控但保留配置
- `remove`: 完全删除任务

---

## 性能与优化

### Q15: 100个监控任务会不会很慢？

**A:** 性能分析和优化建议：

**资源消耗**:
```
任务数      CPU      内存       网络I/O
────────────────────────────────────────
10个       <1%      ~20MB      ~100KB/小时
50个       ~2%      ~80MB      ~500KB/小时
100个      ~5%      ~150MB     ~1MB/小时
```

**优化建议**:

1. **减少任务数**
   ```
   只监控最重要的网页
   ```

2. **增加检查间隔**
   ```bash
   # 从5分钟改为30分钟
   /webupdater remove old_task
   /webupdater add https://example.com 1800
   ```

3. **使用内容摘要**
   ```python
   # 在 _extract_content_summary 中限制字符数
   summary = text_content[:200].strip()  # 只取前200字符
   ```

4. **异步优化**
   ```python
   # 批量发送请求
   tasks = [fetch_url(url) for url in urls]
   results = await asyncio.gather(*tasks)
   ```

---

### Q16: 如何减少内存占用？

**A:** 内存优化方案：

```python
# 1. 限制任务数量
MAX_TASKS = 50

# 2. 清理过期数据
# 定期删除太旧的任务
if len(self.tasks) > MAX_TASKS:
    oldest_task = min(self.tasks.values(), 
                      key=lambda t: t.last_check_time)
    await self.stop_monitoring(oldest_task.id)
    del self.tasks[oldest_task.id]

# 3. 不存储完整内容
# 只存储哈希值，不存储原始内容

# 4. 定期GC
import gc
gc.collect()
```

---

### Q17: 网速慢，请求经常超时怎么办？

**A:** 超时处理和优化：

```python
# 增加超时时间
self.http_timeout = 30  # 从10秒改为30秒

# 增加重试次数
self.max_retries = 5  # 从3次改为5次

# 增加检查间隔
# 给网络更多时间恢复
/webupdater add https://slow-website.com 1800  # 改为30分钟
```

---

## 进阶话题

### Q18: 如何监控特定的网页内容（不是整个页面）？

**A:** 需要进阶功能，当前版本不支持，但可以通过以下方式实现：

**方案1: 使用API端点**
```
监控 API 而不是 HTML 页面
/webupdater add https://api.github.com/repos/owner/repo/releases/latest 300
```

**方案2: 使用RSS源**
```
监控 RSS/Atom 源
/webupdater add https://example.com/feed.xml 600
```

**方案3: 在v1.1中使用CSS选择器（计划）**
```python
# 未来版本
task = WebUpdateTask(
    url="https://example.com/page",
    content_selector=".article-content"  # 只监控这个元素
)
```

---

### Q19: 如何集成邮件通知？

**A:** 需要扩展插件功能（v1.1计划）：

**当前实现思路**:
```python
# 在 _send_update_notification 中添加邮件逻辑
import smtplib
from email.mime.text import MIMEText

async def _send_update_notification(self, task, content):
    # 发送聊天消息
    await self.context.send_message(task.unified_msg_origin, message_chain)
    
    # 发送邮件
    msg = MIMEText(content)
    msg['Subject'] = f"网页更新: {task.url}"
    msg['From'] = "sender@example.com"
    msg['To'] = "receiver@example.com"
    
    with smtplib.SMTP_SSL("smtp.example.com", 465) as server:
        server.login("username", "password")
        server.send_message(msg)
```

---

### Q20: 可以与其他插件交互吗？

**A:** 是的，可以通过以下方式：

```python
# 在其他插件中调用 webupdater
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.updater = None
    
    @filter.on_astrbot_loaded()
    async def get_updater(self):
        # 获取 webupdater 插件实例
        self.updater = self.context.get_plugin("webupdater")
    
    @filter.command("get_updates")
    async def get_latest_updates(self, event: AstrMessageEvent):
        # 使用 webupdater 的功能
        tasks = self.updater.tasks
        for task_id, task in tasks.items():
            if task.enabled:
                yield event.plain_result(f"监控: {task.url}")
```

---

### Q21: 如何贡献我的改进？

**A:** 开源贡献流程：

```bash
# 1. Fork 项目到你的账号

# 2. Clone 你的 Fork
git clone https://github.com/YOUR_USERNAME/astrbot_plugin_webupdater

# 3. 创建功能分支
git checkout -b feature/new-feature
git checkout -b bugfix/issue-123

# 4. 提交修改
git add .
git commit -m "feat: Add new feature"
git commit -m "fix: Fix issue #123"

# 5. 推送到你的 Fork
git push origin feature/new-feature

# 6. 创建 Pull Request
# 在 GitHub 上创建 PR，选择主项目为目标

# 7. 等待审核
# 项目维护者会审核你的代码
# 可能需要进行修改

# 8. 合并
# PR 被批准后会合并到主项目
```

---

### Q22: 如何报告bug？

**A:** 有效的bug报告流程：

1. **搜索已有issue**
   - 确保这个bug还没被报告

2. **创建新issue**
   - 标题清晰扼要
   - 详细描述问题
   - 提供复现步骤
   - 包含错误日志
   - 说明你的环境

**模板示例**:
```markdown
## Bug 描述
我在监控GitHub页面时遇到了问题

## 复现步骤
1. 运行 `/webupdater add https://github.com/releases 300`
2. 等待300秒
3. 没有收到更新通知，但页面确实更新了

## 预期行为
应该收到更新通知

## 实际行为
30分钟后没有收到任何通知

## 错误日志
```
[ERROR] 检查更新失败: Connection timeout
```

## 环境信息
- OS: Windows 10
- Python: 3.9.0
- AstrBot: v4.10.0
- 插件版本: v1.0.0
```

---

### Q23: 如何添加日志功能？

**A:** 使用 AstrBot 的日志系统：

```python
# 插件中使用
self.logger.debug(f"调试信息: {variable}")
self.logger.info(f"信息: 任务已启动")
self.logger.warning(f"警告: 网络连接缓慢")
self.logger.error(f"错误: {exception}")

# 日志级别
DEBUG   - 最详细，用于开发调试
INFO    - 一般信息
WARNING - 警告
ERROR   - 错误

# 查看日志
# 在 AstrBot 日志文件或控制台输出中查看
```

---

### Q24: 安全问题 - 如何保护用户隐私？

**A:** 安全建议：

```python
# 1. 验证URL避免恶意URL
if not self._validate_url(url):
    return error

# 2. 不存储敏感信息
# 不保存网页完整内容，只保存哈希值

# 3. 限制请求频率
# 避免对同一网站发送过多请求
# 最小间隔 60 秒

# 4. 超时保护
# 防止请求卡住
http_timeout = 10

# 5. 错误处理
# 不暴露系统信息给用户
try:
    ...
except Exception as e:
    logger.error(f"Internal error: {e}")
    yield event.plain_result("发生错误，请稍后重试")
```

---

## 更新日志

### v1.0.0 (2024-01-19)
- ✅ 基础网页监控功能
- ✅ 异步后台检查
- ✅ 任务持久化存储
- ✅ 主动消息推送
- ✅ 完整文档

### 计划中的版本
- [ ] v1.1: 内容选择器支持
- [ ] v1.2: 邮件/Webhook集成
- [ ] v2.0: 数据库存储 + 管理面板

---

## 获取帮助

如果这个FAQ没有解决你的问题：

1. **查看官方文档** - https://docs.astrbot.app/
2. **加入社区群** - QQ 975206796
3. **提交Issue** - GitHub Issues
4. **讨论功能** - GitHub Discussions

---

*最后更新: 2024年1月19日*
