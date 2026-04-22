import itertools
import json
import logging
import re
from html import escape
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
ADMIN_IDS = [1849157614, 1912631413]
BARMEN_IDS = [1720094364, 5798808763]

CARDS: Dict[str, List[str]] = {
    "tbank": [
        "https://tbank.ru/cf/223D77JNlDy",
        "https://tbank.ru/cf/6nMBJUr7uaZ",
    ],
    "sber": [
        "https://messenger.online.sberbank.ru/sl/4SSTauqBPhN0caLGu",
        "https://messenger.online.sberbank.ru/sl/bwXl4bE9Qdjr5TpCA",
    ],
    "ozon": [
        "https://finance.ozon.ru/apps/sbp/ozonbankpay/019db14a-cc21-7e06-b876-d6c418d94abc",
    ],
}

# Цикличные итераторы: каждое нажатие на банк отдаёт следующую ссылку по кругу
CARD_CYCLES: Dict[str, itertools.cycle] = {
    key: itertools.cycle(urls) for key, urls in CARDS.items()
}

BANK_BUTTONS: List[Tuple[str, str]] = [
    ("Тбанк", "tbank"),
    ("Сбер", "sber"),
    ("OZON", "ozon"),
]

STATE_FILE = Path("state.json")
MAIN_MENU_IMAGE_PATH = Path("imag/logo.jpg")
BAR_MENU_IMAGE_CANDIDATES = [
    Path("imag/menu.jpg")
]

ADDRESS_TEXT = (
    "Ссылка на адрес в Яндекс картах https://yandex.ru/maps/-/CPvmvP1B\n"
    "г. Москва, Ольховская улица, 14с3"
)

DRINKS = {
    "Water": "Святой источник 0,5 - 100р.",
}

COCKTAILS = {
    "long_island": "Лонг-Айленд - 460р.",
    "mojito": "Мохито - 460р.",
    "rum_cola": "Рома без колой - 420р.",
    "tequila_sunrise": "Текила Санрайз - 350р.",
    "vodka_energy": "Водка с энергетиком - 350р.",
}

SHOTS = {
    "shots_12": "12 шотов за 1320р.",
    "shots_6": "6 шотов за 700р.",
    "shots_3": "3 шота за 400р.",
}


@dataclass
class Order:
    order_number: int
    customer_id: int
    customer_name: str
    items: List[str]
    total_amount: int
    admin_id: int
    barmen_id: int
    card: str = ""
    bank_name: str = ""
    status: str = "created"


orders: Dict[int, Order] = {}
carts: Dict[int, List[str]] = {}


def load_state() -> Dict[str, int]:
    if not STATE_FILE.exists():
        return {"order_counter": 0, "admin_index": 0, "barmen_index": 0}
    try:
        with STATE_FILE.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError, ValueError):
        return {"order_counter": 0, "admin_index": 0, "barmen_index": 0}

    return {
        "order_counter": int(data.get("order_counter", 0)),
        "admin_index": int(data.get("admin_index", 0)),
        "barmen_index": int(data.get("barmen_index", 0)),
    }


def save_state(state: Dict[str, int]) -> None:
    with STATE_FILE.open("w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [["Заказать напиток"], ["Корзина🛒"]],
        resize_keyboard=True,
    )


def category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Вода🧊", callback_data="category:drinks")],
            [InlineKeyboardButton("Коктейль🍸", callback_data="category:cocktail")],
            [InlineKeyboardButton("Шоты🥛", callback_data="category:shots")],
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


def bank_selection_keyboard(order_number: int) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for bank_name, bank_key in BANK_BUTTONS:
        rows.append([InlineKeyboardButton(bank_name, callback_data=f"pay_bank:{order_number}:{bank_key}")])
    rows.append([InlineKeyboardButton("Отменить заказ", callback_data=f"cancel_order:{order_number}")])
    return InlineKeyboardMarkup(rows)


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


def cart_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Оплатить заказ", callback_data="checkout_cart")],
            [InlineKeyboardButton("Очистить корзину", callback_data="clear_cart")],
        ]
    )


def after_add_to_cart_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Выбрать ещё позицию", callback_data="continue_shopping")],
            [InlineKeyboardButton("Перейти к оплате", callback_data="go_to_cart")],
        ]
    )


def get_customer_name(update: Update) -> str:
    user = update.effective_user
    if user is None:
        return "unknown"
    if user.username:
        return f"@{user.username}"
    return str(user.id)


def next_order_assignment() -> Optional[tuple[int, int, int]]:
    if not ADMIN_IDS or not BARMEN_IDS:
        return None

    state = load_state()
    if state["order_counter"] >= 10000:
        return None

    state["order_counter"] += 1
    admin_id = ADMIN_IDS[state["admin_index"] % len(ADMIN_IDS)]
    barmen_id = BARMEN_IDS[state["barmen_index"] % len(BARMEN_IDS)]
    state["admin_index"] = (state["admin_index"] + 1) % len(ADMIN_IDS)
    state["barmen_index"] = (state["barmen_index"] + 1) % len(BARMEN_IDS)
    save_state(state)
    return state["order_counter"], admin_id, barmen_id


