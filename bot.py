import os
import json
import time
import threading
from dotenv import load_dotenv
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from urllib3.exceptions import ProtocolError
from requests.exceptions import ConnectionError
import fcm_receiver
import re

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USERS_RAW = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS = [int(u.strip()) for u in ALLOWED_USERS_RAW.split(",") if u.strip().isdigit()]

bot = telebot.TeleBot(BOT_TOKEN)
DATA_FILE = "trackers.json"
FCM_KEYS_FILE = "fcm_keys.json"

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
        "Привет! Я бот для отслеживания тайтлов Anilibria через пуш-уведомления Firebase (FCM).\nВот ваши текущие отслеживаемые ID:",
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

def run_fcm_listener():
    client = fcm_receiver.FCMClient()
    client.app_id = "1:500586946614:android:7d9606acda0283a1"
    client.project_id = "anilibria-app"
    client.api_key = "AIzaSyC0hPAsvfeyVEUq9HlXPtKOghw2mVxc798"

    # Загружаем ключи из файла или регистрируем новые, чтобы не делать checkin каждый раз
    if os.path.exists(FCM_KEYS_FILE):
        try:
            with open(FCM_KEYS_FILE, "r") as f:
                keys = json.load(f)
                client.android_id = keys["android_id"]
                client.security_token = keys["security_token"]
                client.gcm_token = keys["gcm_token"]
                client.fcm_token = keys["fcm_token"]
                
                # Загружаем PEM ключи обратно в объекты
                from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
                client.private_key = load_pem_private_key(keys["private_key"].encode("utf-8"), password=None)
                client.public_key = load_pem_public_key(keys["public_key"].encode("utf-8"))
                
                client.auth_secret = bytes.fromhex(keys["auth_secret_hex"])
                client.require_gcm_token = False
                print("[FCM] Loaded persisted credentials")
        except Exception as e:
            print("[FCM] Failed to load keys, registering new device:", e)
            client.create_new_keys()
            client.register()
            save_fcm_keys(client)
    else:
        client.create_new_keys()
        client.register()
        save_fcm_keys(client)

    # Подписываемся на топики уведомлений аниме
    try:
        client.subscribe_to_topic("all")
        client.subscribe_to_topic("android_all")
        print("[FCM] Subscribed to 'all' & 'android_all' topics")
    except Exception as e:
        print("[FCM] Error subscribing to topics:", e)

    def on_notification(payload, persistent_id):
        # Структура payload приходит в виде dict
        # Пример: {"title": "Новая серия!", "body": "Вышла 5 серия...", "link": "https://anilibria.tv/anime/releases/release/id_or_code"}
        print(f"[FCM] Received notification: {payload}")
        title = payload.get("title", "")
        body = payload.get("body", "")
        link = payload.get("link", "") or payload.get("url", "")
        
        if not link:
            return

        # Ищем ID тайтла или код из ссылки
        # Ссылки могут быть: .../release/123.html или .../release/title_code
        match = re.search(r"release/([^/.]+)", link)
        if not match:
            return
            
        detected_id = match.group(1) # Например '9243' или 'horimiya'
        
        # Получаем всех пользователей и проверяем их подписки
        users_data = load_data()
        for user_id, tracked_ids in users_data.items():
            # Если пользователь отслеживает этот ID
            if detected_id in tracked_ids:
                try:
                    msg_text = f"🔔 *Новая серия!*\n\n*Тайтл:* {title}\n*Описание:* {body}\n\n[Открыть тайтл]({link})"
                    bot.send_message(int(user_id), msg_text, parse_mode="Markdown")
                    print(f"[FCM] Notification sent to user {user_id}")
                except Exception as ex:
                    print(f"[FCM] Failed to send message to user {user_id}: {ex}")

    client.on_notification_message = on_notification
    
    while True:
        try:
            print("[FCM] Starting listener...")
            client.start_listening()
            while True:
                time.sleep(1)
        except Exception as e:
            print(f"[FCM] Error in listener loop: {e}. Reconnecting in 10 seconds...")
            try:
                client.close()
            except Exception:
                pass
            time.sleep(10)

def save_fcm_keys(client):
    try:
        # Сериализуем ECPrivateKey и ECPublicKey, если они являются объектами, а не строками
        from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption, PublicFormat
        
        priv_key_str = client.private_key
        if not isinstance(priv_key_str, str):
            priv_key_str = client.private_key.private_bytes(
                encoding=Encoding.PEM,
                format=PrivateFormat.PKCS8,
                encryption_algorithm=NoEncryption()
            ).decode("utf-8")
            
        pub_key_str = client.public_key
        if not isinstance(pub_key_str, str):
            pub_key_str = client.public_key.public_bytes(
                encoding=Encoding.PEM,
                format=PublicFormat.SubjectPublicKeyInfo
            ).decode("utf-8")

        keys = {
            "android_id": client.android_id,
            "security_token": client.security_token,
            "gcm_token": client.gcm_token,
            "fcm_token": client.fcm_token,
            "private_key": priv_key_str,
            "public_key": pub_key_str,
            "auth_secret_hex": client.auth_secret.hex()
        }
            
        with open(FCM_KEYS_FILE, "w") as f:
            json.dump(keys, f)
        print("[FCM] Credentials saved successfully")
    except Exception as e:
        print("[FCM] Failed to save keys:", e)

def start_telegram_polling():
    print("Telegram бот запущен...")
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except (ConnectionError, ProtocolError, Exception) as e:
            print(f"Ошибка соединения Telegram: {e}. Переподключение через 5 секунд...")
            time.sleep(5)

if __name__ == "__main__":
    # Запускаем FCM в фоновом потоке
    fcm_thread = threading.Thread(target=run_fcm_listener, daemon=True)
    fcm_thread.start()

    # Запускаем Telegram Bot Polling в основном потоке
    start_telegram_polling()
