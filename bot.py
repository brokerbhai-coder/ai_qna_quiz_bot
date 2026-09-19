import os
import time
import uuid
import json
import threading
import telebot
from telebot import types
from flask import Flask, request
from quiz_parser import parse_quizzes, extract_title
import gdrive_store

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    raise SystemExit(
        "BOT_TOKEN nahi mila!\n"
        "1) .env file banayein aur usme likhein: BOT_TOKEN=yahan_apna_token\n"
        "   YA\n"
        "2) Environment variable set karein: export BOT_TOKEN=yahan_apna_token"
    )

bot = telebot.TeleBot(BOT_TOKEN)

DEFAULT_TIMER_SECONDS = 30
POST_ANSWER_PAUSE = 2  # jawab dene ke baad itna ruk kar agla question

# Har banaye gaye quiz ko yahan yaad rakhte hain.
# quiz_id -> {"title": str, "quizzes": [list of quiz-dicts]}
# Ye ab ek JSON file me bhi save hota hai taaki bot restart/spin-down ke
# baad bhi purane quizzes wapas mil jayein. (Render free tier pe naya
# deploy hone par filesystem reset ho jata hai, is liye sirf normal
# restart/spin-down ke case me ye kaam karega, naye deploy me nahi.)
QUIZ_STORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quiz_store.json")


