"""Три варианта оформления: первый вход, обычные экраны, главная."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from maxapi.enums.upload_type import UploadType
from maxapi.types import InputMedia
from maxapi.types.attachments.upload import AttachmentPayload, AttachmentUpload

from project.bot_media import (
    FIRST_START_IMAGE_PATH,
    OTHER_MESSAGES_IMAGE_PATH,
    first_start_image,
    install_bot_images,
    warm_bot_images,
)


def _bot() -> SimpleNamespace:
    return SimpleNamespace(
        send_message=AsyncMock(),
        edit_message=AsyncMock(),
        send_callback=AsyncMock(),
        upload_media=AsyncMock(
            side_effect=lambda media: AttachmentUpload(
                type=UploadType.IMAGE,
                payload=AttachmentPayload(token=f"tok-{Path(media.path).name}"),
            )
        ),
    )


def _image_token_or_path(attachments: list) -> str:
    item = attachments[0]
    if isinstance(item, InputMedia):
        return item.path
    return item.payload.token


def test_assets_exist() -> None:
    assert FIRST_START_IMAGE_PATH.is_file()
    assert OTHER_MESSAGES_IMAGE_PATH.is_file()
    assert FIRST_START_IMAGE_PATH != OTHER_MESSAGES_IMAGE_PATH


def test_brand_image_is_opt_in() -> None:
    bot = _bot()
    raw_send = bot.send_message
    install_bot_images(bot)
    asyncio.run(bot.send_message(chat_id=10, text="Выберите дом", attachments=["keyboard"]))
    assert raw_send.await_args.kwargs["attachments"] == ["keyboard"]
    asyncio.run(
        bot.send_message(
            chat_id=10, text="Выберите дом", attachments=["keyboard"], brand_image=True
        )
    )
    sent = raw_send.await_args.kwargs
    assert _image_token_or_path(sent["attachments"]).endswith("other_messages.webp")
    assert sent["attachments"][1] == "keyboard"


def test_initial_brand_is_not_replaced_and_home_is_not_decorated() -> None:
    bot = _bot()
    raw_send = bot.send_message
    install_bot_images(bot)
    asyncio.run(bot.send_message(chat_id=10, text="Привет", attachments=[first_start_image()]))
    assert _image_token_or_path(raw_send.await_args.kwargs["attachments"]).endswith(
        "first_start.webp"
    )
    asyncio.run(bot.send_message(chat_id=10, text="<b>Главная</b>", attachments=["keyboard"]))
    assert raw_send.await_args.kwargs["attachments"] == ["keyboard"]


def test_edit_does_not_reupload_brand_image() -> None:
    bot = _bot()
    raw_edit = bot.edit_message
    install_bot_images(bot)
    asyncio.run(raw_edit("mid", text="Дома", attachments=["keyboard"]))
    assert raw_edit.await_args.kwargs["attachments"] == ["keyboard"]


def test_warm_images_reuse_upload_token() -> None:
    bot = _bot()
    asyncio.run(warm_bot_images(bot))
    assert bot.upload_media.await_count == 3
    cached = first_start_image(bot)
    assert isinstance(cached, AttachmentUpload)
    assert cached.payload.token.startswith("tok-")
    raw_send = bot.send_message
    install_bot_images(bot)
    asyncio.run(
        bot.send_message(
            chat_id=10, text="Выберите дом", attachments=["keyboard"], brand_image=True
        )
    )
    assert isinstance(raw_send.await_args.kwargs["attachments"][0], AttachmentUpload)


def test_priority_notify_text_is_not_decorated() -> None:
    bot = _bot()
    raw_send = bot.send_message
    install_bot_images(bot)
    asyncio.run(bot.send_message(chat_id=10, text="🔴 Отключение воды", attachments=["keyboard"]))
    assert raw_send.await_args.kwargs["attachments"] == ["keyboard"]
    asyncio.run(
        bot.send_message(
            chat_id=10,
            text="Дайджест чата",
            attachments=["keyboard"],
            brand_image=False,
        )
    )
    assert raw_send.await_args.kwargs["attachments"] == ["keyboard"]
    assert "brand_image" not in raw_send.await_args.kwargs
