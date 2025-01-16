from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, ChatMemberHandler, MessageHandler, filters
import random
import asyncio
import time
import requests
import re
import json

# Шансы и множители для каждого дракона
dragons = {
    'red': {'chance': 50, 'multiplier': 2, 'emoji': '🐉 Красный'},
    'green': {'chance': 30, 'multiplier': 3, 'emoji': '🐲 Зелёный'},
    'black': {'chance': 10, 'multiplier': 5, 'emoji': '🐍 Чёрный'}
}

allowed_chat_id = -1002443174653  # ID супергруппы SQUID TEST
allowed_topic_title = "Dragon"  # Название топика, где разрешена игра
allowed_topic_id = 315  # Предустановленный Message Thread ID для топика

# Словарь для хранения ставок игроков
player_bets = {}
timer_messages = {}

# Словарь для хранения балансов и адресов пользователей
user_data = {}  # Формат: {user_id: {'balance': 0, 'wallet_address': None}}

SOL_TOKEN_CONTRACT = "9t2LggMNdyhCGmtKH617WzJjLagLEaj7MNzvvucwpump"  # Адрес контракта монеты SOL
bank_wallet_address = "3ypZUE9CyaeDHFEBbACEiNaj3CZws2dpY28PGkYfueii"  # Адрес банка для депозита
solscan_api_key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjcmVhdGVkQXQiOjE3MzcwMjIxNTc2ODgsImVtYWlsIjoiaXZhbmZyb2xvdnZANjYyNC5ydSIsImFjdGlvbiI6InRva2VuLWFwaSIsImFwaVZlcnNpb24iOiJ2MiIsImlhdCI6MTczNzAyMjE1N30.faQFC9ksCH0QW14gOTqvgxzkTOriQB8hExQmyMqu7aI"  # API ключ Solscan

DATA_FILE = 'user_data.json'

def load_user_data():
    global user_data
    try:
        with open(DATA_FILE, 'r') as file:
            user_data = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        user_data = {}


def save_user_data():
    with open(DATA_FILE, 'w') as file:
        json.dump(user_data, file, indent=4)  # добавлен отступ для улучшения читаемости
    print("Данные сохранены:", user_data)  # Печать в консоль для проверки

