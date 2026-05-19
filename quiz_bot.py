# -*- coding: utf-8 -*-
"""
Квиз-бот для Softclub Academy.
Логика: ФИ -> выбор раздела -> вопросы по одному с таймером ->
отчёт за этап -> пересдача ошибок до полного прохождения ->
финальный отчёт владельцу -> следующий раздел.

Запуск:  python quiz_bot.py
Установка зависимостей:  pip install pyTelegramBotAPI
"""

import os
import glob
import threading
import telebot
from telebot import types

# ============================ НАСТРОЙКИ ============================
# Вставьте СВЕЖИЙ токен (старый обязательно отзовите в @BotFather!)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8939631783:AAHgPB9wVbbhnS2lLeRzPqgFWe4f86FJiEo")
OWNER_ID = int(os.getenv("OWNER_ID", "1649433338"))
# Ваш Telegram ID — сюда приходят отчёты по студентам.
# Чтобы узнать свой ID: запустите бота и отправьте ему команду /myid


SECTIONS_DIR = "sections"   # папка с файлами разделов (.txt)
TIME_CLOSED = 15            # секунд на закрытый вопрос
TIME_OPEN = 20              # секунд на открытый вопрос
# ===================================================================

bot = telebot.TeleBot(BOT_TOKEN)

# Состояние каждого пользователя: user_id -> dict
users = {}

# По одному замку на пользователя (защита от гонок таймера и ответов)
locks = {}
_locks_guard = threading.Lock()


def get_lock(uid):
    with _locks_guard:
        if uid not in locks:
            locks[uid] = threading.Lock()
        return locks[uid]


# ======================= ЗАГРУЗКА РАЗДЕЛОВ =========================

def parse_section_file(path):
    """Читает один .txt-файл раздела. Возвращает (название, вопросы, ошибки)."""
    with open(path, encoding="utf-8") as f:
        content = f.read()

    title = os.path.splitext(os.path.basename(path))[0]
    body_lines = []
    for ln in content.splitlines():
        if ln.strip().lower().startswith("# раздел"):
            part = ln.split(":", 1)
            if len(part) == 2 and part[1].strip():
                title = part[1].strip()
            continue
        body_lines.append(ln)

    # Разбиваем на блоки по пустым строкам — один блок = один вопрос
    blocks, cur = [], []
    for ln in body_lines:
        if ln.strip() == "":
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(ln.rstrip())
    if cur:
        blocks.append(cur)

    questions, errors = [], []
    for i, block in enumerate(blocks, 1):
        first = block[0].strip()

        # ----- Открытый вопрос -----
        if first.lower().startswith("[открытый]"):
            text = first[len("[открытый]"):].strip()
            if len(block) < 2:
                errors.append(f"Вопрос {i}: открытый вопрос без ответа")
                continue
            answer = block[1].strip()
            if not (answer.isdigit() and 1 <= len(answer) <= 4):
                errors.append(
                    f"Вопрос {i}: ответ '{answer}' должен быть числом из 1–4 цифр")
                continue
            questions.append({"type": "open", "text": text, "answer": answer})

        # ----- Закрытый вопрос -----
        else:
            text = first
            options_raw = block[1:]
            if len(options_raw) != 4:
                errors.append(
                    f"Вопрос {i} ('{text[:30]}...'): нужно 4 варианта, "
                    f"найдено {len(options_raw)}")
                continue
            correct, options = None, []
            for j, opt in enumerate(options_raw):
                opt = opt.strip()
                if opt.startswith("+"):
                    correct = j
                    options.append(opt[1:].strip())
                else:
                    options.append(opt)
            if correct is None:
                errors.append(
                    f"Вопрос {i} ('{text[:30]}...'): не отмечен правильный "
                    f"вариант (поставьте + перед ним)")
                continue
            questions.append({
                "type": "closed", "text": text,
                "options": options, "correct": correct,
            })

    return title, questions, errors