def load_quiz_store():
    """Bot start hote hi purane save kiye hue quizzes load karta hai.
    Pehle Google Drive try karta hai (agar configured hai, taaki naye
    deploy ke baad bhi data mile); nahi to local JSON file se load karta
    hai. Dono fail ho to khali dict se shuru karta hai — bot kabhi is
    wajah se crash nahi hoga."""
    drive_data = gdrive_store.load_from_drive()
    if drive_data is not None:
        print(f"[quiz_store] Google Drive se data load ho gaya ({len(drive_data)} quiz).")
        return drive_data
    else:
        print("[quiz_store] Drive se data nahi mila, local file try kar rahe hain.")

    try:
        if os.path.exists(QUIZ_STORE_FILE):
            with open(QUIZ_STORE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except Exception as e:
        print(f"quiz_store.json load karne me dikkat (ignore karke aage badh rahe hain): {e}")
    return {}


def save_quiz_store():
    """QUIZ_STORE ko local JSON file me aur (agar configured hai) Google
    Drive pe bhi save karta hai. Kisi bhi step ke fail hone par bhi bot
    crash nahi hoga, sirf warning print hoga."""
    try:
        with open(QUIZ_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(QUIZ_STORE, f, ensure_ascii=False)
    except Exception as e:
        print(f"quiz_store.json save karne me dikkat (ignore karke aage badh rahe hain): {e}")

    gdrive_saved = gdrive_store.save_to_drive(QUIZ_STORE)
    print(f"[quiz_store] Drive pe save {'successful' if gdrive_saved else 'nahi ho paya'}.")


QUIZ_STORE = load_quiz_store()

# Chalu (live) quiz sessions. chat_id -> session-dict
ACTIVE = {}

# poll_id -> chat_id, taaki poll_answer aane par pata chale kis session ka hai
POLL_TO_CHAT = {}

FORMAT_EXAMPLE = (
    "TITLE: Sample Quiz (optional, sabse upar)\n\n"
    "Q: Bharat ki rajdhani kya hai?\n"
    "A) Mumbai\n"
    "B) Delhi\n"
    "C) Kolkata\n"
    "D) Chennai\n"
    "ANSWER: B\n"
    "EXPLANATION: Delhi bharat ki rajdhani hai (yeh line optional hai)\n"
    "TIMER: 30 (optional, seconds mein)\n\n"
    "Q: Agla sawaal yahan?\n"
    "A) Option 1\n"
    "B) Option 2\n"
    "ANSWER: A"
)


@bot.message_handler(commands=["start", "help"])
def send_welcome(message):
    bot.reply_to(
        message,
        "Namaste! Mujhe neeche diye gaye format me questions (text message ya .txt file) "
        "bhejein. Main ek quiz taiyar kar dunga jise aap yahin shuru kar sakte hain, "
        "ya kisi bhi group mein bhej sakte hain.\n\n"
        "Quiz shuru hone ke baad questions ek-ek karke, timer ke saath aayenge — "
        "jaisa @QuizBot me hota hai.\n\n"
        "Format dekhne ke liye /format bhejein. Chalu quiz rokne ke liye /stop bhejein."
    )


@bot.message_handler(commands=["format"])
def send_format(message):
    bot.reply_to(message, "```\n" + FORMAT_EXAMPLE + "\n```", parse_mode="Markdown")


@bot.message_handler(commands=["stop"])
def handle_stop(message):
    chat_id = message.chat.id
    session = ACTIVE.get(chat_id)
    if session:
        session["stopped"] = True
        ACTIVE.pop(chat_id, None)
        bot.send_message(chat_id, "Quiz rok diya gaya.")
    else:
        bot.send_message(chat_id, "Koi quiz abhi chal nahi raha hai.")


@bot.message_handler(content_types=["document"])
def handle_document(message):
    try:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        text = downloaded.decode("utf-8", errors="ignore")
    except Exception as e:
        bot.reply_to(message, f"File padhne me error: {e}")
        return
    handle_new_quiz_text(message.chat.id, text)


@bot.message_handler(func=lambda m: not m.text.startswith("/"), content_types=["text"])
def handle_text(message):
    handle_new_quiz_text(message.chat.id, message.text)


def handle_new_quiz_text(chat_id, raw_text):
    """Text ko parse karke quiz save karta hai aur user ko button deta hai."""
    title, body = extract_title(raw_text)
    quizzes = parse_quizzes(body)

    if not quizzes:
        bot.send_message(
            chat_id,
            "Koi valid question nahi mila. Sahi format dekhne ke liye /format bhejein."
        )
        return

    quiz_id = uuid.uuid4().hex[:8]
    QUIZ_STORE[quiz_id] = {"title": title or "Custom Quiz", "quizzes": quizzes}
    save_quiz_store()

    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("Yahi chat mein shuru karo", callback_data=f"start:{quiz_id}"),
        types.InlineKeyboardButton("Group mein bhejo", switch_inline_query=quiz_id),
    )
    bot.send_message(
        chat_id,
        f"{len(quizzes)} question mile hain ('{title or 'Custom Quiz'}'). Ab neeche se chunein:",
        reply_markup=markup,
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("start:"))
def handle_start_button(call):
    quiz_id = call.data.split(":", 1)[1]
    bot.answer_callback_query(call.id, "Shuru kar raha hoon...")
    start_quiz_session(call.message.chat.id, quiz_id)


@bot.inline_handler(func=lambda query: True)
def handle_inline_query(inline_query):
    """Jab user kisi group mein bot ka naam type karke quiz_id daalta hai."""
    quiz_id = inline_query.query.strip()
    data = QUIZ_STORE.get(quiz_id)

    if not data:
        bot.answer_inline_query(inline_query.id, [], cache_time=1)
        return

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("Quiz shuru karo", callback_data=f"start:{quiz_id}"))

    result = types.InlineQueryResultArticle(
        id=quiz_id,
        title=f"{data['title']} ({len(data['quizzes'])} sawaal) bhejein",
        description="Is par tap karke is group mein quiz shuru karo",
        input_message_content=types.InputTextMessageContent(
            f"Quiz taiyar hai: {data['title']} ({len(data['quizzes'])} sawaal). "
            "Shuru karne ke liye neeche button dabayein:"
        ),
        reply_markup=markup,
    )
    bot.answer_inline_query(inline_query.id, [result], cache_time=1)


def start_quiz_session(chat_id, quiz_id):
    data = QUIZ_STORE.get(quiz_id)
    if not data:
        bot.send_message(chat_id, "Yeh quiz mil nahi raha (shayad bot restart hua). Naya text bhejein.")
        return

    quizzes = data["quizzes"]
    title = data["title"]

    timer_values = [q["timer"] for q in quizzes if q.get("timer")]
    default_timer = timer_values[0] if timer_values else DEFAULT_TIMER_SECONDS

    ACTIVE[chat_id] = {
        "quizzes": quizzes,
        "index": 0,
        "gen": 0,
        "stopped": False,
        "current_poll_id": None,
        "current_correct_id": None,
        "default_timer": default_timer,
        "scores": {},  # user_id -> {"name":, "correct":, "wrong":}
    }

    intro = (
        f"🎲 Get ready for the quiz '{title}'\n\n"
        f"✏️ {len(quizzes)} questions\n"
        f"⏱ {default_timer} seconds per question\n\n"
        f"🏁 Shuru ho raha hai... Rokne ke liye /stop bhejein."
    )
    bot.send_message(chat_id, intro)
    send_next_question(chat_id)