# ==========================
# Game-related handlers
# ==========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        await update.message.reply_text("Эта игра доступна только в чате Dragon.")
        return
    welcome_message = """
        🎉 Добро пожаловать в игру *Ставка на Дракона*!

        Сделайте ставку на одного из трёх драконов и получите шанс выиграть больше монет!
        🐉 Красный дракон: шанс 50%, x2 ставки
        🐲 Зелёный дракон: шанс 30%, x3 ставки
        🐍 Чёрный дракон: шанс 10%, x5 ставки
    """
    keyboard = [
        [InlineKeyboardButton("Старт", callback_data='start_game')],
        [InlineKeyboardButton("Баланс", callback_data='balance'), InlineKeyboardButton("Пополнение", callback_data='deposit_info')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_allowed_chat(update):
        await query.answer("Эта игра доступна только в чате Dragon.", show_alert=True)
        return
    keyboard = [
        [InlineKeyboardButton(f"{dragons['red']['emoji']} (шанс {dragons['red']['chance']}%)", callback_data='bet_red')],
        [InlineKeyboardButton(f"{dragons['green']['emoji']} (шанс {dragons['green']['chance']}%)", callback_data='bet_green')],
        [InlineKeyboardButton(f"{dragons['black']['emoji']} (шанс {dragons['black']['chance']}%)", callback_data='bet_black')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("Выберите дракона для ставки:", reply_markup=reply_markup)

async def place_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_allowed_chat(update):
        await query.answer("Эта игра доступна только в чате Dragon.", show_alert=True)
        return
    user_id = query.from_user.id
    chat_id = update.effective_chat.id
    dragon_color = query.data.split('_')[1]

    if user_id in player_bets:
        await query.answer("❌ Вы уже сделали ставку!")
        return

    bet_amount = 10
    if user_data.get(user_id, {}).get('balance', 0) < bet_amount:
        await query.answer("❌ Недостаточно средств на балансе! Пополните баланс.")
        return

    user_data[user_id]['balance'] -= bet_amount
    save_user_data()
    player_bets[user_id] = {'dragon': dragon_color, 'bet': bet_amount}
    await query.edit_message_text(f"Вы выбрали {dragons[dragon_color]['emoji']} дракона со ставкой {bet_amount} монет.\n💡 Подождите окончания раунда!")

    start_time = time.time()
    context.job_queue.run_once(finish_game, 30, data={'chat_id': chat_id, 'start_time': start_time})
    context.job_queue.run_repeating(show_timer, 5, data={'chat_id': chat_id, 'duration': 30, 'start_time': start_time})
/////
async def animate_result(context: ContextTypes.DEFAULT_TYPE):
    job_data = context.job.data
    chat_id = job_data['chat_id']
    result_dragon = job_data['result_dragon']
    result_message = job_data['result_message']

    for i in range(3):
        await context.bot.send_message(
            chat_id=chat_id,
            message_thread_id=allowed_topic_id,
            text=f"🐇 Гонка драконов: {' '.join(['💨'] * (i + 1))}"
        )
        await asyncio.sleep(1)
    await context.bot.send_message(
        chat_id=chat_id,
        message_thread_id=allowed_topic_id,
        text=f"📢 Победил {dragons[result_dragon]['emoji']} дракон!"
    )
    await context.bot.send_message(
        chat_id=chat_id,
        message_thread_id=allowed_topic_id,
        text=result_message,
        parse_mode='HTML'
    )
    await start_new_game(context, chat_id)

async def start_new_game(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    keyboard = [
        [InlineKeyboardButton(f"{dragons['red']['emoji']} (шанс {dragons['red']['chance']}%)", callback_data='bet_red')],
        [InlineKeyboardButton(f"{dragons['green']['emoji']} (шанс {dragons['green']['chance']}%)", callback_data='bet_green')],
        [InlineKeyboardButton(f"{dragons['black']['emoji']} (шанс {dragons['black']['chance']}%)", callback_data='bet_black')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=chat_id, message_thread_id=allowed_topic_id, text="Начнем новую игру! Выберите дракона:", reply_markup=reply_markup)

async def finish_game(context: ContextTypes.DEFAULT_TYPE):
    result_dragon = random.choices(list(dragons.keys()), [50, 30, 10])[0]
    result_message = f"📢 Игра окончена! Победил {dragons[result_dragon]['emoji']} дракон!\n"
    total_payouts = []

    for user_id, bet in player_bets.items():
        if bet['dragon'] == result_dragon:
            payout = bet['bet'] * dragons[result_dragon]['multiplier']
            user_data[user_id]['balance'] += payout
            total_payouts.append(f"<a href='tg://user?id={user_id}'>Игрок</a> выиграл {payout} монет!")
        else:
            total_payouts.append(f"<a href='tg://user?id={user_id}'>Игрок</a> проиграл свои монеты.")
    save_user_data()
    result_message += "\n" + "\n".join(total_payouts)
    player_bets.clear()

    context.job_queue.run_once(
        animate_result,
        0,
        data={'chat_id': context.job.data['chat_id'], 'result_dragon': result_dragon, 'result_message': result_message}
    )

# ==========================
# Balance and wallet handlers
# ==========================
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    balance = user_data.get(user_id, {}).get('balance', 0)
    wallet = user_data.get(user_id, {}).get('wallet_address', 'Не установлен')
    keyboard = [
        [InlineKeyboardButton("Назад", callback_data='start_game'), InlineKeyboardButton("Указать адрес", callback_data='set_wallet')],
        [InlineKeyboardButton("В начало", callback_data='main_menu')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.answer()
    await query.edit_message_text(f"Ваш баланс: {balance} монет\nВаш адрес кошелька: {wallet}", reply_markup=reply_markup)

async def set_wallet_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [[InlineKeyboardButton("Назад", callback_data='balance'), InlineKeyboardButton("В начало", callback_data='main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.answer()
    await query.edit_message_text("Введите адрес кошелька с помощью команды: /set_wallet <адрес>", reply_markup=reply_markup)

async def set_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) != 1:
        await update.message.reply_text("Пожалуйста, укажите только один адрес кошелька.")
        return
    wallet_address = context.args[0]
    
    # Сохранение кошелька в словарь пользователя
    user_data.setdefault(user_id, {'balance': 0})['wallet_address'] = wallet_address
    save_user_data()  # Сохраняем изменения в файл

    keyboard = [[InlineKeyboardButton("Кошелек", callback_data='balance'), InlineKeyboardButton("В начало", callback_data='main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Адрес кошелька {wallet_address} успешно установлен.", reply_markup=reply_markup)

async def show_deposit_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = [[InlineKeyboardButton("Назад", callback_data='balance'), InlineKeyboardButton("В начало", callback_data='main_menu')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.answer()
    await query.edit_message_text(
        f"Для пополнения баланса переведите Squid Bingo (SQUID) монеты на игровой адрес:\n{bank_wallet_address}\n"
        "После перевода используйте команду /check_deposit для обновления баланса.", reply_markup=reply_markup
    )
/////
# ==========================
# Deposit checking function
# ==========================
async def check_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet_address = user_data.get(user_id, {}).get('wallet_address')

    if not wallet_address:
        await update.message.reply_text("❌ Сначала укажите свой адрес кошелька с помощью команды /set_wallet <адрес>.")
        return

    # Получаем транзакции по адресу
    transactions = check_transaction_history(wallet_address)
    if not transactions:
        await update.message.reply_text("❌ Нет новых транзакций. Попробуйте позже.")
        return

    deposit_found = False
    # Проходим по транзакциям
    for tx in transactions:
        # Если транзакция от указанного пользователя и успешна
        if tx.get('source') == wallet_address and tx.get('status') == 'success':
            amount = tx.get('amount', 0)
            user_data[user_id]['balance'] += amount  # Пополняем баланс пользователя
            deposit_found = True
            save_user_data()  # Сохраняем обновленные данные
            break

    if deposit_found:
        await update.message.reply_text(f"✅ Баланс успешно пополнен! Ваш новый баланс: {user_data[user_id]['balance']} монет.")
    else:
        await update.message.reply_text("❌ Транзакция не найдена. Убедитесь, что отправили монеты на правильный адрес.")

# ==========================
# Utility and general handlers
# ==========================
def check_transaction_history(address: str):
    url = f"https://api.solscan.io/account/splTransfers?account={address}&contract={SOL_TOKEN_CONTRACT}"
    headers = {"accept": "application/json", "Authorization": f"Bearer {solscan_api_key}"}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get('data', [])
    return []

async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type
    chat_title = update.effective_chat.title
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    await update.message.reply_text(
        f"Chat ID: {chat_id}\nChat Type: {chat_type}\nChat Title: {chat_title}\nMessage Thread ID: {message_thread_id}"
    )

async def set_topic_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global allowed_topic_id
    allowed_topic_id = update.effective_message.message_thread_id if update.effective_message else None
    await update.message.reply_text(f"Message Thread ID установлен: {allowed_topic_id}")

def is_allowed_chat(update: Update) -> bool:
    chat = update.effective_chat
    message_thread_id = update.effective_message.message_thread_id if update.effective_message else None
    return chat.id == allowed_chat_id and message_thread_id == allowed_topic_id

async def greet_new_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.chat_member.new_chat_members:
        if not member.is_bot:
            welcome_text = f"Добро пожаловать, {member.first_name}! Нажмите 'Старт', чтобы сыграть!"
            keyboard = [[InlineKeyboardButton("Старт", callback_data='start_game')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=welcome_text,
                reply_markup=reply_markup
            )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    wallet_address = update.message.text.strip()

    # Проверка на корректность адреса кошелька
    if re.fullmatch(r'[1-9A-HJ-NP-Za-km-z]{32,44}', wallet_address):
        # Сохранение кошелька в словарь пользователя
        user_data.setdefault(user_id, {'balance': 0})['wallet_address'] = wallet_address
        save_user_data()  # Сохраняем изменения в файл
        await update.message.reply_text(f"Адрес кошелька {wallet_address} успешно установлен.")
    else:
        await update.message.reply_text("Введённый текст не является корректным адресом кошелька.")

if __name__ == '__main__':
    load_user_data()
    app = ApplicationBuilder().token('7881851539:AAH4km0NsrKacgQsVpAvJwiFWt6m2hiXJ1U').build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('get_chat_id', get_chat_id))
    app.add_handler(CommandHandler('set_topic_id', set_topic_id))
    app.add_handler(CommandHandler('balance', show_balance))
    app.add_handler(CommandHandler('set_wallet', set_wallet))
    app.add_handler(CallbackQueryHandler(start_game, pattern='^start_game$'))
    app.add_handler(CallbackQueryHandler(show_balance, pattern='^balance$'))
    app.add_handler(CallbackQueryHandler(set_wallet_prompt, pattern='^set_wallet$'))
    app.add_handler(CallbackQueryHandler(show_deposit_info, pattern='^deposit_info$'))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(place_bet, pattern='^bet_(red|green|black)$'))
    app.add_handler(ChatMemberHandler(greet_new_user, ChatMemberHandler.CHAT_MEMBER))

    app.run_polling()
