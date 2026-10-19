"""Secure, durable Feishu notification orchestration."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ResourceNotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.security import decrypt_sensitive_data, encrypt_sensitive_data
from app.db.models.notification import NotificationChannel, NotificationDelivery
from app.db.models.report import NotificationRule
from app.modules.audit.service import AuditService
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.schemas import (
    EVENT_CATALOG,
    TEMPLATE_CATALOG,
    ChannelCreate,
    ChannelInfo,
    ChannelUpdate,
    DeliveryInfo,
    RuleCreate,
    RuleInfo,
    RuleUpdate,
)
from app.modules.permission.repository import PermissionRepository


logger = get_logger(__name__)

FEISHU_WEBHOOK_RE = re.compile(
    r"^https://open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9_-]{8,}$"
)
TEMPLATES = {item["code"]: item for item in TEMPLATE_CATALOG}
RECIPIENT_LABELS = {
    "all_members": "全体项目成员",
    "project_admins": "项目管理员",
    "event_owner": "事件负责人",
    "affected_member": "受影响成员",
    "custom": "指定成员",
}
HEADER_STYLES = {
    "success": "green",
    "danger": "red",
    "warning": "orange",
    "info": "blue",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NotificationService:
    """Own notification configuration and the durable delivery state machine."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = NotificationRepository(db)
        self.permission_repo = PermissionRepository(db)
        self.audit = AuditService(db)

    @staticmethod
    def catalog() -> dict[str, list[dict[str, Any]]]:
        return {"events": EVENT_CATALOG, "templates": TEMPLATE_CATALOG}

    async def list_channels(self, project_id: int) -> list[ChannelInfo]:
        return [self._channel_info(item) for item in await self.repo.list_channels(project_id)]

    async def create_channel(self, project_id: int, data: ChannelCreate, user_id: int) -> ChannelInfo:
        webhook = self._validate_webhook(data.webhook_url)
        if await self.repo.channel_name_exists(project_id, data.name):
            raise ValidationError("Webhook 名称已存在")
        channel = await self.repo.create_channel(
            project_id=project_id,
            name=data.name.strip(),
            channel_type="feishu_webhook",
            webhook_encrypted=encrypt_sensitive_data(webhook),
            enabled=data.enabled,
            created_by=user_id,
            updated_by=user_id,
        )
        await self.audit.record(
            "notification.channel.create", "notification_channel", user_id,
            project_id, channel.id, {"name": channel.name},
        )
        await self.db.commit()
        await self.db.refresh(channel)
        return self._channel_info(channel)

    async def update_channel(
        self, project_id: int, channel_id: int, data: ChannelUpdate, user_id: int
    ) -> ChannelInfo:
        channel = await self._require_channel(project_id, channel_id)
        values = data.model_dump(exclude_unset=True)
        if "name" in values:
            name = values["name"].strip()
            if await self.repo.channel_name_exists(project_id, name, channel_id):
                raise ValidationError("Webhook 名称已存在")
            channel.name = name
        if values.get("webhook_url"):
            channel.webhook_encrypted = encrypt_sensitive_data(
                self._validate_webhook(values["webhook_url"])
            )
        if "enabled" in values:
            channel.enabled = values["enabled"]
        channel.updated_by = user_id
        await self.audit.record(
            "notification.channel.update", "notification_channel", user_id,
            project_id, channel.id, {"fields": sorted(values)},
        )
        await self.db.commit()
        await self.db.refresh(channel)
        return self._channel_info(channel)

    async def delete_channel(self, project_id: int, channel_id: int, user_id: int) -> None:
        channel = await self._require_channel(project_id, channel_id)
        if await self.repo.channel_rule_count(channel_id):
            raise ValidationError("该 Webhook 正被通知规则使用，请先调整规则")
        await self.audit.record(
            "notification.channel.delete", "notification_channel", user_id,
            project_id, channel.id, {"name": channel.name},
        )
        await self.db.delete(channel)
        await self.db.commit()

    async def test_channel(
        self, project_id: int, channel_id: int, message: str, user_id: int
    ) -> dict[str, Any]:
        channel = await self._require_channel(project_id, channel_id)
        payload, recipient_meta = await self._build_card_with_recipients(
            project_id,
            "daily_summary",
            "Webhook 测试消息",
            {"message": message, "operator_id": user_id},
            "project_admins",
        )
        # Decrypt open_ids and inject mentions
        encrypted_open_ids = recipient_meta.get("encrypted_open_ids") or []
        open_ids = [
            decrypt_sensitive_data(enc)
            for enc in encrypted_open_ids
            if enc
        ]
        final_card = self._inject_mentions(payload, open_ids)
        try:
            response = await self._post_webhook(
                decrypt_sensitive_data(channel.webhook_encrypted), final_card
            )
            channel.last_test_status = "success"
            result = {"success": True, "response": self._safe_json(response)}
        except Exception as exc:
            channel.last_test_status = "failed"
            result = {"success": False, "error": self._safe_error(exc)}
        channel.last_test_at = utcnow()
        channel.updated_by = user_id
        await self.audit.record(
            "notification.channel.test", "notification_channel", user_id,
            project_id, channel.id, {"success": result["success"]},
        )
        await self.db.commit()
        return result

    async def list_rules(self, project_id: int) -> list[RuleInfo]:
        return [self._rule_info(item) for item in await self.repo.list_rules(project_id)]

    async def create_rule(self, project_id: int, data: RuleCreate, user_id: int) -> RuleInfo:
        await self._validate_rule(project_id, data.model_dump())
        rule = await self.repo.create_rule(
            project_id=project_id,
            name=data.name.strip(),
            enabled=data.enabled,
            trigger_type=self._legacy_trigger(data.event_type),
            conditions_json=data.conditions_json,
            webhook_url=None,
            event_type=data.event_type,
            channel_id=data.channel_id,
            template_code=data.template_code,
            recipient_type=data.recipient_type,
            recipient_config=data.recipient_config,
            created_by=user_id,
            updated_by=user_id,
        )
        await self.audit.record(
            "notification.rule.create", "notification_rule", user_id,
            project_id, rule.id, {"name": rule.name, "event_type": rule.event_type},
        )
        await self.db.commit()
        return self._rule_info(await self.repo.get_rule(rule.id))

    async def update_rule(
        self, project_id: int, rule_id: int, data: RuleUpdate, user_id: int
    ) -> RuleInfo:
        rule = await self._require_rule(project_id, rule_id)
        values = data.model_dump(exclude_unset=True)
        merged = {
            "name": rule.name,
            "event_type": rule.event_type,
            "channel_id": rule.channel_id,
            "template_code": rule.template_code,
            "recipient_type": rule.recipient_type,
            "recipient_config": rule.recipient_config,
            "conditions_json": rule.conditions_json,
            "enabled": rule.enabled,
            **values,
        }
        await self._validate_rule(project_id, merged)
        for field, value in values.items():
            setattr(rule, field, value)
        if "event_type" in values:
            rule.trigger_type = self._legacy_trigger(values["event_type"])
        rule.updated_by = user_id
        await self.audit.record(
            "notification.rule.update", "notification_rule", user_id,
            project_id, rule.id, {"fields": sorted(values)},
        )
        await self.db.commit()
        return self._rule_info(await self.repo.get_rule(rule.id))

    async def delete_rule(self, project_id: int, rule_id: int, user_id: int) -> None:
        rule = await self._require_rule(project_id, rule_id)
        await self.audit.record(
            "notification.rule.delete", "notification_rule", user_id,
            project_id, rule.id, {"name": rule.name},
        )
        await self.db.delete(rule)
        await self.db.commit()

    async def list_deliveries(
        self,
        project_id: int,
        page: int,
        page_size: int,
        event_type: str | None = None,
        status: str | None = None,
        started_from: datetime | None = None,
        started_to: datetime | None = None,
    ) -> dict[str, Any]:
        total, rows = await self.repo.list_deliveries(
            project_id, page, page_size, event_type, status, started_from, started_to
        )
        items = []
        for delivery, rule_name, channel_name in rows:
            item = DeliveryInfo.model_validate(delivery, from_attributes=True)
            item.rule_name = rule_name
            item.channel_name = channel_name
            item.error_message = self._mask_secrets(item.error_message)
            items.append(item)
        return {"total": total, "items": items}

    async def emit_event(
        self,
        project_id: int,
        event_id: str,
        event_type: str,
        context: dict[str, Any],
        summary: str,
        rule_ids: list[int] | None = None,
    ) -> list[int]:
        """Persist matched deliveries; the caller owns the transaction and commit.

        Args:
            rule_ids: Optional list of specific rule IDs to trigger. If provided,
                     only these rules will be evaluated (if enabled and matching event_type).
                     If None, all enabled rules for the event will be evaluated.
        """
        delivery_ids: list[int] = []

        if rule_ids:
            # 只触发指定的规则
            rules = await self.repo.get_rules_by_ids(rule_ids, project_id, event_type)
        else:
            # 触发所有匹配的规则
            rules = await self.repo.enabled_rules_for_event(project_id, event_type)
        for rule in rules:
            status = "pending"
            reason = None
            if not rule.channel or not rule.channel.enabled:
                status, reason = "skipped", "通知渠道未启用"
            elif not self._match_event_conditions(rule.conditions_json, context):
                status, reason = "skipped", "未命中触发条件"
            card, recipient_meta = await self._build_card_with_recipients(
                project_id, rule.template_code, summary, context,
                rule.recipient_type, rule.recipient_config or {},
            )
            if status == "pending" and recipient_meta.get("resolved_count", 0) == 0:
                status, reason = "skipped", "未找到有效接收人或接收人未绑定飞书身份"
            payload = {
                "webhook_payload": card,
                "recipient_meta": recipient_meta,
                "context": self._safe_json(context),
                "recipient_type": rule.recipient_type,
                "recipient_config": self._safe_json(rule.recipient_config or {}),
                "template_code": rule.template_code,
            }
            delivery = await self.repo.create_delivery_idempotent(
                project_id=project_id,
                rule_id=rule.id,
                channel_id=rule.channel_id,
                event_id=event_id,
                event_type=event_type,
                status=status,
                attempt_count=0,
                max_attempts=5,
                next_attempt_at=utcnow() if status == "pending" else None,
                payload_json=payload,
                error_message=reason,
                message_summary=summary[:300],
            )
            if delivery and status == "pending":
                delivery_ids.append(delivery.id)
        return delivery_ids

    async def process_delivery(self, delivery_id: int) -> str:
        delivery = await self.repo.get_delivery(delivery_id, lock=True)
        if not delivery:
            return "missing"
        now = utcnow()
        stale_before = now - timedelta(minutes=5)
        if delivery.status == "sent" or delivery.status in {"failed", "skipped"}:
            return delivery.status
        if delivery.status == "sending" and delivery.updated_at and delivery.updated_at > stale_before:
            return "sending"
        if delivery.status == "retrying" and delivery.next_attempt_at and delivery.next_attempt_at > now:
            return "retrying"
        delivery.status = "sending"
        delivery.attempt_count += 1
        delivery.next_attempt_at = None
        delivery.updated_at = now
        channel_id = delivery.channel_id
        payload_json = delivery.payload_json or {}
        webhook_payload = payload_json.get("webhook_payload") or {}
        await self.db.commit()

        try:
            if not channel_id:
                raise RuntimeError("通知渠道已删除")
            channel = await self.repo.get_channel(channel_id)
            if not channel or not channel.enabled:
                raise RuntimeError("通知渠道不存在或已停用")
            webhook = decrypt_sensitive_data(channel.webhook_encrypted)
            # Decrypt open_ids and inject mentions
            recipient_meta = payload_json.get("recipient_meta") or {}
            encrypted_open_ids = recipient_meta.get("encrypted_open_ids") or []
            open_ids = [
                decrypt_sensitive_data(enc)
                for enc in encrypted_open_ids
                if enc
            ]
            final_card = self._inject_mentions(webhook_payload, open_ids)
            response = await self._post_webhook(webhook, final_card)
            delivery = await self.repo.get_delivery(delivery_id, lock=True)
            if not delivery:
                return "missing"
            delivery.status = "sent"
            delivery.response_json = self._safe_json(response)
            delivery.error_message = None
            delivery.sent_at = utcnow()
            delivery.updated_at = delivery.sent_at
            channel = await self.repo.get_channel(channel_id)
            if channel:
                channel.last_triggered_at = delivery.sent_at
            await self.db.commit()
            return "sent"
        except Exception as exc:
            await self.db.rollback()
            delivery = await self.repo.get_delivery(delivery_id, lock=True)
            if not delivery:
                return "missing"
            delivery.error_message = self._safe_error(exc)
            delivery.updated_at = utcnow()
            if delivery.attempt_count >= delivery.max_attempts:
                delivery.status = "failed"
                delivery.next_attempt_at = None
            else:
                delivery.status = "retrying"
                delay = min(15 * (2 ** max(delivery.attempt_count - 1, 0)), 3600)
                delivery.next_attempt_at = utcnow() + timedelta(seconds=delay)
            await self.db.commit()
            return delivery.status

    async def due_delivery_ids(self, limit: int = 100) -> list[int]:
        return await self.repo.due_delivery_ids(limit)

    @staticmethod
    async def wake_deliveries(delivery_ids: list[int]) -> None:
        if not delivery_ids:
            return
        try:
            from app.workers.notification_tasks import enqueue_notification_delivery

            for delivery_id in delivery_ids:
                await enqueue_notification_delivery(delivery_id)
        except Exception:
            logger.warning(
                "notification queue wake failed; recovery scan will retry ids=%s",
                delivery_ids,
            )

    async def _validate_rule(self, project_id: int, values: dict[str, Any]) -> None:
        channel = await self._require_channel(project_id, int(values["channel_id"]))
        if not channel.enabled and values.get("enabled", True):
            raise ValidationError("启用规则前需先启用 Webhook")
        template = TEMPLATES.get(values["template_code"])
        if not template or values["event_type"] not in template["event_types"]:
            raise ValidationError("消息模板与事件类型不兼容")
        if values["recipient_type"] == "custom":
            member_ids = {int(item) for item in values.get("recipient_config", {}).get("member_ids", [])}
            project_member_ids = await self.permission_repo.project_member_ids(project_id)
            if not member_ids or not member_ids.issubset(project_member_ids):
                raise ValidationError("自定义接收人必须是当前项目成员")

    async def _require_channel(self, project_id: int, channel_id: int) -> NotificationChannel:
        channel = await self.repo.get_channel(channel_id)
        if not channel or channel.project_id != project_id:
            raise ResourceNotFoundError("Webhook 配置不存在")
        return channel

    async def _require_rule(self, project_id: int, rule_id: int) -> NotificationRule:
        rule = await self.repo.get_rule(rule_id)
        if not rule or rule.project_id != project_id:
            raise ResourceNotFoundError("通知规则不存在")
        return rule

    @staticmethod
    def _validate_webhook(value: str) -> str:
        webhook = value.strip()
        if not FEISHU_WEBHOOK_RE.fullmatch(webhook):
            raise ValidationError("仅支持飞书群机器人官方 HTTPS Webhook 地址")
        return webhook

    @staticmethod
    def _mask_webhook(value: str) -> str:
        try:
            suffix = value.rsplit("/", 1)[-1][-6:]
        except Exception:
            suffix = "******"
        return f"https://open.feishu.cn/open-apis/bot/v2/hook/...{suffix}"

    @classmethod
    def _mask_secrets(cls, value: str | None) -> str | None:
        if not value:
            return value
        return re.sub(
            r"https://open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9_-]+",
            "https://open.feishu.cn/open-apis/bot/v2/hook/***",
            value,
        )[:1000]

    @classmethod
    def _safe_error(cls, exc: Exception) -> str:
        return cls._mask_secrets(str(exc))[:1000] or exc.__class__.__name__

    @classmethod
    def _safe_json(cls, value: Any) -> Any:
        budget = [8000]

        def sanitize(item: Any, depth: int = 0) -> Any:
            if budget[0] <= 0:
                return "[truncated]"
            if depth > 6:
                return "[max-depth]"
            if item is None or isinstance(item, (bool, int)):
                budget[0] -= len(str(item))
                return item
            if isinstance(item, float):
                budget[0] -= 24
                return item if math.isfinite(item) else str(item)
            if isinstance(item, str):
                text = cls._mask_secrets(item) or ""
                text = text[:min(2000, max(budget[0], 0))]
                budget[0] -= len(text)
                return text
            if isinstance(item, dict):
                result: dict[str, Any] = {}
                for key, child in list(item.items())[:50]:
                    safe_key = (cls._mask_secrets(str(key)) or "")[:200]
                    budget[0] -= len(safe_key)
                    result[safe_key] = sanitize(child, depth + 1)
                    if budget[0] <= 0:
                        break
                return result
            if isinstance(item, (list, tuple, set)):
                result = []
                for child in list(item)[:50]:
                    result.append(sanitize(child, depth + 1))
                    if budget[0] <= 0:
                        break
                return result
            return sanitize(str(item), depth + 1)

        return sanitize(value)

    @staticmethod
    def _match_event_conditions(conditions: dict[str, Any] | None, context: dict[str, Any]) -> bool:
        if not conditions:
            return True
        statuses = conditions.get("on_status")
        if statuses and context.get("status") not in statuses:
            return False
        minimum_error_rate = conditions.get("min_error_rate")
        if minimum_error_rate is not None and float(context.get("error_rate", 0)) < float(minimum_error_rate):
            return False
        return True

    async def _resolve_recipient_candidates(
        self,
        project_id: int,
        recipient_type: str,
        recipient_config: dict[str, Any],
        context: dict[str, Any],
    ) -> set[int]:
        """Resolve recipient_type to candidate user_id set."""
        if recipient_type == "all_members":
            return await self.repo.project_member_user_ids(project_id)
        elif recipient_type == "project_admins":
            return await self.repo.project_admin_user_ids(project_id)
        elif recipient_type == "event_owner":
            owner_id = context.get("owner_id")
            return {int(owner_id)} if owner_id else set()
        elif recipient_type == "affected_member":
            member_id = context.get("member_id")
            return {int(member_id)} if member_id else set()
        elif recipient_type == "custom":
            member_ids = recipient_config.get("member_ids") or []
            return {int(uid) for uid in member_ids if uid}
        else:
            return set()

    async def _build_card_with_recipients(
        self,
        project_id: int,
        template_code: str,
        summary: str,
        context: dict[str, Any],
        recipient_type: str,
        recipient_config: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Build card + resolve recipients with feishu_open_id."""
        config = recipient_config or {}
        candidate_ids = await self._resolve_recipient_candidates(
            project_id, recipient_type, config, context
        )
        users = await self.repo.users_with_feishu_identity(candidate_ids)
        encrypted_open_ids = [
            encrypt_sensitive_data(user.feishu_open_id)
            for user in users
            if user.feishu_open_id
        ]
        resolved_user_ids = sorted([u.id for u in users])
        resolved_count = len(users)
        skipped_count = len(candidate_ids) - resolved_count
        recipient_meta = {
            "resolved_user_ids": resolved_user_ids,
            "resolved_count": resolved_count,
            "skipped_count": skipped_count,
            "encrypted_open_ids": encrypted_open_ids,
        }
        card = self._build_card_placeholder(
            template_code, summary, context, recipient_type, resolved_count
        )
        return (card, recipient_meta)

    @classmethod
    def _build_card_placeholder(
        cls, template_code: str, summary: str, context: dict[str, Any], recipient_type: str, resolved_count: int = 0
    ) -> dict[str, Any]:
        template = TEMPLATES.get(template_code, TEMPLATES["daily_summary"])
        title = template["name"]
        fields = ["__MENTION_PLACEHOLDER__", f"**消息摘要**: {cls._plain(summary)}"]
        preferred = (
            ("project_name", "项目"), ("plan_name", "测试计划"),
            ("task_name", "任务"), ("case_name", "用例"),
            ("status", "状态"), ("pass_rate", "通过率"),
            ("error_rate", "错误率"), ("duration", "耗时"),
            ("role_name", "新角色"),
        )
        for key, label in preferred:
            if key in context and context[key] is not None:
                value = context[key]
                if key in {"pass_rate", "error_rate"}:
                    value = f"{float(value):.2f}%"
                fields.append(f"**{label}**: {cls._plain(value)}")
        recipient_label = RECIPIENT_LABELS.get(recipient_type, recipient_type)
        if resolved_count > 0:
            recipient_label += f" ({resolved_count}人)"
        fields.append(f"**通知范围**: {recipient_label}")
        return {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": HEADER_STYLES.get(template.get("tone"), "blue"),
                },
                "elements": [{
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": "\n".join(fields)},
                }],
            },
        }

    @staticmethod
    def _inject_mentions(card: dict, open_ids: list[str]) -> dict:
        """Deep-copy card and inject @-mentions for open_ids."""
        import json
        card_copy = json.loads(json.dumps(card))
        placeholder = "__MENTION_PLACEHOLDER__"
        try:
            content = card_copy['card']['elements'][0]['text']['content']
        except (KeyError, IndexError, TypeError):
            return card_copy
        if not open_ids:
            content = content.replace(placeholder + "\n", "").replace(placeholder, "")
        else:
            mentions = " ".join(f'<at id="{oid}"></at>' for oid in open_ids[:50])
            content = content.replace(placeholder, mentions)
        card_copy['card']['elements'][0]['text']['content'] = content
        return card_copy

    @staticmethod
    def _plain(value: Any) -> str:
        """Sanitize value for Lark Markdown: escape HTML entities and clean whitespace."""
        s = str(value)
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        s = s.replace("\n", " ").replace("\r", " ")
        return s[:300]


    @staticmethod
    async def _post_webhook(webhook_url: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
            body = response.json()
        code = body.get("code", body.get("StatusCode", 0))
        if code not in (0, None):
            raise RuntimeError(f"飞书返回错误，code={code}")
        return body

    @staticmethod
    def _legacy_trigger(event_type: str) -> str:
        return "plan_run" if event_type.startswith(("execution.", "schedule.")) else "execution"

    @classmethod
    def _channel_info(cls, channel: NotificationChannel) -> ChannelInfo:
        try:
            masked = cls._mask_webhook(decrypt_sensitive_data(channel.webhook_encrypted))
        except Exception:
            masked = "Webhook 密文不可用"
        return ChannelInfo(
            id=channel.id,
            project_id=channel.project_id,
            name=channel.name,
            channel_type=channel.channel_type,
            enabled=channel.enabled,
            webhook_masked=masked,
            last_test_status=channel.last_test_status,
            last_test_at=channel.last_test_at,
            last_triggered_at=channel.last_triggered_at,
            created_at=channel.created_at,
            updated_at=channel.updated_at,
        )

    @staticmethod
    def _rule_info(rule: NotificationRule) -> RuleInfo:
        return RuleInfo(
            id=rule.id,
            project_id=rule.project_id,
            name=rule.name,
            enabled=rule.enabled,
            event_type=rule.event_type,
            channel_id=rule.channel_id,
            channel_name=rule.channel.name if rule.channel else None,
            template_code=rule.template_code,
            recipient_type=rule.recipient_type,
            recipient_config=rule.recipient_config or {},
            conditions_json=rule.conditions_json or {},
            created_at=rule.created_at,
            updated_at=rule.updated_at,
        )
