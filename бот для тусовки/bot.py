import json
import logging
from html import escape
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ====== CONFIG ======
BOT_TOKEN = "8703264796:AAFmIbkXaZzWawngDZvjZeYGgSr7taA6bUM"
ADMIN_ID = 682426078
BARMEN_ID = 8502547596

CARDS = [
    "1111 2222 3333 4444",
    "5555 6666 7777 8888",
    "9999 0000 1111 2222",
    "3333 4444 5555 6666",
    "7777 8888 9999 0000",
]

STATE_FILE = Path("state.json")
MAIN_MENU_IMAGE_PATH = Path("imag/logo.jpg")

ADDRESS_TEXT = (
    "Ссылка на адрес в Яндекс картах https://yandex.ru/maps/-/CPvmvP1B\n"
    "г. Москва, Ольховская улица, 14с3"
)

DRINKS = {
    "Water": "Вода 0,5 - 100р.",
    "Cola": "Кола 0,5 - 100р.",
    "sprite": "Спрайт 0,5 - 100р.",
}

COCKTAILS = {
    "long_island": "Лонг-Айленд - 460р.",
    "mojito": "Мохито - 460р.",
    "rum_cola": "Ром с колой - 420р.",
    "tequila_sunrise": "Текила Санрайз - 350р.",
    "vodka_energy": "Водка с энергетиком - 350р.",
}

SHOTS = {
    "shots_12": "12 шотов за 1300р.",
    "shots_6": "6 шотов за 700р.",
    "shots_3": "3 шота за 400р.",
}


@dataclass
class Order:
    order_number: int
    customer_id: int
    customer_name: str
    item: str
    card: str
    status: str = "created"


orders: Dict[int, Order] = {}


def load_state() -> Dict[str, int]:
    if not STATE_FILE.exists():
        return {"order_counter": 0, "card_index": 0}
    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError, ValueError):
        return {"order_counter": 0, "card_index": 0}

    return {
        "order_counter": int(data.get("order_counter", 0)),
        "card_index": int(data.get("card_index", 0)),
    }


def save_state(state: Dict[str, int]) -> None:
    with STATE_FILE.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([["Меню бара🍹", "Наш адрес📍"]], resize_keyboard=True)


def category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Напитки🥤", callback_data="category:drinks")],
            [InlineKeyboardButton("Коктейль🍸", callback_data="category:cocktail")],
            [InlineKeyboardButton("Шоты", callback_data="category:shots")],
        ]
    )


def drinks_keyboard() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(name, callback_data=f"item:{key}")] for key, name in DRINKS.items()]
    buttons.append([InlineKeyboardButton("Назад", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(buttons)


def cocktails_keyboard() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(name, callback_data=f"item:{key}")] for key, name in COCKTAILS.items()]
    buttons.append([InlineKeyboardButton("Назад", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(buttons)


def shots_keyboard() -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(name, callback_data=f"item:{key}")] for key, name in SHOTS.items()]
    buttons.append([InlineKeyboardButton("Назад", callback_data="back_to_categories")])
    return InlineKeyboardMarkup(buttons)


def buyer_payment_keyboard(order_number: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Подтвердить оплату",
                    callback_data=f"pay_confirm:{order_number}",
                )
            ],
            [
                InlineKeyboardButton(
                    "Отменить заказ",
                    callback_data=f"cancel_order:{order_number}",
                )
            ],
        ]
    )


def admin_keyboard(order_number: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Подтвердить", callback_data=f"admin_ok:{order_number}"),
                InlineKeyboardButton("Отклонить", callback_data=f"admin_no:{order_number}"),
            ]
        ]
    )


def retry_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Повторить попытку", callback_data="retry_main")]])


def get_customer_name(update: Update) -> str:
    user = update.effective_user
    if user is None:
        return "unknown"
    if user.username:
        return f"@{user.username}"
    return str(user.id)


def next_order_number_and_card() -> Optional[tuple[int, str]]:
    if not CARDS:
        return None

    state = load_state()
    if state["order_counter"] >= 10000:
        return None

    state["order_counter"] += 1
    card = CARDS[state["card_index"] % len(CARDS)]
    state["card_index"] = (state["card_index"] + 1) % len(CARDS)
    save_state(state)
    return state["order_counter"], card


