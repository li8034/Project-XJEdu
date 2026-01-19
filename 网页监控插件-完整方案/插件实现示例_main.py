"""
网页更新推送机器人插件 - 完整实现示例
一个用于自动监控网页更新并主动推送通知的AstrBot插件
"""

import asyncio
import hashlib
import json
import os
from datetime import datetime
from typing import Dict, Optional, List
import uuid

from astrbot.api.star import Context, Star, register
from astrbot.api.event import filter, AstrMessageEvent
import astrbot.api.message_components as Comp
from astrbot.api.message import MessageChain

import httpx


# ============================================================================
# 数据模型
# ============================================================================

class WebUpdateTask:
    """网页监控任务的数据模型"""
    
    def __init__(
        self,
        url: str,
        interval: int = 300,
        task_id: Optional[str] = None,
        enabled: bool = True,
        unified_msg_origin: str = "",
        last_hash: str = "",
        last_check_time: int = 0,
        created_time: int = 0
    ):
        self.id = task_id or str(uuid.uuid4())[:8]
        self.url = url
        self.interval = interval
        self.enabled = enabled
        self.unified_msg_origin = unified_msg_origin
        self.last_hash = last_hash
        self.last_check_time = last_check_time
        self.created_time = created_time or int(datetime.now().timestamp())
    
    def to_dict(self) -> dict:
        """序列化为字典"""
        return {
            "id": self.id,
            "url": self.url,
            "interval": self.interval,
            "enabled": self.enabled,
            "unified_msg_origin": self.unified_msg_origin,
            "last_hash": self.last_hash,
            "last_check_time": self.last_check_time,
            "created_time": self.created_time,
        }
    
    @staticmethod
    def from_dict(data: dict) -> "WebUpdateTask":
        """从字典反序列化"""
        return WebUpdateTask(
            url=data.get("url"),
            interval=data.get("interval", 300),
            task_id=data.get("id"),
            enabled=data.get("enabled", True),
            unified_msg_origin=data.get("unified_msg_origin", ""),
            last_hash=data.get("last_hash", ""),
            last_check_time=data.get("last_check_time", 0),
            created_time=data.get("created_time", 0),
        )


# ============================================================================
# 插件主类
# ============================================================================