def extract_item_price(item_name: str) -> int:
    rub_match = re.search(r"(\d+)\s*р\.?", item_name, flags=re.IGNORECASE)
    if rub_match:
        return int(rub_match.group(1))

    all_numbers = re.findall(r"\d+", item_name)
    if not all_numbers:
        return 0
    return int(all_numbers[-1])


def cart_text(items: List[str]) -> str:
    if not items:
        return "Ваша корзина пока пуста."

    lines = ["Ваша корзина:"]
    total = 0
    for idx, item in enumerate(items, start=1):
        price = extract_item_price(item)
        total += price
        lines.append(f"{idx}. {item} ({price}р.)")
    lines.append("")
    lines.append(f"Итого: {total}р.")
    return "\n".join(lines)


def top_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Меню бара🍹", callback_data="top:bar_menu"),
                InlineKeyboardButton("Наш адрес📍", callback_data="top:address"),
            ]
        ]
    )


async def send_main_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE) -> None:
    if MAIN_MENU_IMAGE_PATH.exists():
        with MAIN_MENU_IMAGE_PATH.open("rb") as image_file:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=image_file,
                caption="Добро пожаловать!🤗 Выберите нужный раздел:",
                reply_markup=top_inline_keyboard(),
            )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text="Добро пожаловать! Выберите нужный раздел:",
            reply_markup=top_inline_keyboard(),
        )

    await context.bot.send_message(
        chat_id=chat_id,
        text="Выберите действие:",
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

    if text == "Заказать напиток":
        await update.message.reply_text(
            "Что хотите заказать: Коктейль или Шоты?",
            reply_markup=category_keyboard(),
        )
        return
    if text == "Корзина🛒":
        if update.effective_user is None:
            return
        user_cart = carts.get(update.effective_user.id, [])
        if not user_cart:
            await update.message.reply_text("Ваша корзина пока пуста.")
            return
        await update.message.reply_text(cart_text(user_cart), reply_markup=cart_keyboard())
        return

    await update.message.reply_text(
        "Пожалуйста, используйте кнопки: Меню бара, Заказать напиток, Корзина или Наш адрес.",
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

    if data == "top:address":
        await query.message.reply_text(ADDRESS_TEXT)
        return

    if data == "top:bar_menu":
        menu_image_path = next((path for path in BAR_MENU_IMAGE_CANDIDATES if path.exists()), None)
        if menu_image_path is not None:
            with menu_image_path.open("rb") as image_file:
                await query.message.reply_photo(photo=image_file, caption="Актуальное меню бара:")
        else:
            await query.message.reply_text("Файл меню не найден. Проверьте путь к menu.jpg.")
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
            "Вкусы: Малина, Гранат, Блю Кюрасао.\n"
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

    if data == "continue_shopping":
        await query.edit_message_text(
            "Что хотите заказать: Коктейль или Шоты?",
            reply_markup=category_keyboard(),
        )
        return

    if data == "go_to_cart":
        if update.effective_user is None:
            return
        user_cart = carts.get(update.effective_user.id, [])
        if not user_cart:
            await query.edit_message_text("Ваша корзина пока пуста.")
            return
        await query.edit_message_text(cart_text(user_cart), reply_markup=cart_keyboard())
        return

    if data.startswith("item:"):
        item_key = data.split(":", maxsplit=1)[1]
        item_name = DRINKS.get(item_key) or COCKTAILS.get(item_key) or SHOTS.get(item_key)
        if item_name is None or update.effective_user is None:
            return

        user_cart = carts.setdefault(update.effective_user.id, [])
        user_cart.append(item_name)
        await query.message.delete()
        await query.message.chat.send_message(
            text=f"Товар добавлен в корзину: {item_name}\n\nВыберите следующее действие:",
            reply_markup=after_add_to_cart_keyboard(),
        )
        return

    if data == "clear_cart":
        if update.effective_user is None:
            return
        carts.pop(update.effective_user.id, None)
        await query.edit_message_text("Корзина очищена.")
        return

    if data == "checkout_cart":
        if update.effective_user is None:
            return
        user_cart = carts.get(update.effective_user.id, [])
        if not user_cart:
            await query.edit_message_text("Ваша корзина пуста, добавьте позиции из меню бара.")
            return

        next_data = next_order_assignment()
        if next_data is None:
            await query.message.reply_text(
                "Невозможно оформить заказ: лимит номеров (1-10000) достигнут или карты/админы/бармены не настроены."
            )
            return

        order_number, admin_id, barmen_id = next_data
        customer_name = get_customer_name(update)
        total_amount = sum(extract_item_price(item) for item in user_cart)
        orders[order_number] = Order(
            order_number=order_number,
            customer_id=update.effective_user.id,
            customer_name=customer_name,
            items=user_cart.copy(),
            total_amount=total_amount,
            admin_id=admin_id,
            barmen_id=barmen_id,
        )

        order_items = "\n".join(f"- {item}" for item in user_cart)
        text = (
            f"Ваш заказ №{order_number:05d}:\n{order_items}\n\n"
            f"Итого к оплате: {total_amount}р.\n"
            "Выберите банк для получения ссылки на оплату:"
        )

        carts.pop(update.effective_user.id, None)
        await query.message.delete()
        await query.message.chat.send_message(
            text=text,
            reply_markup=bank_selection_keyboard(order_number),
            parse_mode="HTML",
        )
        return

    if data.startswith("pay_bank:"):
        parts = data.split(":", maxsplit=2)
        if len(parts) != 3:
            await query.message.reply_text("Некорректные данные оплаты.")
            return
        order_number = int(parts[1])
        bank_key = parts[2]
        order = orders.get(order_number)
        if order is None:
            await query.message.reply_text("Заказ не найден или уже обработан.")
            return

        if update.effective_user is None or update.effective_user.id != order.customer_id:
            await query.message.reply_text("Выбор банка доступен только покупателю.")
            return

        cycle = CARD_CYCLES.get(bank_key)
        payment_url = next(cycle).strip() if cycle else ""
        bank_name = next((name for name, key in BANK_BUTTONS if key == bank_key), bank_key)
        if not payment_url:
            await query.answer("Ссылка для этого банка пока не настроена.", show_alert=True)
            return

        order.card = payment_url
        order.bank_name = bank_name
        comment_text = f"{order.customer_name} {order.order_number:05d}"
        text = (
            f"Заказ №{order.order_number:05d}\n"
            f"Банк: {bank_name}\n"
            f"Ссылка на оплату:\n{escape(payment_url)}\n\n"
            f"Комментарий к переводу (скопируйте):\n<code>{escape(comment_text)}</code>\n\n"
            "Нажимайте кнопку 'Подтвердить оплату' только ПОСЛЕ перевода денежных средств, "
            "иначе заказ могут отменить."
        )
        await query.edit_message_text(
            text=text,
            reply_markup=buyer_payment_keyboard(order.order_number),
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
        if not order.card:
            await query.message.reply_text("Сначала выберите банк и получите ссылку на оплату.")
            return

        if update.effective_user is None or update.effective_user.id != order.customer_id:
            await query.message.reply_text("Подтвердить этот заказ может только покупатель.")
            return

        order.status = "waiting_admin"
        await query.message.delete()
        await query.message.reply_text("Ожидайте подтверждение.⏰")
        await context.bot.send_message(
            chat_id=order.admin_id,
            text=(
                "Новый заказ на проверку оплаты:\n"
                f"Номер заказа: {order.order_number:05d}\n"
                f"Покупатель: {order.customer_name}\n"
                f"Позиции:\n" + "\n".join(f"- {item}" for item in order.items) + "\n"
                f"Сумма: {order.total_amount}р."
            ),
            reply_markup=admin_keyboard(order.order_number),
        )
        return

    if data.startswith("admin_ok:"):
        order_number = int(data.split(":", maxsplit=1)[1])
        order = orders.get(order_number)
        if order is None:
            await query.message.reply_text("Заказ не найден.")
            return
        if update.effective_user is None or update.effective_user.id != order.admin_id:
            await query.message.reply_text("Этот заказ может подтвердить только назначенный администратор.")
            return

        order.status = "approved"
        await query.edit_message_reply_markup(reply_markup=None)
        await context.bot.send_message(
            chat_id=order.customer_id,
            text=f"✅ Оплата подтверждена. Ваш заказ №{order.order_number:05d} принят! Ожидайте у бара. ✅",
        )
        await context.bot.send_message(
            chat_id=order.barmen_id,
            text=(
                "Новый подтвержденный заказ:\n"
                f"Номер: {order.order_number:05d}\n"
                f"Позиции:\n" + "\n".join(f"- {item}" for item in order.items) + "\n"
                f"Сумма: {order.total_amount}р."
            ),
        )
        await query.message.reply_text("Заказ подтвержден и отправлен бармену.")
        return

    if data.startswith("admin_no:"):
        order_number = int(data.split(":", maxsplit=1)[1])
        order = orders.get(order_number)
        if order is None:
            await query.message.reply_text("Заказ не найден.")
            return
        if update.effective_user is None or update.effective_user.id != order.admin_id:
            await query.message.reply_text("Этот заказ может отклонить только назначенный администратор.")
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
    if not ADMIN_IDS:
        raise ValueError("Добавьте хотя бы одного администратора в ADMIN_IDS")
    if not BARMEN_IDS:
        raise ValueError("Добавьте хотя бы одного бармена в BARMEN_IDS")
    if not CARDS:
        raise ValueError("Добавьте хотя бы одну ссылку в CARDS")


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