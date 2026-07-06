import os
import json
from dotenv import load_dotenv
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS_RAW = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS = [int(u.strip()) for u in ALLOWED_USERS_RAW.split(",") if u.strip().isdigit()]

bot = telebot.TeleBot(BOT_TOKEN)
DATA_FILE = "trackers.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def check_permission(message):
    user_id = message.from_user.id
    if user_id not in ALLOWED_USERS:
        bot.reply_to(message, "У вас нет доступа к этому боту.")
        return False
    return True

def get_main_keyboard(user_id):
    data = load_data()
    user_titles = data.get(str(user_id), [])
    
    markup = InlineKeyboardMarkup()
    
    # Добавляем кнопки для удаления существующих тайтлов
    for title_id in user_titles:
        markup.add(InlineKeyboardButton(text=f"❌ Удалить ID: {title_id}", callback_data=f"del_{title_id}"))
        
    markup.add(InlineKeyboardButton(text="➕ Добавить ID тайтла", callback_data="add_id"))
    return markup

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if not check_permission(message):
        return
        
    user_id = message.from_user.id
    bot.send_message(
        message.chat.id,
        "Привет! Я бот для отслеживания тайтлов.\nВот ваши текущие отслеживаемые ID:",
        reply_markup=get_main_keyboard(user_id)
    )

@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    if call.from_user.id not in ALLOWED_USERS:
        bot.answer_callback_query(call.id, "У вас нет доступа к этому боту.", show_alert=True)
        return

    user_id = call.from_user.id
    data = call.data

    if data == "add_id":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "Пожалуйста, введите ID тайтла для добавления:")
        bot.register_next_step_handler(msg, process_add_id)
    elif data.startswith("del_"):
        title_to_del = data.split("_")[1]
        all_data = load_data()
        user_titles = all_data.get(str(user_id), [])
        
        if title_to_del in user_titles:
            user_titles.remove(title_to_del)
            all_data[str(user_id)] = user_titles
            save_data(all_data)
            bot.answer_callback_query(call.id, f"ID {title_to_del} успешно удален!")
        else:
            bot.answer_callback_query(call.id, "Этот ID уже не отслеживается.")
            
        bot.edit_message_reply_markup(
            chat_id=call.message.chat.id,
            message_id=call.message.id,
            reply_markup=get_main_keyboard(user_id)
        )

def process_add_id(message):
    if not check_permission(message):
        return
        
    user_id = message.from_user.id
    new_id = message.text.strip()
    
    if not new_id:
        bot.reply_to(message, "ID не может быть пустым.")
        return
        
    all_data = load_data()
    user_titles = all_data.get(str(user_id), [])
    
    if new_id in user_titles:
        bot.reply_to(message, f"ID {new_id} уже отслеживается.", reply_markup=get_main_keyboard(user_id))
    else:
        user_titles.append(new_id)
        all_data[str(user_id)] = user_titles
        save_data(all_data)
        bot.send_message(
            message.chat.id,
            f"ID {new_id} успешно добавлен для отслеживания!",
            reply_markup=get_main_keyboard(user_id)
        )

if __name__ == "__main__":
    print("Бот запущен...")
    bot.infinity_polling()