def load_all_sections():
    """Читает все .txt из папки sections/. Возвращает (разделы, ошибки)."""
    sections, all_errors = {}, {}
    if not os.path.isdir(SECTIONS_DIR):
        os.makedirs(SECTIONS_DIR)
    for path in sorted(glob.glob(os.path.join(SECTIONS_DIR, "*.txt"))):
        title, questions, errors = parse_section_file(path)
        sections[title] = questions
        if errors:
            all_errors[title] = errors
    return sections, all_errors


SECTIONS, SECTION_ERRORS = load_all_sections()
SECTION_LIST = list(SECTIONS.keys())


# ============================ УТИЛИТЫ ==============================

def split_text(text, limit=3800):
    """Режет длинный текст на куски под лимит Telegram (4096)."""
    parts = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:]
    parts.append(text)
    return parts


# ======================= КОМАНДЫ / СТАРТ ===========================

@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = message.chat.id
    with get_lock(uid):
        old = users.get(uid)
        if old and old.get("timer"):
            old["timer"].cancel()
        users[uid] = {"step": "awaiting_name"}
    bot.send_message(
        uid,
        "Ассалому алайкум! 👋\n\n"
        "Это тестовый бот SMR.\n"
        "Для начала введите вашу <b>Фамилию и Имя</b>:",
        parse_mode="HTML",
    )


@bot.message_handler(commands=["myid"])
def cmd_myid(message):
    bot.send_message(message.chat.id,
                     f"Ваш Telegram ID: {message.chat.id}\n"
                     f"Впишите это число в OWNER_ID в начале файла quiz_bot.py")


@bot.message_handler(commands=["help"])
def cmd_help(message):
    bot.send_message(
        message.chat.id,
        "/start — начать тестирование\n"
        "/myid — узнать свой Telegram ID\n"
        "/reload — (для владельца) перечитать разделы из папки sections")


@bot.message_handler(commands=["reload"])
def cmd_reload(message):
    if message.chat.id != OWNER_ID:
        return
    global SECTIONS, SECTION_ERRORS, SECTION_LIST
    SECTIONS, SECTION_ERRORS = load_all_sections()
    SECTION_LIST = list(SECTIONS.keys())

    msg = f"✅ Перезагружено разделов: {len(SECTIONS)}\n\n"
    for t in SECTION_LIST:
        qs = SECTIONS[t]
        closed = sum(1 for q in qs if q["type"] == "closed")
        opened = sum(1 for q in qs if q["type"] == "open")
        msg += f"• {t}: {closed} закрытых + {opened} открытых = {len(qs)}\n"
    if SECTION_ERRORS:
        msg += "\n⚠️ ОШИБКИ В ФАЙЛАХ (эти вопросы пропущены):\n"
        for t, errs in SECTION_ERRORS.items():
            msg += f"\n[{t}]\n" + "\n".join("  " + e for e in errs) + "\n"
    for chunk in split_text(msg):
        bot.send_message(message.chat.id, chunk)


# ========================= МАРШРУТ ТЕКСТА ==========================

@bot.message_handler(content_types=["text"])
def text_router(message):
    uid = message.chat.id
    with get_lock(uid):
        st = users.get(uid)
        if not st:
            bot.send_message(uid, "Напишите /start, чтобы начать.")
            return
        step = st.get("step")
        if step == "awaiting_name":
            handle_name(message)
        elif step == "awaiting_open_answer":
            handle_open_answer(message)
        elif step == "choosing_section":
            bot.send_message(uid, "Пожалуйста, выберите раздел кнопкой ниже.")
        elif step == "in_closed":
            bot.send_message(uid, "Пожалуйста, ответьте, нажав на кнопку с номером.")


def handle_name(message):
    uid = message.chat.id
    name = message.text.strip()
    if len(name) < 3:
        bot.send_message(uid, "Введите Фамилию и Имя полностью:")
        return
    users[uid]["name"] = name
    users[uid]["step"] = "choosing_section"
    bot.send_message(uid, f"Спасибо, {name}!")
    show_sections(uid)


