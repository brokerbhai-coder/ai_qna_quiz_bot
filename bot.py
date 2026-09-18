import os
import time
import uuid
import threading
import telebot
from telebot import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from quiz_parser import parse_quizzes, extract_title

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

# Har banaye gaye quiz ko yahan yaad rakhte hain (jab tak bot chalu hai).
# quiz_id -> {"title": str, "quizzes": [list of quiz-dicts]}
QUIZ_STORE = {}

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


def send_final_scores(chat_id, session, total_questions):
    scores = session.get("scores", {})
    if not scores:
        bot.send_message(chat_id, "Quiz khatam! 🎉 (kisi ne bhi jawab nahi diya)")
        return

    ranked = sorted(scores.values(), key=lambda e: e["correct"], reverse=True)
    lines = ["🏆 Result:"]
    for e in ranked:
        lines.append(f"{e['name']}: {e['correct']} sahi / {e['wrong']} galat (total {total_questions})")

    bot.send_message(chat_id, "Quiz khatam! 🎉\n\n" + "\n".join(lines))


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
        entry = scores.setdefault(user.id, {"name": name, "correct": 0, "wrong": 0})
        if selected == session.get("current_correct_id"):
            entry["correct"] += 1
        else:
            entry["wrong"] += 1

    my_gen = session["gen"]

    def advance_soon():
        time.sleep(POST_ANSWER_PAUSE)  # thoda time do taaki result dikh jaaye
        s = ACTIVE.get(chat_id)
        if s and not s["stopped"] and s.get("gen") == my_gen:
            s["index"] += 1
            send_next_question(chat_id)

    threading.Thread(target=advance_soon, daemon=True).start()


class _PingHandler(BaseHTTPRequestHandler):
    """Render/UptimeRobot isi address ko ping karke bot ko jagaye rakhte hain."""

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive")

    def log_message(self, format, *args):
        pass  # HTTP logs chup rakhte hain, sirf bot ke logs dikhenge


def start_ping_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), _PingHandler)
    server.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=start_ping_server, daemon=True).start()
    print("Bot chal raha hai... (band karne ke liye Ctrl+C dabayein)")
    bot.infinity_polling(skip_pending=True)
