import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import random
import webbrowser
import socket
import time
import threading

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# =============================================================================
#   Инициализация Flask и константы
# =============================================================================

app = Flask(__name__, static_folder='static')
CORS(app)

SETTINGS_FILE    = "settings.json"
INVENTORY_FILE   = "inventory.json"
COOLDOWNS_FILE   = "cooldowns.json"

# Глобальные переменные
pending_users = []              # очередь пользователей, ждущих открытия кейса
last_open_time = {}             # {username: timestamp последнего открытия}
COOLDOWN_SECONDS = 3600         # 1 час = 3600 секунд

# Дефолтные настройки (используются, если settings.json отсутствует или повреждён)
DEFAULT_SETTINGS = {
    "channel": "ripper_cmertanoc",
    "oauth_token": "oauth:ТОКЕН_СЮДА_ВСТАВЬ_СВОЙ",
    "open_browser_on_start": True,
    "rarities": {
        "common":    {"name": "Обычный",     "color": "#c4aaff", "chance": 48.0},
        "rare":      {"name": "Редкий",      "color": "#9f7aea", "chance": 28.0},
        "epic":      {"name": "Эпический",   "color": "#7c3aed", "chance": 15.0},
        "legendary": {"name": "Легендарный", "color": "#b794f4", "chance": 6.5},
        "godlike":   {"name": "Божественный","color": "#a78bdb", "chance": 2.0},
        "impossible": {"name": "Невозможный","color": "#7c3aed", "chance": 0.5}
    },
    "items": [
        {"name": "P250 | Crimson Kimono",      "rarity": "common",    "image_url": ""},
        {"name": "Glock-18 | Candy Apple",     "rarity": "common",    "image_url": ""},
        {"name": "USP-S | Torque",             "rarity": "rare",      "image_url": ""},
        {"name": "M4A4 | Neo-Noir",            "rarity": "rare",      "image_url": ""},
        {"name": "AK-47 | Redline",            "rarity": "rare",      "image_url": ""},
        {"name": "Desert Eagle | Printstream", "rarity": "epic",      "image_url": ""},
        {"name": "AWP | Asiimov",              "rarity": "epic",      "image_url": ""},
        {"name": "Karambit | Doppler",         "rarity": "legendary", "image_url": ""},
        {"name": "Butterfly Knife | Fade",     "rarity": "legendary", "image_url": ""},
        {"name": "AWP | Dragon Lore",          "rarity": "legendary", "image_url": ""},
        {"name": "Karambit | Gamma Doppler",   "rarity": "godlike",   "image_url": ""},
        {"name": "Skeleton Knife | Fade",      "rarity": "godlike",   "image_url": ""},
        {"name": "Butterfly Knife | Crimson Web", "rarity": "impossible", "image_url": ""},
        {"name": "Bayonet | Sapphire",         "rarity": "impossible","image_url": ""}
    ]
}


# =============================================================================
#   Функции работы с настройками
# =============================================================================

def load_settings():
    """Загружает настройки из файла или создаёт дефолтные"""
    if not os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_SETTINGS, f, ensure_ascii=False, indent=2)
        return DEFAULT_SETTINGS.copy()

    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Ошибка чтения settings.json: {e}")
        print("Используются дефолтные настройки")
        return DEFAULT_SETTINGS.copy()