async def send_main_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    if MAIN_MENU_IMAGE_PATH.exists():
        with MAIN_MENU_IMAGE_PATH.open("rb") as image_file:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=image_file,
                caption="Добро пожаловать!🤗 Выберите нужный раздел:",
                reply_markup=main_menu_keyboard(),
            )
        return

    await context.bot.send_message(
        chat_id=chat_id,
        text="Добро пожаловать! Выберите нужный раздел:",
        reply_markup=main_menu_keyboard(),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat is None:
        return
    await send_main_menu(update.effective_chat.id, context)


async def menu_or_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return

    text = (update.message.text or "").strip()

    if text == "Наш адрес📍":
        await update.message.reply_text(ADDRESS_TEXT)
        return
    if text == "Меню бара🍹":
        await update.message.reply_text(
            "Что хотите заказать: Коктейль или Шоты?",
            reply_markup=category_keyboard(),
        )
        return

    await update.message.reply_text(
        "Пожалуйста, используйте кнопки: Меню бара или Наш адрес.",
        reply_markup=main_menu_keyboard(),
    )


async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    await query.answer()

    data = query.data
    if query.message is None:
        return

    if data == "category:cocktail":
        await query.edit_message_text("Выберите коктейль:", reply_markup=cocktails_keyboard())
        return

    if data == "category:drinks":
        await query.edit_message_text("Выберите напиток:", reply_markup=drinks_keyboard())
        return

    if data == "category:shots":
        await query.edit_message_text(
            "Выберите количество шотов:\n\n"
            "Вкусы: Малина, Яблоко, Облепиха.\n"
            "Выбор вкуса шота будет на баре.",
            reply_markup=shots_keyboard(),
        )
        return

    if data == "back_to_categories":
        await query.edit_message_text(
            "Что хотите заказать: Коктейль или Шоты?",
            reply_markup=category_keyboard(),
        )
        return

    if data.startswith("item:"):
        item_key = data.split(":", maxsplit=1)[1]
        item_name = DRINKS.get(item_key) or COCKTAILS.get(item_key) or SHOTS.get(item_key)
        if item_name is None or update.effective_user is None:
            return

        next_data = next_order_number_and_card()
        if next_data is None:
            await query.message.reply_text(
                "Невозможно оформить заказ: лимит номеров (1-10000) достигнут или карты не настроены."
            )
            return

        order_number, card = next_data
        customer_name = get_customer_name(update)
        orders[order_number] = Order(
            order_number=order_number,
            customer_id=update.effective_user.id,
            customer_name=customer_name,
            item=item_name,
            card=card,
        )

        comment_text = f"{customer_name} {order_number:05d}"
        text = (
            f"Ваш заказ: {item_name}\n"
            f"Номер заказа: {order_number:05d}\n\n"
            f"Карта для перевода: <code>{escape(card)}</code>\n"
            f"Комментарий к переводу (скопируйте):\n<code>{escape(comment_text)}</code>\n\n"
            "Нажимайте кнопку 'Подтвердить оплату' только ПОСЛЕ перевода денежных средств, "
            "иначе заказ могут отменить."
        )

        await query.message.delete()
        await query.message.chat.send_message(
            text=text,
            reply_markup=buyer_payment_keyboard(order_number),
            parse_mode="HTML",
        )
        return

    if data.startswith("cancel_order:"):
        order_number = int(data.split(":", maxsplit=1)[1])
        order = orders.get(order_number)
        if order is not None:
            order.status = "cancelled"
        await query.message.delete()
        await query.message.chat.send_message(
            "Заказ отменен. Возвращаем в меню бара.",
            reply_markup=category_keyboard(),
        )
        return

    if data.startswith("pay_confirm:"):
        order_number = int(data.split(":", maxsplit=1)[1])
        order = orders.get(order_number)
        if order is None:
            await query.message.reply_text("Заказ не найден или уже обработан.")
            return

        if update.effective_user is None or update.effective_user.id != order.customer_id:
            await query.message.reply_text("Подтвердить этот заказ может только покупатель.")
            return

        order.status = "waiting_admin"
        await query.message.reply_text("Ожидайте подтверждение.⏰")
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "Новый заказ на проверку оплаты:\n"
                f"Номер заказа: {order.order_number:05d}\n"
                f"Покупатель: {order.customer_name}\n"
                f"Позиция: {order.item}"
            ),
            reply_markup=admin_keyboard(order.order_number),
        )
        return

    if data.startswith("admin_ok:"):
        if update.effective_user is None or update.effective_user.id != ADMIN_ID:
            await query.message.reply_text("Эта кнопка доступна только администратору.")
            return

        order_number = int(data.split(":", maxsplit=1)[1])
        order = orders.get(order_number)
        if order is None:
            await query.message.reply_text("Заказ не найден.")
            return

        order.status = "approved"
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=order.customer_id,
            text=f"✅ Оплата подтверждена. Ваш заказ №{order.order_number:05d} принят! Ожидайте у бара. ✅",
        )
        await context.bot.send_message(
            chat_id=BARMEN_ID,
            text=(
                "Новый подтвержденный заказ:\n"
                f"Номер: {order.order_number:05d}\n"
                f"Позиция: {order.item}"
            ),
        )
        await query.message.reply_text("Заказ подтвержден и отправлен бармену.")
        return

    if data.startswith("admin_no:"):
        if update.effective_user is None or update.effective_user.id != ADMIN_ID:
            await query.message.reply_text("Эта кнопка доступна только администратору.")
            return

        order_number = int(data.split(":", maxsplit=1)[1])
        order = orders.get(order_number)
        if order is None:
            await query.message.reply_text("Заказ не найден.")
            return

        order.status = "rejected"
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=order.customer_id,
            text="❌ Оплата не пришла. Попробуйте снова. ❌",
            reply_markup=retry_keyboard(),
        )
        await query.message.reply_text("Заказ отклонен, покупатель уведомлен.")
        return

    if data == "retry_main":
        if update.effective_chat is None:
            return
        await send_main_menu(update.effective_chat.id, context)


def validate_config() -> None:
    if BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN":
        raise ValueError("Укажите BOT_TOKEN в файле bot.py")
    if ADMIN_ID == 123456789:
        raise ValueError("Укажите реальный ADMIN_ID в файле bot.py")
    if BARMEN_ID == 987654321:
        raise ValueError("Укажите реальный BARMEN_ID в файле bot.py")
    if not CARDS:
        raise ValueError("Добавьте хотя бы одну карту в список CARDS")


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=logging.INFO,
    )
    validate_config()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_or_address))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.run_polling()


if __name__ == "__main__":
    main()
