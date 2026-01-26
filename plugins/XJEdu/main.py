import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

try:
    from bs4 import BeautifulSoup  # 已在 AstrBot 依赖中
except Exception:  # pragma: no cover
    BeautifulSoup = None

try:
    import aiohttp  # 已在 AstrBot 依赖中
except Exception:  # pragma: no cover
    aiohttp = None

try:
    from playwright.async_api import async_playwright  # 可选依赖，用于绕过动态挑战
except Exception:  # pragma: no cover
    async_playwright = None


DUE_LIST_URL = "https://due.xjtu.edu.cn/jxxx/jxtz2.htm"
DUE_LIST_EXTRA = [
    "https://due.xjtu.edu.cn/jxxx/jxtz2/jsap.htm",  # 竞赛安排子栏目
    "https://due.xjtu.edu.cn/jxxx/jxtz2/jsdc.htm",  # 竞赛大创子栏目
]
STORE_PATH = os.path.join(os.path.dirname(__file__), "competitions_store.json")


def _now() -> datetime:
    return datetime.now()


def _parse_date(date_str: str) -> Optional[datetime]:
    date_str = date_str.strip()
    date_str = date_str.replace("—", "-").replace("–", "-").replace("至", "-").replace("~", "-").replace("～", "-")
    patterns = [
        "%Y年%m月%d日",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
    ]
    for p in patterns:
        try:
            return datetime.strptime(date_str, p)
        except Exception:
            pass
    # 中文带时分的简单处理
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if m:
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return datetime(y, mo, d)
        except Exception:
            return None
    m2 = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", date_str)
    if m2:
        try:
            y, mo, d = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
            return datetime(y, mo, d)
        except Exception:
            return None
    return None


def _extract_qq_group(text: str) -> Optional[str]:
    patterns = [
        r"QQ群[号]?[：: ]?(\d{5,12})",
        r"QQ[：: ]?(\d{5,12})",
        r"群号[：: ]?(\d{5,12})",
    ]
    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def _is_registration(title: str, body: str) -> bool:
    kw = [
        "报名", "报名通知", "报名开始", "报名截止", "报名链接", "参赛", "竞赛报名",
        "竞赛安排", "赛事安排", "竞赛通知"
    ]
    text = f"{title}\n{body}"
    return any(k in text for k in kw)


def _extract_time_window(body: str) -> Dict[str, Optional[datetime]]:
    res: Dict[str, Optional[datetime]] = {"start": None, "end": None}
    range_pat = re.search(r"(\d{4}[年./-]\d{1,2}[月./-]\d{1,2})\s*[—–\-~～至到]{1,2}\s*(\d{4}[年./-]\d{1,2}[月./-]\d{1,2})", body)
    if range_pat:
        s_dt = _parse_date(range_pat.group(1))
        e_dt = _parse_date(range_pat.group(2))
        if s_dt:
            res["start"] = s_dt
        if e_dt:
            res["end"] = e_dt
    # 尝试从“开始时间/截止时间/报名时间”行中提取
    pairs = [
        (r"开始(?:时间|日期)[：: ]*(.+)", "start"),
        (r"截止(?:时间|日期)[：: ]*(.+)", "end"),
        (r"报名(?:开始)?(?:时间|日期)[：: ]*(.+)", "start"),
        (r"报名截止(?:时间|日期)?[：: ]*(.+)", "end"),
    ]
    for pat, key in pairs:
        m = re.search(pat, body)
        if m:
            dt = _parse_date(m.group(1))
            if dt:
                res[key] = dt

    # 若无行匹配，尝试抓取段落中的两个日期，以第一个当 start，最后一个当 end
    dates = re.findall(r"\d{4}[./-]\d{1,2}[./-]\d{1,2}|\d{4}年\d{1,2}月\d{1,2}日", body)
    parsed = [d for d in (_parse_date(s) for s in dates) if d]
    if parsed:
        parsed.sort()
        if res["start"] is None:
            res["start"] = parsed[0]
        if res["end"] is None:
            res["end"] = parsed[-1]
    return res