def show_sections(uid):
    if not SECTION_LIST:
        bot.send_message(uid, "Разделы ещё не добавлены. Обратитесь к преподавателю.")
        return
    markup = types.InlineKeyboardMarkup()
    for idx, title in enumerate(SECTION_LIST):
        markup.add(types.InlineKeyboardButton(title, callback_data=f"sec:{idx}"))
    bot.send_message(uid, "Выберите раздел для прохождения:", reply_markup=markup)


# ============================ CALLBACK =============================

@bot.callback_query_handler(func=lambda c: True)
def callbacks(c):
    uid = c.message.chat.id
    data = c.data
    try:
        bot.answer_callback_query(c.id)
    except Exception:
        pass

    with get_lock(uid):
        st = users.get(uid)
        if not st:
            bot.send_message(uid, "Сессия устарела. Напишите /start, чтобы начать заново.")
            return

        if data.startswith("sec:"):
            if st.get("step") != "choosing_section":
                return
            idx = int(data[4:])
            if 0 <= idx < len(SECTION_LIST):
                start_section(uid, idx)

        elif data.startswith("ans:"):
            _, token, choice = data.split(":")
            handle_closed_answer(uid, int(token), int(choice))

        elif data == "next_section":
            st["step"] = "choosing_section"
            show_sections(uid)

        elif data == "finish":
            bot.send_message(uid, "Спасибо! Тестирование завершено.\n"
                                  "Напишите /start, чтобы пройти снова.")
            users.pop(uid, None)


# ======================== ХОД ТЕСТИРОВАНИЯ =========================

def start_section(uid, idx):
    """Начинает раздел: этап 1 — все вопросы."""
    title = SECTION_LIST[idx]
    questions = SECTIONS[title]
    st = users[uid]
    st["section_title"] = title
    st["stage"] = 1
    st["stage_history"] = []  # отчёт по каждому этапу
    st["queue"] = list(questions)  # вопросы текущего этапа
    begin_stage(uid)


def begin_stage(uid):
    """Запускает очередной этап (первый проход или пересдача)."""
    st = users[uid]
    st["index"] = 0
    st["answers"] = []
    st["q_token"] = 0
    bot.send_message(
        uid,
        f"📚 Раздел: <b>{st['section_title']}</b>\n"
        f"Этап {st['stage']}. Вопросов: {len(st['queue'])}\n\n"
        f"⏱ На закрытый вопрос — {TIME_CLOSED} сек, "
        f"на открытый — {TIME_OPEN} сек.\n"
        f"Поехали!",
        parse_mode="HTML",
    )
    send_next_question(uid)


def send_next_question(uid):
    """Отправляет следующий вопрос из очереди или завершает этап."""
    st = users.get(uid)
    if not st:
        return
    idx = st["index"]
    queue = st["queue"]
    if idx >= len(queue):
        finish_stage(uid)
        return

    q = queue[idx]
    st["q_token"] += 1
    token = st["q_token"]
    num, total = idx + 1, len(queue)

    if q["type"] == "closed":
        st["step"] = "in_closed"
        text = f"❓ Вопрос {num}/{total}\n\n{q['text']}\n\n"
        for j, opt in enumerate(q["options"]):
            text += f"{j + 1}) {opt}\n"
        text += f"\n⏱ {TIME_CLOSED} секунд"
        markup = types.InlineKeyboardMarkup()
        markup.row(*[
            types.InlineKeyboardButton(str(j + 1), callback_data=f"ans:{token}:{j}")
            for j in range(4)
        ])
        sent = bot.send_message(uid, text, reply_markup=markup)
        st["question_msg_id"] = sent.message_id
        start_timer(uid, token, TIME_CLOSED)
    else:
        st["step"] = "awaiting_open_answer"
        st["open_token"] = token
        text = (f"✏️ Вопрос {num}/{total}\n\n{q['text']}\n\n"
                f"Напишите ответ числом (от 1 до 4 цифр).\n"
                f"⏱ {TIME_OPEN} секунд")
        bot.send_message(uid, text)
        start_timer(uid, token, TIME_OPEN)


