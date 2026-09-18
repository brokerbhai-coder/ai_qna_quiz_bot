"""
Quiz Parser
============
Simple text format ko Telegram "Quiz Poll" ke liye parse karta hai.

Expected format (har question ke beech ek KHALI LINE zaroor rakhein):

Q: Bharat ki rajdhani kya hai?
A) Mumbai
B) Delhi
C) Kolkata
D) Chennai
ANSWER: B
EXPLANATION: Delhi bharat ki rajdhani hai (yeh line optional hai)
TIMER: 30 (optional, seconds mein - itne second baad poll khud band ho jayega)

Sabse pehli line mein optional quiz TITLE bhi likh sakte hain:

TITLE: Class 12 Chemistry Chapter 1
"""

import re

MAX_QUESTION_LEN = 300
MAX_OPTION_LEN = 100
MAX_EXPLANATION_LEN = 200
MIN_TIMER_SECONDS = 5
MAX_TIMER_SECONDS = 600  # Telegram ka hard limit


def extract_title(raw_text: str):
    """Agar text ki pehli line 'TITLE: ...' ho to (title, baaki_text) return
    karta hai. Warna (None, raw_text) return karta hai."""
    lines = raw_text.strip().splitlines()
    if lines:
        match = re.match(r"^(?:TITLE)\s*[:\-]\s*(.+)$", lines[0].strip(), re.IGNORECASE)
        if match:
            title = match.group(1).strip()
            rest = "\n".join(lines[1:])
            return title, rest
    return None, raw_text


def parse_quizzes(raw_text: str):
    """Raw text se list of quiz-dicts return karta hai.

    Har dict me hota hai: question, options (list), correct_option_id, explanation, timer
    """
    quizzes = []
    blocks = re.split(r"\n\s*\n", raw_text.strip())

    for block in blocks:
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue

        question = None
        options = []
        answer_letter = None
        explanation = None
        timer_seconds = None

        for line in lines:
            ans_match = re.match(r"^(?:ANSWER|ANS|CORRECT)\s*[:\-]\s*([A-J])", line, re.IGNORECASE)
            exp_match = re.match(r"^(?:EXPLANATION|EXPLAIN)\s*[:\-]\s*(.+)$", line, re.IGNORECASE)
            timer_match = re.match(r"^(?:TIMER|TIME)\s*[:\-]\s*(\d+)", line, re.IGNORECASE)
            opt_match = re.match(r"^([A-J])[\).\-]\s*(.+)$", line)
            q_match = re.match(r"^Q\d*\s*[:\.\)]\s*(.+)$", line, re.IGNORECASE)

            if ans_match:
                answer_letter = ans_match.group(1).upper()
            elif timer_match:
                timer_seconds = int(timer_match.group(1))
            elif exp_match:
                explanation = exp_match.group(1).strip()
            elif opt_match:
                options.append(opt_match.group(2).strip())
            elif q_match and question is None:
                question = q_match.group(1).strip()
            elif question is None:
                question = line

        if not question or len(options) < 2 or not answer_letter:
            continue  # incomplete block, skip kar do

        correct_index = ord(answer_letter) - ord("A")
        if correct_index >= len(options):
            continue  # ANSWER letter options se match nahi hua

        if timer_seconds is not None:
            timer_seconds = max(MIN_TIMER_SECONDS, min(timer_seconds, MAX_TIMER_SECONDS))

        quizzes.append({
            "question": question[:MAX_QUESTION_LEN],
            "options": [o[:MAX_OPTION_LEN] for o in options[:10]],
            "correct_option_id": correct_index,
            "explanation": (explanation[:MAX_EXPLANATION_LEN] if explanation else None),
            "timer": timer_seconds,
        })

    return quizzes
  