def send_next_question(chat_id):
    session = ACTIVE.get(chat_id)
    if not session or session["stopped"]:
        return

    idx = session["index"]
    quizzes = session["quizzes"]

    if idx >= len(quizzes):
        send_final_scores(chat_id, session, len(quizzes))
        ACTIVE.pop(chat_id, None)
        return

    q = quizzes[idx]
    timer = q.get("timer") or session["default_timer"]
    numbered_question = f"[{idx + 1}/{len(quizzes)}] {q['question']}"

    try:
        sent = bot.send_poll(
            chat_id=chat_id,
            question=numbered_question[:300],
            options=q["options"],
            type="quiz",
            correct_option_id=q["correct_option_id"],
            is_anonymous=False,
            explanation=q["explanation"] or "",
            open_period=timer,
        )
    except telebot.apihelper.ApiTelegramException as e:
        bot.send_message(chat_id, f"Question {idx + 1} bhejne me dikkat: {e}")
        session["index"] += 1
        send_next_question(chat_id)
        return

    poll_id = sent.poll.id
    POLL_TO_CHAT[poll_id] = chat_id
    session["current_poll_id"] = poll_id
    session["current_correct_id"] = q["correct_option_id"]
    session["gen"] += 1
    my_gen = session["gen"]

    def advance_after_timeout():
        time.sleep(timer + 2)
        s = ACTIVE.get(chat_id)
        if s and not s["stopped"] and s.get("gen") == my_gen:
            s["index"] += 1
            send_next_question(chat_id)

    threading.Thread(target=advance_after_timeout, daemon=True).start()


def _progress_bar(percent, length=10):
    filled = round((percent / 100) * length)
    filled = max(0, min(length, filled))
    return "🟩" * filled + "⬜" * (length - filled)


def send_final_scores(chat_id, session, total_questions):
    scores = session.get("scores", {})
    quizzes = session.get("quizzes", [])
    if not scores:
        bot.send_message(chat_id, "Quiz khatam! 🎉 (kisi ne bhi jawab nahi diya)")
        return

    ranked = sorted(scores.values(), key=lambda e: e["correct"], reverse=True)
    lines = ["🏆 Result:\n"]

    medals = ["🥇", "🥈", "🥉"]
    for i, e in enumerate(ranked):
        answered = e["correct"] + e["wrong"]
        correct_pct = round((e["correct"] / total_questions) * 100) if total_questions else 0
        wrong_pct = round((e["wrong"] / total_questions) * 100) if total_questions else 0
        medal = medals[i] if i < len(medals) else "▫️"

        lines.append(f"{medal} {e['name']}")
        lines.append(f"✅ Sahi: {e['correct']}/{total_questions} ({correct_pct}%)")
        lines.append(_progress_bar(correct_pct))
        lines.append(f"❌ Galat: {e['wrong']}/{total_questions} ({wrong_pct}%)")
        lines.append(_progress_bar(wrong_pct))
        lines.append("")  # khali line, agle user se pehle

    bot.send_message(chat_id, "Quiz khatam! 🎉\n\n" + "\n".join(lines).strip())

    # Jinhone galat jawab diye, unke liye ek "sirf galat wale sawaal se
    # naya quiz banao" button bhejte hain. Har user ke liye alag quiz
    # banta hai, taaki sirf unhi ke galat kiye hue questions shaamil hon.
    markup = types.InlineKeyboardMarkup(row_width=1)
    has_retry_button = False

    for user_id, e in scores.items():
        wrong_indices = e.get("wrong_indices") or []
        if not wrong_indices:
            continue

        wrong_quizzes = [quizzes[i] for i in wrong_indices if 0 <= i < len(quizzes)]
        if not wrong_quizzes:
            continue

        retry_quiz_id = uuid.uuid4().hex[:8]
        QUIZ_STORE[retry_quiz_id] = {
            "title": f"{e['name']} ke galat sawaal",
            "quizzes": wrong_quizzes,
        }
        has_retry_button = True
        markup.add(
            types.InlineKeyboardButton(
                f"🔁 {e['name']} ke {len(wrong_quizzes)} galat sawaal se naya quiz",
                callback_data=f"start:{retry_quiz_id}",
            )
        )

    if has_retry_button:
        save_quiz_store()
        bot.send_message(
            chat_id,
            "Chaho to sirf galat kiye hue sawaalon se dobara quiz bana sakte ho 👇",
            reply_markup=markup,
        )