def start_timer(uid, token, seconds):
    st = users.get(uid)
    if not st:
        return
    timer = threading.Timer(seconds, on_timeout, args=(uid, token))
    timer.daemon = True
    st["timer"] = timer
    timer.start()


def on_timeout(uid, token):
    """Сработал таймер: студент не ответил вовремя."""
    with get_lock(uid):
        st = users.get(uid)
        if not st or st.get("q_token") != token:
            return  # студент уже ответил — таймер устарел

        # увеличиваем счётчик пропусков подряд
        st["consecutive_timeouts"] = st.get("consecutive_timeouts", 0) + 1

        q = st["queue"][st["index"]]
        st["answers"].append({"q": q, "given": "— (нет ответа)", "correct": False})
        if q["type"] == "closed":
            _clear_buttons(uid, st)
        bot.send_message(uid, "⏱ Время вышло. Засчитан как неправильный.")

        # если 3 пропуска подряд — останавливаем тестирование
        if st["consecutive_timeouts"] >= 3:
            bot.send_message(
                uid,
                "❌ Вы пропустили 3 вопроса подряд.\n"
                "Тестирование остановлено. Напишите /start, чтобы начать заново."
            )
            users.pop(uid, None)  # удаляем сессию
            return

        st["index"] += 1
        send_next_question(uid)


def handle_closed_answer(uid, token, choice):
    """Студент нажал кнопку с вариантом ответа."""
    st = users.get(uid)
    if not st or st.get("q_token") != token:
        return  # устаревшая кнопка или время уже вышло
    if st.get("timer"):
        st["timer"].cancel()
        st["consecutive_timeouts"] = 0  # сбрасываем счётчик пропусков
    q = st["queue"][st["index"]]
    _clear_buttons(uid, st)
    is_correct = (choice == q["correct"])
    st["answers"].append({
        "q": q,
        "given": q["options"][choice],
        "correct": is_correct,
    })
    bot.send_message(uid, "✔️ Ответ принят.")
    st["index"] += 1
    send_next_question(uid)


def handle_open_answer(message):
    """Студент прислал текст в ответ на открытый вопрос."""
    uid = message.chat.id
    st = users.get(uid)
    if not st or st.get("q_token") != st.get("open_token"):
        return
    if st.get("timer"):
        st["timer"].cancel()
        st["consecutive_timeouts"] = 0  # сбрасываем счётчик пропусков
    q = st["queue"][st["index"]]
    # оставляем только цифры — прощаем пробелы и лишние символы
    given_digits = "".join(ch for ch in message.text if ch.isdigit())
    shown = given_digits if given_digits else "— (нет цифр)"
    is_correct = (given_digits == q["answer"])
    st["answers"].append({"q": q, "given": shown, "correct": is_correct})
    bot.send_message(uid, "✔️ Ответ принят.")
    st["index"] += 1
    send_next_question(uid)


def _clear_buttons(uid, st):
    """Убирает кнопки у уже отвеченного вопроса."""
    mid = st.get("question_msg_id")
    if mid:
        try:
            bot.edit_message_reply_markup(uid, mid)
        except Exception:
            pass
        st["question_msg_id"] = None


# ========================= ЗАВЕРШЕНИЕ ЭТАПА ========================

