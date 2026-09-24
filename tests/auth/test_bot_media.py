"""Три варианта оформления: первый вход, обычные экраны, главная."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from maxapi.types import InputMedia
from maxapi.types.updates.message_callback import MessageForCallback

from project.bot_media import (
    FIRST_START_IMAGE_PATH,
    OTHER_MESSAGES_IMAGE_PATH,
    first_start_image,
    install_bot_images,
)


def _bot() -> SimpleNamespace:
    return SimpleNamespace(
        send_message=AsyncMock(),
        edit_message=AsyncMock(),
        send_callback=AsyncMock(),
    )


def _image_path(attachments: list) -> str:
    assert attachments[0].type == "image"
    return attachments[0].path


def test_assets_exist() -> None:
    assert FIRST_START_IMAGE_PATH.is_file()
    assert OTHER_MESSAGES_IMAGE_PATH.is_file()
    assert FIRST_START_IMAGE_PATH != OTHER_MESSAGES_IMAGE_PATH


def test_ordinary_messages_keep_keyboard_and_use_second_image() -> None:
    bot = _bot()
    raw_send = bot.send_message
    install_bot_images(bot)
    asyncio.run(bot.send_message(chat_id=10, text="Выберите дом", attachments=["keyboard"]))
    sent = raw_send.await_args.kwargs
    assert _image_path(sent["attachments"]) == str(OTHER_MESSAGES_IMAGE_PATH)
    assert sent["attachments"][1] == "keyboard"


def test_initial_brand_is_not_replaced_and_home_is_not_decorated() -> None:
    bot = _bot()
    raw_send = bot.send_message
    install_bot_images(bot)
    asyncio.run(bot.send_message(chat_id=10, text="Привет", attachments=[first_start_image()]))
    assert _image_path(raw_send.await_args.kwargs["attachments"]) == str(FIRST_START_IMAGE_PATH)
    asyncio.run(bot.send_message(chat_id=10, text="<b>Главная</b>", attachments=["keyboard"]))
    assert raw_send.await_args.kwargs["attachments"] == ["keyboard"]


def test_callback_ack_does_not_upload_photo_but_screen_edit_does() -> None:
    bot = _bot()
    raw_callback = bot.send_callback
    install_bot_images(bot)
    asyncio.run(bot.send_callback(callback_id="abc", message=None))
    assert raw_callback.await_args.kwargs["message"] is None
    old = MessageForCallback(text="Улица", attachments=[])
    asyncio.run(bot.send_callback(callback_id="abc", message=old))
    sent = raw_callback.await_args.kwargs["message"]
    assert sent is not old
    assert _image_path(sent.attachments) == str(OTHER_MESSAGES_IMAGE_PATH)
    assert old.attachments == []


def test_edit_and_install_twice_do_not_double_attach() -> None:
    bot = _bot()
    raw_edit = bot.edit_message
    install_bot_images(bot)
    install_bot_images(bot)
    asyncio.run(bot.edit_message("mid", text="Дома", attachments=["keyboard"]))
    assert len(raw_edit.await_args.kwargs["attachments"]) == 2
    asyncio.run(
        bot.edit_message(
            "mid",
            text="Дома",
            attachments=[InputMedia(str(OTHER_MESSAGES_IMAGE_PATH), type="image")],
        )
    )
    assert len(raw_edit.await_args.kwargs["attachments"]) == 1