@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):
    poll_id = poll_answer.poll_id
    chat_id = POLL_TO_CHAT.get(poll_id)
    if chat_id is None:
        return

    session = ACTIVE.get(chat_id)
    if not session or session["stopped"]:
        return
    if session.get("current_poll_id") != poll_id:
        return  # yeh purana/expired poll hai, ignore karo

    # Score record karte hain (option_ids khali hoga agar user ne vote hata diya)
    if poll_answer.option_ids:
        selected = poll_answer.option_ids[0]
        user = poll_answer.user
        name = user.first_name or "User"
        if user.last_name:
            name += f" {user.last_name}"
        scores = session.setdefault("scores", {})
        entry = scores.setdefault(user.id, {"name": name, "correct": 0, "wrong": 0, "wrong_indices": []})
        if selected == session.get("current_correct_id"):
            entry["correct"] += 1
        else:
            entry["wrong"] += 1
            entry["wrong_indices"].append(session["index"])

    my_gen = session["gen"]

    def advance_soon():
        time.sleep(POST_ANSWER_PAUSE)  # thoda time do taaki result dikh jaaye
        s = ACTIVE.get(chat_id)
        if s and not s["stopped"] and s.get("gen") == my_gen:
            s["index"] += 1
            send_next_question(chat_id)

    threading.Thread(target=advance_soon, daemon=True).start()


app = Flask(__name__)

# Webhook path me BOT_TOKEN daala hai taaki koi bahar wala isko guess na kar
# sake aur galat updates na bhej sake.
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"


@app.route(WEBHOOK_PATH, methods=["POST"])
def receive_webhook():
    """Telegram yahan naye updates POST karta hai (webhook mode)."""
    try:
        json_str = request.get_data().decode("utf-8")
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
    except Exception as e:
        print(f"Webhook update process karne me error: {e}")
    return "OK", 200


@app.route("/", methods=["GET"])
def health_check():
    """Render/UptimeRobot isi address ko ping karke bot ko jagaye rakhte hain."""
    return "Bot is alive", 200


def run_webhook_mode():
    """Telegram ko batata hai ki updates ab webhook (HTTP) ke through
    bhejein, polling ke through nahi — isse deploy ke dauraan purana aur
    naya instance ek saath 'getUpdates' call karke conflict nahi karte."""
    external_url = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("WEBHOOK_URL")

    try:
        bot.remove_webhook()
    except Exception as e:
        print(f"remove_webhook me warning (ignore kar rahe hain): {e}")
    time.sleep(1)

    if external_url:
        webhook_url = f"{external_url.rstrip('/')}{WEBHOOK_PATH}"
        try:
            bot.set_webhook(url=webhook_url)
            print(f"Webhook set ho gaya: {webhook_url}")
        except Exception as e:
            print(f"Webhook set karne me error: {e}")

        port = int(os.environ.get("PORT", 8080))
        app.run(host="0.0.0.0", port=port, threaded=True)
    else:
        # Local testing ke liye (jab RENDER_EXTERNAL_URL available nahi
        # hota) purane polling tarike par fallback karte hain.
        print("RENDER_EXTERNAL_URL nahi mila, isliye local polling mode me chal raha hai...")

        def run_local_ping_server():
            port = int(os.environ.get("PORT", 8080))
            app.run(host="0.0.0.0", port=port, threaded=True)

        threading.Thread(target=run_local_ping_server, daemon=True).start()
        bot.infinity_polling(skip_pending=True)


if __name__ == "__main__":
    print("Bot chal raha hai (webhook mode)...")
    run_webhook_mode()