def finish_stage(uid):
    """Этап пройден: отчёт студенту, затем пересдача ошибок или конец раздела."""
    st = users.get(uid)
    if not st:
        return
    answers = st["answers"]
    correct = sum(1 for a in answers if a["correct"])
    total = len(answers)
    wrong = [a for a in answers if not a["correct"]]

    bot.send_message(
        uid,
        f"📊 Этап {st['stage']} завершён\n"
        f"Раздел: {st['section_title']}\n\n"
        f"✅ Правильно: {correct} из {total}\n"
        f"❌ Неправильно: {len(wrong)}",
    )

    if wrong:
        report = "❌ Разбор ошибок с правильными ответами:\n"
        for i, a in enumerate(wrong, 1):
            q = a["q"]
            correct_text = (q["options"][q["correct"]]
                            if q["type"] == "closed" else q["answer"])
            report += (f"\n{i}. {q['text']}\n"
                       f"   Ваш ответ: {a['given']}\n"
                       f"   ✅ Правильный ответ: {correct_text}\n")
        for chunk in split_text(report):
            bot.send_message(uid, chunk)

    # сохраняем этап в историю для отчёта владельцу
    st["stage_history"].append({
        "stage": st["stage"], "correct": correct,
        "total": total, "wrong": wrong,
    })

    if not wrong:
        finish_section(uid)
    else:
        st["stage"] += 1
        st["queue"] = [a["q"] for a in wrong]
        bot.send_message(
            uid,
            f"⏱ Даю <b>1 минуту</b> на изучение правильных ответов.\n\n"
            f"После этого начнётся этап {st['stage']}: пересдача {len(st['queue'])} "
            f"вопросов, в которых была ошибка.",
            parse_mode="HTML",
        )
        # запускаем таймер на 60 секунд перед началом пересдачи
        timer = threading.Timer(60.0, start_retake_stage, args=(uid,))
        timer.daemon = True
        st["study_timer"] = timer
        timer.start()


def start_retake_stage(uid):
    """Запускается через минуту после показа разбора ошибок — начинает пересдачу."""
    with get_lock(uid):
        st = users.get(uid)
        if not st:
            return
        bot.send_message(uid, "⏰ Время вышло! Начинаем пересдачу.")
        begin_stage(uid)


def finish_section(uid):
    """Раздел пройден полностью без ошибок."""
    st = users.get(uid)
    if not st:
        return
    stages = len(st["stage_history"])
    retakes = stages - 1

    bot.send_message(
        uid,
        f"🎉 Поздравляем!\n"
        f"Раздел «{st['section_title']}» пройден полностью без ошибок.\n"
        f"Этапов потребовалось: {stages} (пересдач: {retakes}).",
    )
    send_owner_report(uid)

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Выбрать другой раздел",
                                          callback_data="next_section"))
    markup.add(types.InlineKeyboardButton("Завершить", callback_data="finish"))
    bot.send_message(uid, "Что дальше?", reply_markup=markup)


def send_owner_report(uid):
    """Отправляет владельцу подробный отчёт по студенту."""
    st = users.get(uid)
    if not st:
        return
    name = st.get("name", "—")
    stages = st["stage_history"]
    retakes = len(stages) - 1

    lines = [
        "📋 ОТЧЁТ ПО СТУДЕНТУ",
        f"Студент: {name}",
        f"Telegram ID: {uid}",
        f"Раздел: {st['section_title']}",
        f"Этапов пройдено: {len(stages)} (пересдач: {retakes})",
        "",
    ]
    for s in stages:
        lines.append(
            f"— Этап {s['stage']}: правильно {s['correct']}/{s['total']}, "
            f"ошибок {len(s['wrong'])}")
        for a in s["wrong"]:
            q = a["q"]
            ct = (q["options"][q["correct"]]
                  if q["type"] == "closed" else q["answer"])
            lines.append(f"    ✗ {q['text']}")
            lines.append(f"       ответ студента: {a['given']} | правильно: {ct}")
        lines.append("")

    report = "\n".join(lines)
    if OWNER_ID == 0:
        print("[!] OWNER_ID не задан — отчёт владельцу не отправлен.")
        print(report)
        return
    try:
        for chunk in split_text(report):
            bot.send_message(OWNER_ID, chunk)
    except Exception as e:
        print("Не удалось отправить отчёт владельцу:", e)


# ============================== ЗАПУСК =============================

if __name__ == "__main__":
    print(f"Загружено разделов: {len(SECTIONS)}")
    for t in SECTION_LIST:
        print(f"  • {t}: {len(SECTIONS[t])} вопросов")
    if SECTION_ERRORS:
        print("ВНИМАНИЕ: в файлах разделов есть ошибки, см. команду /reload")
    if OWNER_ID == 0:
        print("ВНИМАНИЕ: OWNER_ID не задан — отправьте боту /myid и впишите свой ID.")
    print("Бот запущен. Ctrl+C для остановки.")
    bot.infinity_polling(timeout=60)