@register(
    "webupdater",
    "YourName",
    "网页自动更新监控与推送插件",
    "1.0.0"
)
class WebUpdaterPlugin(Star):
    """网页更新监控插件的主类"""
    
    def __init__(self, context: Context):
        super().__init__(context)
        
        # 任务存储
        self.tasks: Dict[str, WebUpdateTask] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}
        
        # 数据持久化路径
        self.storage_dir = os.path.join(
            self.context.data_dir,
            "webupdater"
        )
        os.makedirs(self.storage_dir, exist_ok=True)
        self.tasks_file = os.path.join(self.storage_dir, "tasks.json")
        
        # HTTP客户端配置
        self.http_timeout = 10
        self.max_retries = 3
    
    # ========================================================================
    # 生命周期方法
    # ========================================================================
    
    @filter.on_astrbot_loaded()
    async def on_bot_loaded(self):
        """AstrBot启动时加载所有任务并启动监控"""
        self.logger.info("网页监控插件已加载")
        
        # 加载已保存的任务
        self.load_tasks()
        
        # 启动所有启用的监控任务
        for task_id, task in self.tasks.items():
            if task.enabled:
                await self.start_monitoring(task_id)
                self.logger.info(f"已启动监控任务: {task_id} ({task.url})")
    
    # ========================================================================
    # 指令处理
    # ========================================================================
    
    @filter.command_group("webupdater")
    def webupdater_group(self):
        """网页监控指令组"""
        pass
    
    @webupdater_group.command("add")
    async def cmd_add_monitor(
        self,
        event: AstrMessageEvent,
        url: str,
        interval: int = 300
    ):
        """添加新的网页监控任务
        
        参数:
        - url: 要监控的网页URL
        - interval: 检查间隔（默认300秒）
        """
        try:
            # 验证URL
            if not self._validate_url(url):
                yield event.plain_result("❌ 无效的URL，仅支持 http/https")
                return
            
            # 验证间隔
            if interval < 60:
                yield event.plain_result("❌ 检查间隔不能少于60秒")
                return
            
            # 创建任务
            task = WebUpdateTask(
                url=url,
                interval=interval,
                unified_msg_origin=event.unified_msg_origin
            )
            
            # 保存任务
            self.tasks[task.id] = task
            self.save_tasks()
            
            # 启动监控
            await self.start_monitoring(task.id)
            
            yield event.plain_result(
                f"✅ 已添加监控任务 `{task.id}`\n"
                f"📍 URL: {url}\n"
                f"⏱️ 检查间隔: {interval}秒"
            )
            
            self.logger.info(f"添加监控任务: {task.id} ({url})")
            
        except Exception as e:
            self.logger.error(f"添加监控失败: {e}")
            yield event.plain_result(f"❌ 添加失败: {str(e)}")
    
    @webupdater_group.command("list")
    async def cmd_list_monitors(self, event: AstrMessageEvent):
        """查看所有监控任务"""
        try:
            if not self.tasks:
                yield event.plain_result("📋 暂无监控任务")
                return
            
            # 构建消息
            chain = [Comp.Plain("📋 网页监控任务列表\n━━━━━━━━━━━━━━━━\n")]
            
            for task_id, task in self.tasks.items():
                status = "✅" if task.enabled else "⏸️"
                
                # 计算下次检查时间
                if task.enabled:
                    next_check = task.last_check_time + task.interval
                    next_check_time = datetime.fromtimestamp(next_check).strftime("%H:%M:%S")
                    check_info = f"下次检查: {next_check_time}\n"
                else:
                    check_info = "状态: 已禁用\n"
                
                task_info = (
                    f"\n{status} 任务ID: {task_id}\n"
                    f"   URL: {task.url}\n"
                    f"   检查间隔: {task.interval}秒\n"
                    f"   {check_info}"
                )
                
                chain.append(Comp.Plain(task_info))
            
            yield event.chain_result(chain)
            
        except Exception as e:
            self.logger.error(f"列表任务失败: {e}")
            yield event.plain_result(f"❌ 获取失败: {str(e)}")
    
    @webupdater_group.command("remove")
    async def cmd_remove_monitor(self, event: AstrMessageEvent, task_id: str):
        """删除监控任务"""
        try:
            if task_id not in self.tasks:
                yield event.plain_result(f"❌ 任务不存在: {task_id}")
                return
            
            # 停止运行中的任务
            await self.stop_monitoring(task_id)
            
            # 删除任务
            task = self.tasks.pop(task_id)
            self.save_tasks()
            
            yield event.plain_result(f"✅ 已删除任务 `{task_id}`")
            self.logger.info(f"删除监控任务: {task_id}")
            
        except Exception as e:
            self.logger.error(f"删除任务失败: {e}")
            yield event.plain_result(f"❌ 删除失败: {str(e)}")
    
    @webupdater_group.command("enable")
    async def cmd_enable_monitor(self, event: AstrMessageEvent, task_id: str):
        """启用监控任务"""
        try:
            if task_id not in self.tasks:
                yield event.plain_result(f"❌ 任务不存在: {task_id}")
                return
            
            task = self.tasks[task_id]
            if task.enabled:
                yield event.plain_result(f"⏸️ 任务 `{task_id}` 已处于启用状态")
                return
            
            # 启用任务
            task.enabled = True
            self.save_tasks()
            
            # 启动异步监控
            await self.start_monitoring(task_id)
            
            yield event.plain_result(f"✅ 已启用任务 `{task_id}`")
            self.logger.info(f"启用监控任务: {task_id}")
            
        except Exception as e:
            self.logger.error(f"启用任务失败: {e}")
            yield event.plain_result(f"❌ 启用失败: {str(e)}")
    
    @webupdater_group.command("disable")
    async def cmd_disable_monitor(self, event: AstrMessageEvent, task_id: str):
        """禁用监控任务"""
        try:
            if task_id not in self.tasks:
                yield event.plain_result(f"❌ 任务不存在: {task_id}")
                return
            
            task = self.tasks[task_id]
            if not task.enabled:
                yield event.plain_result(f"⏸️ 任务 `{task_id}` 已处于禁用状态")
                return
            
            # 禁用任务
            task.enabled = False
            self.save_tasks()
            
            # 停止异步监控
            await self.stop_monitoring(task_id)
            
            yield event.plain_result(f"⏸️ 已禁用任务 `{task_id}`")
            self.logger.info(f"禁用监控任务: {task_id}")
            
        except Exception as e:
            self.logger.error(f"禁用任务失败: {e}")
            yield event.plain_result(f"❌ 禁用失败: {str(e)}")
    
    @webupdater_group.command("check")
    async def cmd_check_now(self, event: AstrMessageEvent, task_id: str):
        """立即检查指定任务"""
        try:
            if task_id not in self.tasks:
                yield event.plain_result(f"❌ 任务不存在: {task_id}")
                return
            
            task = self.tasks[task_id]
            
            yield event.plain_result(f"🔍 正在检查任务 `{task_id}`...")
            
            # 执行检查
            content = await self.check_update(task)
            
            if content:
                yield event.plain_result(f"✅ 检测到更新！\n{content}")
            else:
                yield event.plain_result("✔️ 暂无更新")
            
        except Exception as e:
            self.logger.error(f"检查任务失败: {e}")
            yield event.plain_result(f"❌ 检查失败: {str(e)}")
    
    # ========================================================================
    # 核心监控逻辑
    # ========================================================================
    
    async def start_monitoring(self, task_id: str):
        """启动单个任务的监控"""
        if task_id in self.running_tasks:
            return
        
        task = asyncio.create_task(self._monitoring_loop(task_id))
        self.running_tasks[task_id] = task
    
    async def stop_monitoring(self, task_id: str):
        """停止单个任务的监控"""
        if task_id not in self.running_tasks:
            return
        
        task = self.running_tasks.pop(task_id)
        task.cancel()
        
        try:
            await task
        except asyncio.CancelledError:
            pass
    
    async def _monitoring_loop(self, task_id: str):
        """后台监控循环"""
        task = self.tasks[task_id]
        
        while True:
            try:
                if not task.enabled:
                    await asyncio.sleep(10)
                    continue
                
                # 检查更新
                content = await self.check_update(task)
                
                # 如果有更新，发送推送
                if content:
                    await self._send_update_notification(task, content)
                
                # 等待下一次检查
                await asyncio.sleep(task.interval)
                
            except asyncio.CancelledError:
                self.logger.info(f"监控任务已停止: {task_id}")
                break
            except Exception as e:
                self.logger.error(f"监控异常 [{task_id}]: {e}")
                await asyncio.sleep(60)  # 异常时等待60秒后重试
    
    async def check_update(self, task: WebUpdateTask) -> Optional[str]:
        """检查网页是否更新"""
        try:
            # 获取网页内容
            content = await self._fetch_url(task.url)
            if not content:
                return None
            
            # 计算哈希值
            content_hash = self._calculate_hash(content)
            
            # 对比是否有更新
            if task.last_hash and task.last_hash == content_hash:
                return None
            
            # 更新记录
            task.last_hash = content_hash
            task.last_check_time = int(datetime.now().timestamp())
            self.save_tasks()
            
            # 返回新内容摘要
            return self._extract_content_summary(content)
            
        except Exception as e:
            self.logger.error(f"检查更新失败 [{task.id}]: {e}")
            return None
    
    async def _fetch_url(self, url: str) -> Optional[str]:
        """获取URL内容"""
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        url,
                        timeout=self.http_timeout,
                        follow_redirects=True
                    )
                    
                    if response.status_code == 200:
                        return response.text
                    else:
                        self.logger.warning(
                            f"获取URL失败 [{url}]: "
                            f"状态码 {response.status_code}"
                        )
                        return None
                        
            except httpx.TimeoutException:
                self.logger.warning(f"请求超时 [{url}]，正在重试 ({attempt + 1}/{self.max_retries})")
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2)
            except Exception as e:
                self.logger.error(f"获取URL异常 [{url}]: {e}")
                return None
        
        return None
    
    @staticmethod
    def _calculate_hash(content: str) -> str:
        """计算内容的SHA256哈希值"""
        return hashlib.sha256(content.encode()).hexdigest()
    
    @staticmethod
    def _extract_content_summary(html: str) -> str:
        """从HTML提取内容摘要"""
        # 简单实现：提取标题和前200个字符
        # 实际应用可以使用BeautifulSoup库进行更精确的提取
        
        # 尝试提取title
        import re
        title_match = re.search(r'<title>([^<]+)</title>', html, re.IGNORECASE)
        title = title_match.group(1) if title_match else "（无标题）"
        
        # 提取前文本（移除HTML标签）
        text_content = re.sub(r'<[^>]+>', '', html)
        summary = text_content[:200].strip()
        
        return f"📝 标题: {title}\n📄 摘要: {summary}..."
    
    async def _send_update_notification(self, task: WebUpdateTask, content: str):
        """发送更新推送通知"""
        try:
            # 构建消息
            chain = [
                Comp.Plain(
                    f"📢 检测到网页更新！\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"🔗 URL: {task.url}\n"
                    f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"{content}"
                )
            ]
            
            # 使用主动推送发送消息
            await self.context.send_message(task.unified_msg_origin, MessageChain(chain))
            
            self.logger.info(f"已发送更新推送: {task.id}")
            
        except Exception as e:
            self.logger.error(f"发送推送失败: {e}")
    
    # ========================================================================
    # 工具方法
    # ========================================================================
    
    @staticmethod
    def _validate_url(url: str) -> bool:
        """验证URL的有效性"""
        return url.startswith("http://") or url.startswith("https://")
    
    def load_tasks(self):
        """从文件加载任务配置"""
        try:
            if not os.path.exists(self.tasks_file):
                self.tasks = {}
                return
            
            with open(self.tasks_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            self.tasks = {}
            for task_data in data.get("tasks", []):
                task = WebUpdateTask.from_dict(task_data)
                self.tasks[task.id] = task
            
            self.logger.info(f"已加载 {len(self.tasks)} 个监控任务")
            
        except Exception as e:
            self.logger.error(f"加载任务配置失败: {e}")
            self.tasks = {}
    
    def save_tasks(self):
        """保存任务配置到文件"""
        try:
            data = {
                "tasks": [task.to_dict() for task in self.tasks.values()]
            }
            
            with open(self.tasks_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
        except Exception as e:
            self.logger.error(f"保存任务配置失败: {e}")