@register("xjedu_competition", "U_Miyako", "西交教务竞赛监控与推送", "0.1.0")
class XJEduPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._running = True
        self._check_task: Optional[asyncio.Task] = None
        self._remind_task: Optional[asyncio.Task] = None
        self.ai_conf: Dict[str, Any] = {}
        self.store_loaded = False
        self._challenge_warned = False
        self._render_dumped = False

    def _persona_wrap(self, text: str) -> str:
        """将输出文本按内向猫娘口癖进行包装，仅影响聊天输出，不改动日志与文件。"""
        lines = (text or "").splitlines()
        wrapped: List[str] = []
        for ln in lines:
            s = ln.rstrip()
            if not s:
                wrapped.append(ln)
                continue
            # 已带有口癖则不重复追加
            if s.endswith("喵～") or s.endswith("喵~"):
                wrapped.append(s)
            else:
                wrapped.append(s + "喵～")
        return "\n".join(wrapped)

    async def initialize(self):
        # 读取 AI 配置
        await self._load_ai_config()
        # 启动时输出解释器与 Playwright 状态，方便排查运行环境
        # 初始化 AI 开关（KV 未设定则采用配置默认值）
        if (await self.get_kv_data("ai_use", None)) is None:
            await self._save_kv("ai_use", bool(self.ai_conf.get("use_ai", False)))
        # 先尝试从外置文件恢复历史知识库，减少二次拉取；初始化同步改为手动指令触发
        await self._load_store_file()
        # 启动定时任务：每30分钟拉取一次；每日提醒一次
        self._check_task = asyncio.create_task(self._periodic_check_loop(interval_sec=1800))
        self._remind_task = asyncio.create_task(self._daily_deadline_remind_loop(hour=9))
        # 启动时不做任何抓取，仅加载本地文件与启动任务
        logger.info("[XJEdu] 竞赛监控插件已启动")

    async def terminate(self):
        self._running = False
        for t in [self._check_task, self._remind_task]:
            if t and not t.done():
                t.cancel()
        logger.info("[XJEdu] 竞赛监控插件已停止")

    async def _stop_check_task(self):
        # 仅停止当前正在运行的检查任务，不影响后续定时调度
        if self._check_task and not self._check_task.done():
            self._check_task.cancel()
            self._check_task = None
            logger.info("[XJEdu] 已停止当前检查任务")
        else:
            logger.info("[XJEdu] 当前无正在执行的检查任务")

    async def _load_ai_config(self):
        try:
            # 独立配置文件：plugins/XJEdu/config_ai.json
            conf_path = os.path.join(os.path.dirname(__file__), "config_ai.json")
            if os.path.exists(conf_path):
                with open(conf_path, "r", encoding="utf-8") as f:
                    self.ai_conf = json.load(f)
            else:
                self.ai_conf = {
                    "use_ai": True,
                    "provider": "deepseek",
                    "base_url": "https://api.deepseek.com",
                    "api_key": "",
                    "model": "deepseek-chat",
                }
        except Exception as e:
            logger.warning(f"[XJEdu] 读取AI配置失败: {e}")
            self.ai_conf = {"use_ai": True}

    async def _get_kv(self, key: str, default: Any):
        v = await self.get_kv_data(key, default)
        return v if v is not None else default

    async def _save_kv(self, key: str, value: Any):
        await self.put_kv_data(key, value)

    async def _is_ai_enabled(self) -> bool:
        flag = await self._get_kv("ai_use", None)
        if flag is None:
            return bool(self.ai_conf.get("use_ai", False))
        return bool(flag)

    async def _ai_extract_competition(self, title: str, body: str, raw_html: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not await self._is_ai_enabled():
            return None
        if not aiohttp:
            logger.warning("[XJEdu] AI 解析需要 aiohttp，可选安装后再试")
            return None
        api_key = (self.ai_conf or {}).get("api_key")
        if not api_key:
            logger.warning("[XJEdu] AI 解析未配置 api_key，已跳过")
            return None
        base_url = (self.ai_conf or {}).get("base_url", "https://api.deepseek.com").rstrip("/")
        model = (self.ai_conf or {}).get("model", "deepseek-chat")
        url = f"{base_url}/chat/completions"
        prompt_text = (
            "请严格按以下要求提取：\n"
            "- 判断是否为竞赛报名/参赛通知；\n"
            "- 仅当为报名/参赛通知时，提取竞赛报名开始日期、报名截止日期；\n"
            "- 输出严格 JSON：{\"is_registration\": bool, \"start_date\": 日期或null, \"end_date\": 日期或null}；\n"
            "- 日期格式 YYYY-MM-DD；\n"
            "- 若非报名通知，则 is_registration=false 且 start_date/end_date 为 null；\n"
            "- 只取报名时间，忽略举办/开赛/活动/评审/答辩/培训/讲座/作品提交等非报名时间；\n"
            "- 如仅出现单一日期或无法确定，缺失字段填 null；\n"
            "- 不要输出多余文字，不要代码块。"
        )
        # 若检测到动态验证页面，避免将其发给 AI
        if raw_html and ("dynamic_challenge" in raw_html or "安全检查" in raw_html):
            raw_html = None
        # 优先使用整页 HTML（不截断），并落盘供检查；无 HTML 时退回正文片段
        if raw_html:
            lines = [f"标题：{title}"]
            lines.append("网页HTML全文（未截断）：")
            lines.append(raw_html)
            user_content = "\n".join([prompt_text] + lines)
            dump_path = os.path.join(os.path.dirname(__file__), "ai_input_last.html")
            try:
                with open(dump_path, "w", encoding="utf-8", errors="ignore") as f:
                    f.write(raw_html)
            except Exception as dump_err:
                logger.warning(f"[XJEdu] 保存 AI 输入HTML失败: {dump_err}")
        else:
            try:
                snippet = self._extract_relevant_snippet(body)
                lines = [f"标题：{title}"]
                lines.append("正文片段（纯文本）：")
                lines.append(snippet)
                user_content = "\n".join([prompt_text] + lines)
            except Exception:
                user_content = f"{prompt_text}\n标题：{title}\n正文（纯文本）：\n{body[:4000]}"
        # 保存发送给 AI 的原文，并在日志中提示路径
        input_path = os.path.join(os.path.dirname(__file__), "ai_input_last.txt")
        try:
            with open(input_path, "w", encoding="utf-8", errors="ignore") as f:
                f.write(user_content)
            logger.warning(f"[XJEdu] AI 输入已保存 {input_path}")
        except Exception as dump_err:
            logger.warning(f"[XJEdu] 保存 AI 输入失败: {dump_err}")
        payload = {
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": "你是信息抽取助手，严格按用户消息中的要求输出 JSON。"},
                {"role": "user", "content": user_content},
            ],
        }
        # 对 deepseek-reasoner 添加推理参数（兼容性安全）
        try:
            if isinstance(model, str) and "reasoner" in model:
                payload["reasoning"] = {"effort": "medium"}
        except Exception:
            pass
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with aiohttp.ClientSession(headers=headers) as sess:
                async with sess.post(url, json=payload, timeout=60) as resp:
                    if resp.status != 200:
                        try:
                            resp_text = await resp.text(errors="ignore")
                        except Exception:
                            resp_text = ""
                        logger.warning(f"[XJEdu] AI 解析失败 status={resp.status} url={url} resp={resp_text[:300]}")
                        return None
                    data = await resp.json()
            content = (((data.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
            # 调试阶段：保存与输出原始回复
            debug_path = os.path.join(os.path.dirname(__file__), "ai_last_response.json")
            try:
                existing: List[Dict[str, Any]] = []
                if os.path.exists(debug_path):
                    try:
                        with open(debug_path, "r", encoding="utf-8") as rf:
                            existing_data = json.load(rf)
                            if isinstance(existing_data, list):
                                existing = existing_data
                    except Exception:
                        existing = []
                existing.append({
                    "title": title,
                    "preview_body": body[:500],
                    "raw": content,
                    "api": {"base_url": base_url, "model": model},
                    "created_at": _now().isoformat(),
                })
                with open(debug_path, "w", encoding="utf-8") as f:
                    json.dump(existing[-200:], f, ensure_ascii=False, indent=2)
            except Exception as werr:
                logger.warning(f"[XJEdu] 写入 AI 调试文件失败: {werr}")
            # 尝试解析 JSON
            try:
                import json as _json

                text = content.strip()
                # 截取可能的代码块
                if text.startswith("```"):
                    text = text.strip("`")
                    text = text.split("\n", 1)[-1]
                parsed = _json.loads(text)
            except Exception:
                logger.warning(f"[XJEdu] AI 返回无法解析，内容={content[:200]}")
                return None
            return parsed if isinstance(parsed, dict) else None
        except Exception as e:
            logger.warning(f"[XJEdu] AI 请求异常: {type(e).__name__}: {e}")
            return None

    async def _load_store_file(self):
        if self.store_loaded:
            return
        if not os.path.exists(STORE_PATH):
            self.store_loaded = True
            return
        try:
            with open(STORE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            last_ids = data.get("last_seen_ids", [])
            kb = data.get("competitions", [])
            if last_ids:
                await self._save_kv("last_seen_ids", last_ids)
            if kb:
                await self._save_kv("competitions", kb)
            self.store_loaded = True
            logger.info("[XJEdu] 已从外置文件加载历史竞赛数据")
        except Exception as e:
            logger.warning(f"[XJEdu] 读取外置存储失败: {e}")
            self.store_loaded = True

    async def _save_store_file(self):
        try:
            data = {
                "last_seen_ids": await self._get_kv("last_seen_ids", []),
                "competitions": await self._get_kv("competitions", []),
                "errors": await self._get_kv("errors", []),
            }
            with open(STORE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[XJEdu] 写入外置存储失败: {e}")

    async def _initial_sync(self):
        try:
            items = await self._fetch_competition_list()
            if not items:
                return
            last_ids: List[str] = await self._get_kv("last_seen_ids", [])
            kb: List[Dict[str, Any]] = await self._get_kv("competitions", [])
            updated = False
            for it in items:
                if it["id"] in last_ids:
                    continue
                detail = await self._fetch_detail(it.get("url", "")) if it.get("url") else {}
                title = it.get("title", "")
                body = detail.get("body", "")
                raw_html = detail.get("html", "")
                ai_res = await self._ai_extract_competition(title, body, raw_html)
                if not ai_res:
                    continue
                is_reg = bool(ai_res.get("is_registration", False))
                tw_start = _parse_date(ai_res.get("start_date")) if ai_res.get("start_date") else None
                tw_end = _parse_date(ai_res.get("end_date")) if ai_res.get("end_date") else None
                tw = {"start": tw_start, "end": tw_end}
                qq = _extract_qq_group(body)
                # 仅在正文包含“即日起”等描述时，使用列表日期作为报名开始时间
                if is_reg and (tw.get("start") is None) and ("即日起" in body):
                    hint_dt = _parse_date(it.get("post_time") or "")
                    if hint_dt:
                        tw["start"] = hint_dt
                comp = {
                    "id": it["id"],
                    "title": title,
                    "url": it.get("url"),
                    "post_time": it.get("post_time"),
                    "is_registration": is_reg,
                    "start_date": tw["start"].isoformat() if tw["start"] else None,
                    "end_date": tw["end"].isoformat() if tw["end"] else None,
                    "qq_group": qq,
                    "created_at": _now().isoformat(),
                    "last_remind": None,
                }
                # 错误目录：若为报名但开始与截止日期相同或截止早于开始，计入错误目录
                try:
                    errors: List[Dict[str, Any]] = await self._get_kv("errors", [])
                    sd = comp.get("start_date")
                    ed = comp.get("end_date")
                    def _d(s: Optional[str]) -> Optional[datetime]:
                        try:
                            return datetime.fromisoformat(s) if s else None
                        except Exception:
                            return None
                    sdt = _d(sd)
                    edt = _d(ed)
                    same_day = (sd and ed and sd[:10] == ed[:10])
                    end_before_start = (sdt and edt and edt < sdt)
                    if comp.get("is_registration") and (same_day or end_before_start):
                        errors.append({
                            "id": comp["id"],
                            "title": comp["title"],
                            "url": comp.get("url"),
                            "reason": "start_equals_end" if same_day else "end_before_start",
                            "start_date": sd,
                            "end_date": ed,
                            "created_at": _now().isoformat(),
                        })
                        await self._save_kv("errors", errors[-200:])
                except Exception:
                    pass
                if is_reg and tw["end"] and tw["end"] > _now():
                    kb = [k for k in kb if k.get("id") != comp["id"]]
                    kb.append(comp)
                    updated = True
                last_ids.append(it["id"])
            if last_ids:
                await self._save_kv("last_seen_ids", last_ids[-200:])
            if updated:
                await self._save_kv("competitions", kb)
                await self._save_store_file()
            logger.info("[XJEdu] 初始同步完成，补充知识库")
        except Exception as e:
            logger.warning(f"[XJEdu] 初始同步异常: {e}")

    async def _periodic_check_loop(self, interval_sec: int):
        while self._running:
            try:
                await self._check_and_push()
            except Exception as e:
                logger.warning(f"[XJEdu] 定时检查异常: {e}")
            await asyncio.sleep(interval_sec)

    async def _daily_deadline_remind_loop(self, hour: int = 9):
        # 每分钟检查一次是否到点，避免阻塞
        while self._running:
            try:
                now = _now()
                if now.hour == hour and now.minute in (0, 1):
                    await self._send_deadline_reminders(days_threshold=3)
                    await asyncio.sleep(120)
            except Exception as e:
                logger.warning(f"[XJEdu] 截止提醒异常: {e}")
            await asyncio.sleep(60)

    async def _check_and_push(self):
        items = await self._fetch_competition_list()
        if not items:
            return
        last_ids: List[str] = await self._get_kv("last_seen_ids", [])
        subscribers: List[str] = await self._get_kv("subscribers", [])
        kb: List[Dict[str, Any]] = await self._get_kv("competitions", [])

        new_items = [i for i in items if i["id"] not in last_ids]
        if not new_items:
            return

        for it in new_items:
            detail = await self._fetch_detail(it["url"]) if it.get("url") else {}
            title = it.get("title", "")
            body = detail.get("body", "")
            raw_html = detail.get("html", "")
            ai_res = await self._ai_extract_competition(title, body, raw_html)
            if not ai_res:
                continue
            is_reg = bool(ai_res.get("is_registration", False))
            tw_start = _parse_date(ai_res.get("start_date")) if ai_res.get("start_date") else None
            tw_end = _parse_date(ai_res.get("end_date")) if ai_res.get("end_date") else None
            tw = {"start": tw_start, "end": tw_end}
            qq = _extract_qq_group(body)
            # 仅在正文包含“即日起”等描述时，使用列表日期作为报名开始时间
            if is_reg and (tw.get("start") is None) and ("即日起" in body):
                hint_dt = _parse_date(it.get("post_time") or "")
                if hint_dt:
                    tw["start"] = hint_dt

            comp = {
                "id": it["id"],
                "title": title,
                "url": it.get("url"),
                "post_time": it.get("post_time"),
                "is_registration": is_reg,
                "start_date": tw["start"].isoformat() if tw["start"] else None,
                "end_date": tw["end"].isoformat() if tw["end"] else None,
                "qq_group": qq,
                "created_at": _now().isoformat(),
                "last_remind": None,
            }
            # 错误目录：若为报名但开始与截止日期相同或截止早于开始，计入错误目录
            try:
                errors: List[Dict[str, Any]] = await self._get_kv("errors", [])
                sd = comp.get("start_date")
                ed = comp.get("end_date")
                def _d(s: Optional[str]) -> Optional[datetime]:
                    try:
                        return datetime.fromisoformat(s) if s else None
                    except Exception:
                        return None
                sdt = _d(sd)
                edt = _d(ed)
                same_day = (sd and ed and sd[:10] == ed[:10])
                end_before_start = (sdt and edt and edt < sdt)
                if comp.get("is_registration") and (same_day or end_before_start):
                    errors.append({
                        "id": comp["id"],
                        "title": comp["title"],
                        "url": comp.get("url"),
                        "reason": "start_equals_end" if same_day else "end_before_start",
                        "start_date": sd,
                        "end_date": ed,
                        "created_at": _now().isoformat(),
                    })
                    await self._save_kv("errors", errors[-200:])
            except Exception:
                pass
            # 更新知识库：若为报名且尚处在报名阶段，加入KB
            if is_reg and ((tw["end"] and tw["end"] > _now()) or tw["end"] is None):
                # 去重更新
                kb = [k for k in kb if k.get("id") != comp["id"]]
                kb.append(comp)
            else:
                pass

            await self._broadcast_competition(comp, subscribers)

        if not new_items:
            pass

        # 更新 last_seen 与 KB
        last_ids.extend([i["id"] for i in new_items])
        await self._save_kv("last_seen_ids", last_ids[-200:])
        await self._save_kv("competitions", kb)
        await self._save_store_file()

    async def _broadcast_competition(self, comp: Dict[str, Any], subscribers: List[str]):
        # 仅推送报名类信息，非报名通知直接跳过
        if not comp.get("is_registration"):
            return
        # 组装推送文本（报名信息）
        lines = [f"【竞赛报名】{comp.get('title','')}"]
        if comp.get("url"):
            lines.append(f"链接：{comp['url']}")
        sd = comp.get("start_date")
        ed = comp.get("end_date")
        if sd:
            lines.append(f"开始时间：{sd[:10]}")
        if ed:
            lines.append(f"截止时间：{ed[:10]}")
        if comp.get("qq_group"):
            lines.append(f"竞赛QQ群：{comp['qq_group']}")
        msg = self._persona_wrap("\n".join(lines))

        chain = MessageChain().message(msg)
        for sess in subscribers:
            try:
                await self.context.send_message(sess, chain)
            except Exception as e:
                logger.warning(f"[XJEdu] 推送失败 {sess}: {e}")

    async def _send_deadline_reminders(self, days_threshold: int = 3):
        subscribers: List[str] = await self._get_kv("subscribers", [])
        kb: List[Dict[str, Any]] = await self._get_kv("competitions", [])
        if not kb or not subscribers:
            return
        now = _now()
        for comp in kb:
            ed = comp.get("end_date")
            if not ed:
                continue
            try:
                end_dt = datetime.fromisoformat(ed)
            except Exception:
                continue
            days_left = (end_dt.date() - now.date()).days
            if 0 <= days_left <= days_threshold:
                # 防重推：同一天只推一次
                last_remind = comp.get("last_remind")
                if last_remind and last_remind[:10] == now.date().isoformat():
                    continue
                msg = (
                    f"【报名提醒】{comp.get('title','')}\n"
                    f"报名截至：{end_dt.date().isoformat()}\n"
                    f"剩余天数：{days_left}天"
                )
                chain = MessageChain().message(self._persona_wrap(msg))
                for sess in subscribers:
                    try:
                        await self.context.send_message(sess, chain)
                    except Exception as e:
                        logger.warning(f"[XJEdu] 截止提醒失败 {sess}: {e}")
                comp["last_remind"] = now.isoformat()
        await self._save_kv("competitions", kb)
        await self._save_store_file()

    async def _fetch_html(self, url: str) -> str:
        if not aiohttp:
            return ""
        # 支持从环境变量读取代理，提升通过率
        proxy = os.getenv("ASTRBOT_HTTP_PROXY") or os.getenv("HTTP_PROXY")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://due.xjtu.edu.cn/",
        }
        async with aiohttp.ClientSession(headers=headers) as sess:
            try:
                async with sess.get(url, timeout=20, proxy=proxy) as resp:
                    text = await resp.text(errors="ignore")
                    # 站点可能有JS动态验证，若检测到challenge则尝试浏览器渲染兜底
                    if "dynamic_challenge" in text or resp.status in (403, 429):
                        if not self._challenge_warned:
                            preview = text[:200].replace("\n", " ")
                            logger.warning(
                                f"[XJEdu] 遇到动态挑战或限流，尝试使用 Playwright 渲染。status={resp.status} preview={preview}"
                            )
                            self._challenge_warned = True
                        rendered = await self._fetch_html_playwright(url, proxy)
                        return rendered or ""
                    return text
            except Exception as e:
                logger.exception(f"[XJEdu] 抓取失败: {e}")
                return ""

    async def _fetch_html_playwright(self, url: str, proxy: Optional[str] = None) -> str:
        if not async_playwright:
            logger.warning("[XJEdu] Playwright 未安装，无法执行动态渲染。可通过 pip install playwright && playwright install chromium 安装。")
            return ""
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, proxy={"server": proxy} if proxy else None)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                    locale="zh-CN",
                )
                page = await context.new_page()
                await page.goto(url, wait_until="networkidle", timeout=20000)
                # 等待页面执行挑战与跳转，适度等待即可
                await page.wait_for_timeout(4000)
                content = await page.content()
                # 若仍包含 challenge 关键字，再多等一轮
                if "dynamic_challenge" in content or "安全检查" in content:
                    await page.wait_for_timeout(4000)
                    content = await page.content()
                # 首次渲染落盘，便于人工检查结构
                if not self._render_dumped:
                    dump_path = os.path.join(os.path.dirname(__file__), "debug_rendered.html")
                    try:
                        with open(dump_path, "w", encoding="utf-8", errors="ignore") as f:
                            f.write(content)
                    except Exception as dump_err:
                        logger.warning(f"[XJEdu] 渲染结果落盘失败: {dump_err}")
                    self._render_dumped = True
                await browser.close()
                return content
        except Exception as e:
            logger.exception(f"[XJEdu] Playwright 渲染失败: {e}")
            return ""

    async def _fetch_competition_list(self) -> List[Dict[str, Any]]:
        # 多入口抓取 + 本地回退
        html_list: List[tuple[str, str]] = []
        main_html = await self._fetch_html(DUE_LIST_URL)
        if main_html:
            html_list.append((main_html, DUE_LIST_URL))
        for u in DUE_LIST_EXTRA:
            h = await self._fetch_html(u)
            if h:
                html_list.append((h, u))

        # 本地回退：同目录 source_code.html 或环境变量 ASTRBOT_XJTU_FALLBACK_HTML 指向的文件
        if not html_list:
            local_path = os.getenv("ASTRBOT_XJTU_FALLBACK_HTML") or os.path.join(os.path.dirname(__file__), "source_code.html")
            if os.path.exists(local_path):
                try:
                    with open(local_path, "r", encoding="utf-8", errors="ignore") as f:
                        html_list.append((f.read(), "file://fallback"))
                    logger.info(f"[XJEdu] 使用本地HTML回退: {local_path}")
                except Exception as e:
                    logger.warning(f"[XJEdu] 读取本地回退HTML失败: {e}")

        items: Dict[str, Dict[str, Any]] = {}
        if not BeautifulSoup:
            return []

        for html, base in html_list:
            parsed = self._parse_list_html(html, base)
            for it in parsed:
                items[it["id"]] = it

        if not items and not main_html:
            logger.warning("[XJEdu] 未获取到页面HTML，可能被反爬或网络异常。")
        return list(items.values())

    def _parse_list_html(self, html: str, base_url: str) -> List[Dict[str, Any]]:
        soup = BeautifulSoup(html, "html.parser")
        found: List[Dict[str, Any]] = []
        # 优先解析列表 ul.list li a span
        for li in soup.select("ul.list li"):
            a = li.find("a")
            date_span = li.find("span")
            if not a or not a.get("href"):
                continue
            title = (a.get_text() or "").strip()
            href = a.get("href").strip()
            # 过滤关键词，放宽到含 竞赛/比赛/报名/竞赛大创/竞赛安排
            if not any(k in title for k in ["竞赛", "比赛", "报名", "大创", "赛"]):
                continue
            url = href if href.startswith("http") else self._normalize_url(base_url, href)
            post_time = (date_span.get_text() or "").strip() if date_span else None
            found.append({
                "id": url,
                "title": title,
                "url": url,
                "post_time": post_time,
            })
        # 兜底：全局链接扫描
        if not found:
            for a in soup.find_all("a", href=True):
                title = (a.get_text() or "").strip()
                href = a["href"].strip()
                if not title:
                    continue
                if not any(k in title for k in ["竞赛", "比赛", "报名", "大创", "赛"]):
                    continue
                url = href if href.startswith("http") else self._normalize_url(base_url, href)
                found.append({
                    "id": url,
                    "title": title,
                    "url": url,
                    "post_time": None,
                })
        return found

    def _normalize_url(self, base_url: str, href: str) -> str:
        if href.startswith("http"):
            return href
        if href.startswith("../"):
            # 去掉 ../
            href = href[3:]
        if href.startswith("./"):
            href = href[2:]
        # 基础域
        if base_url.startswith("http"):
            root = "https://due.xjtu.edu.cn/"
            return root + href.lstrip("/")
        return href

    async def _fetch_detail(self, url: str) -> Dict[str, Any]:
        html = await self._fetch_html(url)
        if not html or not BeautifulSoup:
            return {"body": "", "html": html or ""}
        soup = BeautifulSoup(html, "html.parser")
        # 优先从正文容器抽取
        candidates = []
        selectors = [
            "div#ny-main", "div.ny", "div#vsb_content", "div#vsb_content_2",
            "div#vsb_content_4", "div#vsb_content_5", "div.article", "div.content",
            "div.news-content"
        ]
        for sel in selectors:
            candidates.extend(soup.select(sel))
        best_text = ""
        for el in candidates:
            t = el.get_text("\n", strip=True)
            if len(t) > len(best_text):
                best_text = t
        if not best_text:
            best_text = soup.get_text("\n")
        return {"body": best_text, "html": html}

    def _extract_relevant_snippet(self, body: str) -> str:
        lines = [ln.strip() for ln in (body or "").splitlines()]
        patt_date = re.compile(r"\d{4}[年./-]\d{1,2}[月./-]\d{1,2}")
        include_kw = ["报名", "报名通知", "报名开始", "报名截止", "参赛", "竞赛", "安排", "截止时间", "开始时间", "报名时间", "发布日期", "发布"]
        discard_kw = ["当前位置", "上一篇", "下一篇", "打印", "分享", "返回", "阅读", "浏览次数", "来源", "作者"]
        picked = []
        for ln in lines:
            if not ln:
                continue
            # 排除明显的导航/页眉页脚等无关内容
            if any(k in ln for k in discard_kw) and not any(k in ln for k in include_kw):
                continue
            # 收入包含日期或关键报名词的行
            if patt_date.search(ln) or any(k in ln for k in include_kw):
                picked.append(ln)
            if len(picked) >= 60:
                break
        return "\n".join(picked if picked else lines[:60])

    async def _send_welcome_with_latest(self):
        subscribers: List[str] = await self._get_kv("subscribers", [])
        if not subscribers:
            return
        items = await self._fetch_competition_list()
        latest = items[0] if items else None
        greeting = "🤖 XJEdu 竞赛监控已上线，开始为您监听教务处通知。"
        msg_lines = [greeting]
        if latest:
            msg_lines.append("最新通知示例：")
            msg_lines.append(f"- {latest.get('title','')}")
            if latest.get("url"):
                msg_lines.append(f"  链接：{latest['url']}")
        chain = MessageChain().message("\n".join(msg_lines))
        for sess in subscribers:
            try:
                await self.context.send_message(sess, MessageChain().message(self._persona_wrap("\n".join(msg_lines))))
            except Exception as e:
                logger.warning(f"[XJEdu] 上线问候发送失败 {sess}: {e}")

    # ==================== 指令组：竞赛（英文短名 comp） ====================
    @filter.command_group("comp")
    def competition_group(self):
        """Competition commands"""
        pass

    @competition_group.command("sub")
    async def cmd_subscribe(self, event: AstrMessageEvent):
        sess = event.unified_msg_origin
        subs: List[str] = await self._get_kv("subscribers", [])
        if sess in subs:
            yield event.plain_result(self._persona_wrap("已订阅，无需重复操作"))
            return
        subs.append(sess)
        await self._save_kv("subscribers", subs)
        yield event.plain_result(self._persona_wrap("✅ 已订阅竞赛推送"))

    @competition_group.command("unsub")
    async def cmd_unsubscribe(self, event: AstrMessageEvent):
        sess = event.unified_msg_origin
        subs: List[str] = await self._get_kv("subscribers", [])
        if sess not in subs:
            yield event.plain_result(self._persona_wrap("未订阅"))
            return
        subs = [s for s in subs if s != sess]
        await self._save_kv("subscribers", subs)
        yield event.plain_result(self._persona_wrap("✅ 已退订竞赛推送"))

    @competition_group.command("list")
    async def cmd_list(self, event: AstrMessageEvent):
        kb: List[Dict[str, Any]] = await self._get_kv("competitions", [])
        errors: List[Dict[str, Any]] = await self._get_kv("errors", [])
        if not kb:
            tip = "📋 当前暂无正在报名的竞赛"
            if errors:
                tip += f"\n⚠️ 错误目录：{len(errors)} 条（可在本地存储中修复）"
            yield event.plain_result(self._persona_wrap(tip))
            return
        lines = ["📋 当前可报名竞赛："]
        if errors:
            lines.append(f"⚠️ 错误目录：{len(errors)} 条（可在本地存储中修复）")
        kb_sorted = sorted(
            kb,
            key=lambda x: x.get("end_date") or "9999-12-31",
        )
        for c in kb_sorted:
            ed = c.get("end_date")
            title = c.get("title")
            url = c.get("url")
            line = f"- {title}"
            if ed:
                try:
                    line += f" | 截止: {datetime.fromisoformat(ed).date().isoformat()}"
                except Exception:
                    pass
            if url:
                line += f"\n  链接: {url}"
            if c.get("qq_group"):
                line += f"\n  QQ群: {c['qq_group']}"
            lines.append(line)
        yield event.plain_result(self._persona_wrap("\n".join(lines)))

    @competition_group.command("check")
    async def cmd_check(self, event: AstrMessageEvent):
        await self._check_and_push()
        yield event.plain_result(self._persona_wrap("✅ 已完成一次即时检查"))

    # ==================== 指令组：管理（英文短名 cadmin） ====================
    @filter.command_group("cadmin")
    def manage_group(self):
        """Competition admin commands"""
        pass

    @manage_group.command("ai")
    async def cmd_ai_toggle(self, event: AstrMessageEvent, mode: str = ""):
        """AI 检测开关。用法：/竞赛管理 ai on|off"""
        mode = (mode or "").strip().lower()
        if mode in ("on", "off", "开启", "关闭"):
            flag = mode in ("on", "开启")
            await self._save_kv("ai_use", flag)
            yield event.plain_result(self._persona_wrap(f"AI 解析已{'开启' if flag else '关闭'}"))
            return
        # 显示当前状态
        enabled = await self._is_ai_enabled()
        yield event.plain_result(self._persona_wrap(f"AI 解析当前状态：{'开启' if enabled else '关闭'}\n用法：/竞赛管理 ai on|off"))

    @manage_group.command("init")
    async def cmd_manual_init(self, event: AstrMessageEvent):
        """手动初始化：从教务处拉取并补充知识库（不推送历史）。"""
        try:
            items = await self._fetch_competition_list()
            if not items:
                yield event.plain_result(self._persona_wrap("⚠️ 初始化失败：未抓取到竞赛列表（可能被反爬或网络异常）"))
                return
            await self._initial_sync()
            latest = items[0]
            lines = ["✅ 已完成初始化同步", "最新抓取：", f"- {latest.get('title','')}"]
            if latest.get("url"):
                lines.append(f"  链接：{latest['url']}")
            yield event.plain_result(self._persona_wrap("\n".join(lines)))
        except Exception as e:
            yield event.plain_result(self._persona_wrap(f"⚠️ 初始化异常：{e}"))

    @manage_group.command("aitest")
    async def cmd_ai_test(self, event: AstrMessageEvent):
        """AI 连通性检测：请求一次抽取并展示回复预览。"""
        try:
            enabled = await self._is_ai_enabled()
            if not enabled:
                yield event.plain_result(self._persona_wrap("AI 当前为关闭，可用 /cadmin ai on 开启"))
                return
            sample_title = "关于举办2026年某某竞赛的通知"
            sample_body = "报名时间：2026-02-01 至 2026-02-20。参赛对象为全体本科生。"
            res = await self._ai_extract_competition(sample_title, sample_body)
            if not res:
                yield event.plain_result(self._persona_wrap("⚠️ AI 请求或解析失败，请查看日志与 ai_last_response.json"))
                return
            # 保存到文件
            out_path = os.path.join(os.path.dirname(__file__), "ai_last_response.json")
            if os.path.exists(out_path):
                try:
                    with open(out_path, "r", encoding="utf-8") as f:
                        preview = f.read()[:200]
                except Exception:
                    preview = json.dumps(res, ensure_ascii=False)[:200]
            else:
                preview = json.dumps(res, ensure_ascii=False)[:200]
            logger.warning(f"[XJEdu] AI 连通性检测返回: {preview}")
            yield event.plain_result(self._persona_wrap(f"✅ AI 连通性正常，预览：\n{json.dumps(res, ensure_ascii=False, indent=2)}"))
        except Exception as e:
            yield event.plain_result(self._persona_wrap(f"⚠️ AI 连通性检测异常：{e}"))

    @manage_group.command("reset")
    async def cmd_reset(self, event: AstrMessageEvent):
        """清空已读与缓存，方便重新推送测试。"""
        try:
            await self._save_kv("last_seen_ids", [])
            await self._save_kv("competitions", [])
            await self._save_kv("errors", [])
            # 删除外置文件
            removed = False
            if os.path.exists(STORE_PATH):
                os.remove(STORE_PATH)
                removed = True
            msg = "✅ 已清空已读与缓存"
            if removed:
                msg += "，并已删除本地存储文件"
            else:
                msg += "（本地存储文件不存在）"
            msg += "，可再次 /comp check 重拉推送"
            yield event.plain_result(self._persona_wrap(msg))
        except Exception as e:
            yield event.plain_result(self._persona_wrap(f"⚠️ 重置失败：{e}"))

    @manage_group.command("stopcheck")
    async def cmd_stop_check(self, event: AstrMessageEvent):
        """停止定时检查任务。"""
        try:
            await self._stop_check_task()
            yield event.plain_result(self._persona_wrap("✅ 已停止定时检查任务"))
        except Exception as e:
            yield event.plain_result(self._persona_wrap(f"⚠️ 停止失败：{e}"))

    # ==================== 帮助 ====================
    @filter.command("竞赛帮助")
    async def cmd_help(self, event: AstrMessageEvent):
        lines = [
            "📖 竞赛插件指令总览",
            "基础指令组（comp）：",
            "  /comp sub           订阅竞赛推送（群/私聊均可）",
            "  /comp unsub         退订竞赛推送",
            "  /comp list          查看当前可报名竞赛",
            "  /comp check         立即抓取一次教务处通知",
            "  /竞赛帮助            查看本帮助",
            "管理指令组（cadmin）：",
            "  /cadmin ai on|off      开关AI解析并查看状态",
            "  /cadmin init           手动执行初始化拉取",
            "  /cadmin aitest         AI 连通性自检（需配置密钥）",
            "  /cadmin reset          清空缓存与本地存储",
            "  /cadmin stopcheck      停止定时检查任务",
            "使用提示：命令前缀与权限规则以机器人全局配置为准。",
        ]
        yield event.plain_result(self._persona_wrap("\n".join(lines)))