def save_settings(data):
    """Сохраняет переданные настройки в файл"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"Ошибка сохранения настроек: {e}")
        return False


# Загружаем настройки при старте
settings = load_settings()


# =============================================================================
#   Кулдауны пользователей
# =============================================================================

def load_cooldowns():
    """Загружает время последнего открытия кейса каждым пользователем"""
    global last_open_time
    if os.path.exists(COOLDOWNS_FILE):
        try:
            with open(COOLDOWNS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                last_open_time = {k: float(v) for k, v in data.items()}
        except Exception:
            last_open_time = {}
    else:
        last_open_time = {}


def save_cooldowns():
    """Сохраняет кулдауны в файл"""
    try:
        with open(COOLDOWNS_FILE, 'w', encoding='utf-8') as f:
            json.dump({k: str(v) for k, v in last_open_time.items()}, f, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения cooldowns: {e}")


load_cooldowns()


def can_user_open(username):
    """
    Проверяет, прошёл ли кулдаун у пользователя.
    Возвращает: (можно_открыть: bool, оставшееся_времени_сек: int)
    """
    if username not in last_open_time:
        return True, 0
    elapsed = time.time() - last_open_time[username]
    if elapsed >= COOLDOWN_SECONDS:
        return True, 0
    return False, COOLDOWN_SECONDS - int(elapsed)


def format_remaining(seconds):
    """Преобразует секунды в человекочитаемый формат (ч мин сек)"""
    if seconds <= 0:
        return "сейчас"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    parts = []
    if h:
        parts.append(f"{h} ч")
    if m:
        parts.append(f"{m} мин")
    if s or not parts:
        parts.append(f"{s} сек")
    return " ".join(parts)


# =============================================================================
#   Отправка сообщений в чат Twitch
# =============================================================================

def send_chat_message(message):
    """
    Отправляет сообщение в чат Twitch через IRC.
    Использует сохранённый oauth-токен и канал из настроек.
    """
    token = settings.get("oauth_token", "").strip()
    channel = settings.get("channel", "").strip().lstrip("#")
    bot_username = "bot_user"

    if not token.startswith("oauth:") or not channel:
        print("Нет валидного токена или канала → сообщение не отправлено")
        return False

    try:
        sock = socket.socket()
        sock.connect(("irc.chat.twitch.tv", 6667))
        sock.send(f"PASS {token}\r\n".encode("utf-8"))
        sock.send(f"NICK {bot_username}\r\n".encode("utf-8"))
        sock.send(f"JOIN #{channel}\r\n".encode("utf-8"))
        sock.send(f"PRIVMSG #{channel} :{message}\r\n".encode("utf-8"))
        sock.close()
        print(f"[CHAT] Отправлено: {message}")
        return True
    except Exception as e:
        print(f"Ошибка отправки в чат: {e}")
        return False


# =============================================================================
#   Логика выбора редкости и предмета
# =============================================================================

def get_weighted_rarity():
    """
    Выбирает редкость по вероятностям (взвешенный рандом).
    Учитывает только те редкости, для которых есть хотя бы один предмет.
    """
    rarities = settings.get("rarities", {})
    all_items = settings.get("items", [])

    # Считаем, сколько предметов есть в каждой редкости
    rarity_counts = {}
    for item in all_items:
        r = item.get("rarity")
        if r:
            rarity_counts[r] = rarity_counts.get(r, 0) + 1

    # Только редкости с предметами и ненулевым шансом
    valid_rarities = [
        (key, info["chance"])
        for key, info in rarities.items()
        if info.get("chance", 0) > 0 and rarity_counts.get(key, 0) > 0
    ]

    if not valid_rarities:
        return "common"

    total_weight = sum(weight for _, weight in valid_rarities)
    if total_weight == 0:
        return random.choice([k for k, _ in valid_rarities])

    rnd = random.uniform(0, total_weight)
    cumulative = 0
    for key, weight in valid_rarities:
        cumulative += weight
        if rnd <= cumulative:
            return key
    return valid_rarities[-1][0]


# =============================================================================
#   Flask маршруты (API)
# =============================================================================

@app.route("/")
def index():
    """Отдаёт главную страницу оверлея"""
    return send_from_directory("static", "index.html")


@app.route("/api/settings")
def api_settings():
    """Возвращает текущие настройки (нужны фронтенду)"""
    return jsonify(settings)


@app.route("/api/open", methods=["POST"])
def api_open():
    """
    Основной эндпоинт — открытие кейса для пользователя.
    Проверяет кулдаун → выбирает редкость → выбирает предмет → сохраняет.
    """
    try:
        data = request.get_json()
        username = data.get("username")
        if not username:
            return jsonify({"error": "username required"}), 400

        can, remaining = can_user_open(username)
        if not can:
            return jsonify({
                "success": False,
                "error": "cooldown",
                "remaining": remaining,
                "message": f"Подожди ещё {format_remaining(remaining)}"
            }), 429

        # Выбираем редкость
        rarity_key = get_weighted_rarity()

        # Все предметы выбранной редкости
        items_in_rarity = [
            i for i in settings.get("items", [])
            if i.get("rarity") == rarity_key
        ]

        # Если по какой-то причине нет — берём все предметы
        if not items_in_rarity:
            items_in_rarity = settings.get("items", [])

        # Загружаем инвентарь
        inventory = {}
        if os.path.exists(INVENTORY_FILE):
            try:
                with open(INVENTORY_FILE, "r", encoding="utf-8") as f:
                    inventory = json.load(f)
            except Exception:
                pass

        user_items = inventory.get(username, [])
        user_item_names = {it["name"] for it in user_items}

        # Предпочитаем предметы, которых у пользователя ещё нет
        available_items = [
            it for it in items_in_rarity
            if it["name"] not in user_item_names
        ]

        if available_items:
            chosen_item = random.choice(available_items)
            already_have = False
        else:
            chosen_item = random.choice(items_in_rarity)
            already_have = True

        # Сохраняем предмет, если он новый
        if not already_have:
            inventory.setdefault(username, []).append(chosen_item)
            with open(INVENTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(inventory, f, ensure_ascii=False, indent=2)

        # Обновляем время последнего открытия
        last_open_time[username] = time.time()
        save_cooldowns()

        rarity_name = settings["rarities"].get(rarity_key, {}).get("name", rarity_key)

        return jsonify({
            "success": True,
            "username": username,
            "item": chosen_item,
            "rarity_key": rarity_key,
            "rarity_name": rarity_name,
            "already_have": already_have
        })

    except Exception as e:
        print(f"Ошибка в /api/open: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/send_chat", methods=["POST"])
def api_send_chat():
    """Позволяет фронтенду отправить сообщение в чат (запасной вариант)"""
    try:
        data = request.get_json()
        message = data.get("message")
        if not message:
            return jsonify({"error": "message required"}), 400

        if send_chat_message(message):
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "failed to send"}), 500
    except Exception as e:
        print(f"Ошибка /api/send_chat: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/get_pending", methods=["GET"])
def api_get_pending():
    """Фронтенд забирает следующего пользователя из очереди"""
    global pending_users
    if pending_users:
        user = pending_users.pop(0)
        return jsonify({"success": True, "username": user})
    return jsonify({"success": False})


# =============================================================================
#   Слушатель сообщений в чате Twitch (фоновая задача)
# =============================================================================

def irc_listener():
    """
    Подключается к чату Twitch как анонимный пользователь (justinfan...)
    Слушает команду !open и добавляет пользователя в очередь.
    Если кулдаун не прошёл — сразу пишет в чат сообщение.
    """
    global settings, pending_users
    channel = settings.get("channel", "").strip().lstrip("#")
    if not channel:
        print("Канал не указан → IRC-слушатель не запущен")
        return

    while True:
        try:
            sock = socket.socket()
            sock.connect(("irc.chat.twitch.tv", 6667))
            sock.send(f"NICK justinfan{random.randint(10000,99999)}\r\n".encode())
            sock.send(f"JOIN #{channel}\r\n".encode())
            print(f"IRC слушатель подключён к #{channel}")

            while True:
                data = sock.recv(2048).decode("utf-8", errors="ignore")
                if not data:
                    break

                if data.startswith("PING"):
                    sock.send(b"PONG :tmi.twitch.tv\r\n")
                    continue

                lines = data.split("\r\n")
                for line in lines:
                    if not line or "PRIVMSG" not in line:
                        continue

                    parts = line.split(":", 2)
                    if len(parts) < 3:
                        continue

                    user_part = parts[1].split("!")
                    if len(user_part) < 2:
                        continue

                    username = user_part[0].strip()
                    message = parts[2].strip()

                    if message == "!open":
                        can, remaining = can_user_open(username)
                        if can:
                            pending_users.append(username)
                            print(f"Добавлен в очередь !open: {username}")
                        else:
                            msg = f"@{username} подожди ещё {format_remaining(remaining)}"
                            send_chat_message(msg)
                            print(f"Кулдаун для {username}: {remaining} сек")
        except Exception as e:
            print(f"Ошибка IRC-слушателя: {e}")
            time.sleep(15)  # переподключение через 15 секунд


def run_server():
    """Запускает Flask-сервер и IRC-слушатель в фоне"""
    try:
        threading.Thread(target=irc_listener, daemon=True).start()
        print("\nСервер запущен → http://127.0.0.1:5000/")
        if settings.get("open_browser_on_start", True):
            webbrowser.open_new("http://127.0.0.1:5000/")
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        print(f"Ошибка запуска сервера: {e}")
        messagebox.showerror("Ошибка", f"Не удалось запустить сервер:\n{str(e)}")


# =============================================================================
#   GUI — окно настроек (Tkinter)
# =============================================================================

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("RICASE")
        self.root.geometry("1020x720")
        self.root.minsize(960, 680)
        self.root.configure(bg="#2c1c47")

        self._setup_styles()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=16, pady=(12, 4))

        # Переменные для полей ввода
        self.channel_var = tk.StringVar(value=settings.get("channel", ""))
        self.token_var = tk.StringVar(value=settings.get("oauth_token", ""))
        self.open_browser_var = tk.BooleanVar(value=settings.get("open_browser_on_start", True))

        self.rarity_vars = {}   # для редактирования шансов редкостей
        self.item_tree = None   # таблица предметов

        self.create_main_tab()
        self.create_rarities_tab()
        self.create_items_tab()

        # Нижняя панель с кнопками
        bottom = tk.Frame(self.root, bg="#2c1c47", height=70)
        bottom.pack(fill="x", pady=(0, 16), padx=16)

        ttk.Button(bottom, text="Сохранить настройки", command=self.save_settings, style="Accent.TButton").pack(side="left", padx=8)
        ttk.Button(bottom, text="Запустить сервер", command=self.run_only, style="Accent.TButton").pack(side="left", padx=8)
        ttk.Button(bottom, text="GitHub", command=lambda: webbrowser.open("https://github.com/RIPPER666YT/RICASE")).pack(side="left", padx=8)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()

    def _setup_styles(self):
        """Настройка стилей для красивого тёмного интерфейса"""
        style = ttk.Style()
        style.theme_use("clam")

        bg_dark   = "#2c1c47"
        bg_mid    = "#3a285a"
        bg_light  = "#4a3570"
        fg_light  = "#d0b8ff"
        fg_header = "#b794f4"
        accent    = "#7c3aed"
        accent_dark  = "#6d28d9"
        accent_darker = "#5b21b6"
        select_fg = "#ffffff"

        style.configure(".", background=bg_dark, foreground=fg_light)
        style.configure("TLabel", background=bg_dark, foreground=fg_light, font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 13, "bold"), foreground=fg_header)

        style.configure("TButton", padding=10, font=("Segoe UI", 11, "bold"),
                        background=bg_light, foreground=fg_light, borderwidth=0)
        style.map("TButton",
                  background=[("active", accent), ("pressed", accent_dark)],
                  foreground=[("active", select_fg), ("pressed", select_fg)])

        style.configure("Treeview", background=bg_mid, foreground=fg_light,
                        fieldbackground=bg_mid, rowheight=34, font=("Segoe UI", 10),
                        borderwidth=0, highlightthickness=0)
        style.map("Treeview", background=[("selected", accent)], foreground=[("selected", select_fg)])

        style.configure("Treeview.Heading", background=bg_light, foreground=fg_light,
                        font=("Segoe UI", 11, "bold"))
        style.map("Treeview.Heading", background=[("active", accent)])

        style.configure("TNotebook", background=bg_dark, tabmargins=[2,5,2,0], borderwidth=0)
        style.configure("TNotebook.Tab", background=bg_mid, foreground=fg_light,
                        padding=[14,8], font=("Segoe UI", 11))
        style.map("TNotebook.Tab", background=[("selected", accent)], foreground=[("selected", select_fg)])

        style.configure("TEntry", fieldbackground=bg_mid, foreground=fg_light,
                        insertcolor=fg_header, bordercolor=bg_light,
                        lightcolor=bg_light, darkcolor=bg_light, focuscolor=bg_dark)
        style.map("TEntry", fieldbackground=[("focus", bg_light)], insertcolor=[("focus", select_fg)])

        style.configure("Accent.TButton", background=accent, foreground=select_fg)
        style.map("Accent.TButton",
                  background=[("active", accent_dark), ("pressed", accent_darker)],
                  foreground=[("active", select_fg), ("pressed", select_fg)])

    def on_close(self):
        """Подтверждение выхода из программы"""
        if messagebox.askokcancel("Выход", "Закрыть RICASE?"):
            self.root.destroy()

    def reset_inventory(self):
        """Удаляет файл инвентаря полностью"""
        if messagebox.askyesno("Сброс инвентаря", "Удалить ВЕСЬ инвентарь пользователей?"):
            if os.path.exists(INVENTORY_FILE):
                try:
                    os.remove(INVENTORY_FILE)
                    messagebox.showinfo("Успех", "Инвентарь сброшен")
                except Exception as e:
                    messagebox.showerror("Ошибка", f"Не удалось удалить файл\n{e}")
            else:
                messagebox.showinfo("Информация", "Инвентарь и так пуст")

    def reset_cooldowns(self):
        """Сбрасывает все кулдауны (все смогут открыть сразу)"""
        if messagebox.askyesno("Сброс кулдаунов", "Сбросить кулдаун ВСЕМ пользователям?"):
            global last_open_time
            last_open_time.clear()
            if os.path.exists(COOLDOWNS_FILE):
                try:
                    os.remove(COOLDOWNS_FILE)
                except:
                    pass
            messagebox.showinfo("Готово", "Все кулдауны сброшены")

    def reset_to_default(self):
        """Восстанавливает дефолтные настройки"""
        if messagebox.askyesno("Сброс настроек", "Восстановить заводские настройки?"):
            try:
                if os.path.exists(SETTINGS_FILE):
                    os.remove(SETTINGS_FILE)
                global settings
                settings = load_settings()
                self.channel_var.set(settings["channel"])
                self.token_var.set(settings["oauth_token"])
                self.open_browser_var.set(settings["open_browser_on_start"])

                # Обновляем таблицу редкостей
                for key, var_info in self.rarity_vars.items():
                    chance = settings["rarities"][key]["chance"]
                    var_info["chance"].set(chance)
                    self.rarity_tree.set(var_info["tree_id"], "chance", f"{chance:.1f}")

                # Обновляем таблицу предметов
                self.item_tree.delete(*self.item_tree.get_children())
                for item in settings.get("items", []):
                    r_key = item.get("rarity", "common")
                    r_name = settings["rarities"].get(r_key, {}).get("name", r_key)
                    url = item.get("image_url", "")
                    self.item_tree.insert("", "end", values=(item.get("name", ""), r_name, url))

                messagebox.showinfo("Готово", "Настройки сброшены к дефолтным")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

    def create_main_tab(self):
        """Вкладка «Основное» — канал, токен, автозапуск браузера"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Основное")

        container = tk.Frame(tab, bg="#2c1c47")
        container.pack(fill="both", expand=True, padx=40, pady=40)

        ttk.Label(container, text="Twitch канал", style="Header.TLabel").grid(row=0, column=0, sticky="w", pady=(0,4))
        ttk.Entry(container, textvariable=self.channel_var, width=42, font=("Segoe UI", 11)).grid(row=1, column=0, sticky="ew", pady=(0,24))

        ttk.Label(container, text="OAuth токен (начинается с oauth:)", style="Header.TLabel").grid(row=2, column=0, sticky="w", pady=(0,4))
        token_frame = tk.Frame(container, bg="#2c1c47")
        token_frame.grid(row=3, column=0, sticky="ew")
        self.entry_token = ttk.Entry(token_frame, textvariable=self.token_var, width=52, font=("Segoe UI", 11), show="*")
        self.entry_token.pack(side="left", fill="x", expand=True)
        self.eye_btn = ttk.Button(token_frame, text="👁", width=3, command=self.toggle_token_visibility)
        self.eye_btn.pack(side="right", padx=(8,0))

        # Чекбокс "Открывать браузер при старте"
        check_frame = tk.Frame(container, bg="#2c1c47")
        check_frame.grid(row=4, column=0, sticky="w", pady=(28,0))
        self.check_canvas = tk.Canvas(check_frame, width=24, height=24, bg="#2c1c47", highlightthickness=0)
        self.check_canvas.pack(side="left", padx=(0,8))
        self.check_rect = self.check_canvas.create_rectangle(2,2,22,22, fill="#3a285a", outline="#4a3570", width=2)
        self.check_mark = self.check_canvas.create_text(12,12, text="✔", fill="#7c3aed", font=("Segoe UI", 16, "bold"), state="hidden")
        ttk.Label(check_frame, text="Открывать браузер при запуске сервера", font=("Segoe UI", 10), foreground="#d0b8ff").pack(side="left")

        def toggle_check(e=None):
            v = self.open_browser_var.get()
            self.open_browser_var.set(not v)
            if self.open_browser_var.get():
                self.check_canvas.itemconfig(self.check_mark, state="normal")
                self.check_canvas.itemconfig(self.check_rect, fill="#7c3aed")
            else:
                self.check_canvas.itemconfig(self.check_mark, state="hidden")
                self.check_canvas.itemconfig(self.check_rect, fill="#3a285a")

        self.check_canvas.bind("<Button-1>", toggle_check)
        if self.open_browser_var.get():
            self.check_canvas.itemconfig(self.check_mark, state="normal")
            self.check_canvas.itemconfig(self.check_rect, fill="#7c3aed")

        container.columnconfigure(0, weight=1)

        # Кнопки сброса
        btn_frame = tk.Frame(container, bg="#2c1c47")
        btn_frame.grid(row=5, column=0, sticky="w", pady=(32,0))
        ttk.Button(btn_frame, text="Сброс инвентаря", command=self.reset_inventory).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="Сброс настроек", command=self.reset_to_default).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="Сброс кулдаунов", command=self.reset_cooldowns).pack(side="left", padx=6)

    def toggle_token_visibility(self):
        """Показать/спрятать OAuth-токен"""
        if self.entry_token.cget("show") == "*":
            self.entry_token.configure(show="")
            self.eye_btn.configure(text="🙈")
        else:
            self.entry_token.configure(show="*")
            self.eye_btn.configure(text="👁")

    def create_rarities_tab(self):
        """Вкладка «Редкости» — редактирование шансов"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Редкости")

        ttk.Label(tab, text="Двойной клик по числу в столбце «Шанс %» для изменения\nСумма всех шансов должна быть ровно 100%", 
                  font=("Segoe UI", 10), foreground="#a78bdb").pack(pady=(12,4))

        self.rarity_tree = ttk.Treeview(tab, columns=("name", "chance"), show="headings", height=8)
        self.rarity_tree.heading("name", text="Редкость")
        self.rarity_tree.heading("chance", text="Шанс %")
        self.rarity_tree.column("name", width=340, anchor="w")
        self.rarity_tree.column("chance", width=140, anchor="center")
        self.rarity_tree.pack(padx=30, pady=10, fill="both", expand=True)

        self.rarity_vars = {}
        for key in ["common", "rare", "epic", "legendary", "godlike", "impossible"]:
            val = settings["rarities"].get(key, {})
            iid = self.rarity_tree.insert("", "end", values=(val.get("name", ""), f"{val.get('chance', 0):.1f}"))
            self.rarity_vars[key] = {
                "tree_id": iid,
                "chance": tk.DoubleVar(value=val.get("chance", 0))
            }

        self.rarity_tree.bind("<Double-1>", self.on_double_click_rarity)

    def on_double_click_rarity(self, event):
        """Редактирование шанса редкости двойным кликом"""
        tree = event.widget
        item = tree.identify_row(event.y)
        if not item:
            return
        col = tree.identify_column(event.x)
        if col != "#2":  # только столбец "Шанс %"
            return

        bbox = tree.bbox(item, column=col)
        if not bbox:
            return

        key = next(k for k, v in self.rarity_vars.items() if v["tree_id"] == item)
        var = self.rarity_vars[key]["chance"]

        entry = ttk.Entry(tree, font=("Segoe UI", 11))
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        entry.insert(0, f"{var.get():.1f}")
        entry.focus()

        def save(e=None):
            try:
                val = float(entry.get())
                var.set(max(0, val))
                tree.set(item, "chance", f"{var.get():.1f}")
            except:
                pass
            entry.destroy()

        entry.bind("<Return>", save)
        entry.bind("<FocusOut>", save)

    def create_items_tab(self):
        """Вкладка «Предметы» — список всех возможных дропов"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="Предметы")

        ttk.Label(tab, text="Двойной клик по ячейке для редактирования", 
                  font=("Segoe UI", 10), foreground="#a78bdb").pack(pady=(12,4))

        frame = tk.Frame(tab, bg="#2c1c47")
        frame.pack(fill="both", expand=True, padx=30, pady=(10,0))

        self.item_tree = ttk.Treeview(frame, columns=("name", "rarity", "image_url"), show="headings")
        self.item_tree.heading("name", text="Название")
        self.item_tree.heading("rarity", text="Редкость")
        self.item_tree.heading("image_url", text="Ссылка на картинку")
        self.item_tree.column("name", width=380, anchor="w")
        self.item_tree.column("rarity", width=140, anchor="center")
        self.item_tree.column("image_url", width=500, anchor="w")
        self.item_tree.pack(side="left", fill="both", expand=True)

        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.item_tree.yview)
        scroll.pack(side="right", fill="y")
        self.item_tree.configure(yscrollcommand=scroll.set)

        # Заполняем таблицу текущими предметами
        for item in settings.get("items", []):
            r_key = item.get("rarity", "common")
            r_name = settings["rarities"].get(r_key, {}).get("name", r_key)
            url = item.get("image_url", "")
            self.item_tree.insert("", "end", values=(item.get("name", ""), r_name, url))

        # Кнопки управления предметами
        btnf = tk.Frame(tab, bg="#2c1c47")
        btnf.pack(pady=16)
        ttk.Button(btnf, text="Добавить", command=self.add_item).pack(side="left", padx=8)
        ttk.Button(btnf, text="Удалить", command=self.delete_item).pack(side="left", padx=8)

        self.item_tree.bind("<Double-1>", self.edit_item)

    def add_item(self):
        """Добавляет пустую строку для нового предмета"""
        self.item_tree.insert("", "end", values=(f"Новый предмет {len(self.item_tree.get_children())+1}", "Обычный", ""))

    def delete_item(self):
        """Удаляет выделенную строку предмета"""
        sel = self.item_tree.selection()
        if sel:
            self.item_tree.delete(sel)

    def edit_item(self, event):
        """Редактирование ячеек таблицы предметов по двойному клику"""
        tree = event.widget
        item = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        if not item or col not in ("#1", "#2", "#3"):
            return

        bbox = tree.bbox(item, column=col)
        if not bbox:
            return

        values = tree.item(item, "values")

        if col == "#1":  # Название
            entry = ttk.Entry(tree, font=("Segoe UI", 10))
            entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
            entry.insert(0, values[0])
            entry.focus()

            def save(e=None):
                new_name = entry.get().strip() or "Без названия"
                tree.set(item, "name", new_name)
                entry.destroy()

            entry.bind("<Return>", save)
            entry.bind("<FocusOut>", save)
            return

        if col == "#2":  # Редкость (выпадающий список)
            current = values[1]
            names = [settings["rarities"][k]["name"] for k in settings["rarities"]]
            popup = tk.Toplevel(self.root)
            popup.wm_overrideredirect(True)
            popup.configure(bg="#3a285a")
            popup.geometry(f"+{tree.winfo_rootx() + bbox[0]+10}+{tree.winfo_rooty() + bbox[1] + bbox[3]}")

            lb = tk.Listbox(popup, height=min(8, len(names)), bg="#3a285a", fg="#d0b8ff",
                            selectbackground="#7c3aed", font=("Segoe UI", 10), borderwidth=0)
            for n in names:
                lb.insert(tk.END, n)
            try:
                idx = names.index(current)
                lb.select_set(idx)
            except ValueError:
                lb.select_set(0)
            lb.pack()

            def apply(e=None):
                s = lb.curselection()
                if s:
                    tree.set(item, "rarity", lb.get(s[0]))
                popup.destroy()

            lb.bind("<Return>", apply)
            lb.bind("<Double-Button-1>", apply)
            lb.bind("<FocusOut>", lambda e: popup.destroy())
            lb.bind("<Escape>", lambda e: popup.destroy())
            return

        # Ссылка на картинку
        entry = ttk.Entry(tree, font=("Segoe UI", 10))
        entry.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
        entry.insert(0, values[2])
        entry.focus()

        def save(e=None):
            new_url = entry.get().strip()
            tree.set(item, "image_url", new_url)
            entry.destroy()

        entry.bind("<Return>", save)
        entry.bind("<FocusOut>", save)

    def check_rarities_sum(self):
        """Проверяет, что сумма шансов редкостей ≈ 100%"""
        total = sum(v["chance"].get() for v in self.rarity_vars.values())
        return abs(total - 100.0) < 0.01

    def save_settings(self):
        """Собирает все данные из интерфейса и сохраняет в settings.json"""
        global settings

        if not self.check_rarities_sum():
            total = sum(v["chance"].get() for v in self.rarity_vars.values())
            messagebox.showwarning(
                "Некорректные шансы",
                f"Сумма шансов должна быть ровно 100%\n\nТекущая сумма: {total:.2f}%"
            )
            return

        try:
            new_settings = {
                "channel": self.channel_var.get().strip(),
                "oauth_token": self.token_var.get().strip(),
                "open_browser_on_start": self.open_browser_var.get(),
                "rarities": {},
                "items": []
            }

            # Сохраняем редкости
            for key, var_info in self.rarity_vars.items():
                new_settings["rarities"][key] = {
                    "name": settings["rarities"][key]["name"],
                    "color": settings["rarities"][key]["color"],
                    "chance": round(var_info["chance"].get(), 2)
                }

            # Сохраняем предметы из таблицы
            for iid in self.item_tree.get_children():
                name, rname, url = self.item_tree.item(iid, "values")
                name = name.strip()
                if not name:
                    continue
                # Находим ключ редкости по имени
                r_key = next((k for k, v in settings["rarities"].items() if v["name"] == rname), "common")
                item = {"name": name, "rarity": r_key}
                if url.strip():
                    item["image_url"] = url.strip()
                new_settings["items"].append(item)

            if save_settings(new_settings):
                settings = new_settings
                messagebox.showinfo("Готово", "Настройки сохранены")
            else:
                messagebox.showerror("Ошибка", "Не удалось сохранить файл настроек")

        except Exception as e:
            messagebox.showerror("Ошибка сохранения", str(e))

    def run_only(self):
        """Сохраняет настройки и запускает сервер"""
        self.save_settings()
        if not self.check_rarities_sum():
            return
        threading.Thread(target=run_server, daemon=True).start()
        self.root.after(2000, lambda: messagebox.showinfo("Сервер", "Запущен на http://127.0.0.1:5000/"))


# =============================================================================
#   Запуск программы
# =============================================================================

if __name__ == "__main__":
    try:
        App()
    except Exception as e:
        print(f"Критическая ошибка при запуске: {e}")
        input("Нажмите Enter для выхода...")