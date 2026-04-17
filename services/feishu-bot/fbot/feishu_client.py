"""
Feishu / Lark Open Platform API client.

Uses the lark_oapi SDK to:
- Send interactive message cards (binding card, normal reply card)
- Obtain tenant access tokens

Design note: We do NOT use the lark_oapi event dispatcher here — the FastAPI
webhook handler owns the event parsing.  lark_oapi is used purely for its
well-tested HTTP API wrapper (CreateMessageRequest, etc.).
"""

from __future__ import annotations

import logging
from typing import Optional

import lark_oapi as lark

from fbot.config import get_settings

logger = logging.getLogger(__name__)

# ── Lark client (lazy) ────────────────────────────────────────────────────────


_client: Optional[lark.Client] = None


def get_lark_client() -> lark.Client:
    """Return the shared lark_oapi client, creating it on first call."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = lark.Client.builder()
        if settings.FEISHU_APP_ID:
            _client = _client.app_id(settings.FEISHU_APP_ID)
        if settings.FEISHU_APP_SECRET:
            _client = _client.app_secret(settings.FEISHU_APP_SECRET)
        _client = _client.build()
        logger.info("Lark client initialised for app_id=%s", settings.FEISHU_APP_ID)
    return _client


# ── Message card helpers ──────────────────────────────────────────────────────


def _build_binding_card(union_id: str, nonce: str, timestamp: str, sign: str) -> dict:
    """
    Build the interactive card payload for the identity-binding flow.

    The card contains:
    - Title: "Hermes 账号绑定"
    - Description: "您尚未绑定 Hermes 账号，请点击下方按钮完成绑定"
    - Button: opens the binding URL in the browser

    Card version 4 (interactive card format).
    """
    settings = get_settings()
    # Binding URL — Auth Service handles the nonce verification
    bind_url = (
        f"{settings.AUTH_SERVICE_URL.replace('http://', 'https://')}"
        f"/auth/feishu-bind"
        f"?union_id={union_id}"
        f"&nonce={nonce}"
        f"&timestamp={timestamp}"
        f"&sign={sign}"
    )

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "🔗 Hermes 账号绑定"},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        "**您尚未绑定 Hermes 账号**\n\n"
                        "点击下方按钮，在浏览器中完成飞书账号与 Hermes 平台的绑定。"
                        "绑定后，您即可在飞书中直接使用 Hermes Agent。\n\n"
                        f"**飞书账号**: `{union_id}`"
                    ),
                },
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "🔗 绑定我的 Hermes 账号"},
                            "type": "primary",
                            "url": bind_url,
                        }
                    ],
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "绑定链接有效期 5 分钟，如过期请重新在飞书中 @Hermes",
                        }
                    ],
                },
            ],
        },
    }


def _build_reply_card(text: str, msg_id: str = "") -> dict:
    """
    Build a standard text reply card.

    Wraps the response text in a Feishu interactive card with:
    - Monospace text rendering for code blocks
    - Copy-to-clipboard button
    - Source attribution
    """
    escaped = text.replace("\\", "\\\\").replace("\"", "\\\"") \
                  .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "🤖 Hermes Agent"},
                "template": "indigo",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"```\n{text}\n```",
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "由 Hermes Agent 企业平台生成",
                        }
                    ],
                },
            ],
        },
    }


def _build_error_card(error_text: str) -> dict:
    """Build an error notification card sent back to the user."""
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "⚠️ Hermes 请求失败"},
                "template": "red",
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**请求处理失败**\n\n{error_text}",
                },
                {
                    "tag": "note",
                    "elements": [
                        {
                            "tag": "plain_text",
                            "content": "请稍后重试，或联系管理员",
                        }
                    ],
                },
            ],
        },
    }


# ── Public send API ──────────────────────────────────────────────────────────


async def send_card_message(
    chat_id: str,
    card_payload: dict,
) -> tuple[bool, Optional[str]]:
    """
    Send an interactive card message to a Feishu chat.

    Parameters
    ----------
    chat_id : str
        Feishu chat ID (from the inbound message).
    card_payload : dict
        Card JSON (as built by _build_*_card helpers).

    Returns
    -------
    (True, None)           — message sent successfully
    (False, error_message) — send failed
    """
    client = get_lark_client()
    try:
        resp = client.im.v1.message.create(
            lark.im.v1.CreateMessageRequest.builder()
            .request_body(
                lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("interactive")
                .content(lark.util.jsutil.to_json(card_payload))
                .build()
            )
            .receive_id_type("chat_id")
            .build()
        )

        if not resp.success():
            logger.error(
                "Failed to send card to chat_id=%s: code=%s msg=%s",
                chat_id,
                resp.code,
                resp.msg,
            )
            return False, f"Feishu API error: {resp.code} {resp.msg}"
        return True, None

    except Exception as exc:
        logger.exception("Exception sending card to chat_id=%s: %s", chat_id, exc)
        return False, str(exc)


async def send_text_message(
    chat_id: str,
    text: str,
) -> tuple[bool, Optional[str]]:
    """Send a plain text message to a Feishu chat."""
    client = get_lark_client()
    try:
        resp = client.im.v1.message.create(
            lark.im.v1.CreateMessageRequest.builder()
            .request_body(
                lark.im.v1.CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(lark.util.jsutil.to_json({"text": text}))
                .build()
            )
            .receive_id_type("chat_id")
            .build()
        )

        if not resp.success():
            logger.error(
                "Failed to send text to chat_id=%s: code=%s msg=%s",
                chat_id,
                resp.code,
                resp.msg,
            )
            return False, f"Feishu API error: {resp.code} {resp.msg}"
        return True, None

    except Exception as exc:
        logger.exception("Exception sending text to chat_id=%s: %s", chat_id, exc)
        return False, str(exc)


async def reply_to_message(
    msg_id: str,
    card_payload: dict,
) -> tuple[bool, Optional[str]]:
    """
    Reply to a specific Feishu message using its ID.

    This creates a threaded reply in the same chat.
    """
    client = get_lark_client()
    try:
        resp = client.im.v1.message.reply(
            lark.im.v1.ReplyMessageRequest.builder()
            .message_id(msg_id)
            .request_body(
                lark.im.v1.ReplyMessageRequestBody.builder()
                .msg_type("interactive")
                .content(lark.util.jsutil.to_json(card_payload))
                .build()
            )
            .build()
        )

        if not resp.success():
            logger.error(
                "Failed to reply to msg_id=%s: code=%s msg=%s",
                msg_id,
                resp.code,
                resp.msg,
            )
            return False, f"Feishu API error: {resp.code} {resp.msg}"
        return True, None

    except Exception as exc:
        logger.exception("Exception replying to msg_id=%s: %s", msg_id, exc)
        return False, str(exc)
