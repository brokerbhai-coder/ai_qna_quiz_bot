# Telegram Quiz Bot

Ye bot ek hi kaam karta hai: aap use ek **fixed text format** me questions bhejo
(text message ya `.txt` file), aur ye unko turant **Telegram Quiz Poll** bana kar
bhej deta hai (multiple-choice poll jisme sahi jawab bot khud check karta hai).

Workflow bilkul waisa hi hai jaisa aapne socha tha:
1. Apne raw questions kisi bhi AI (Claude, ChatGPT, etc.) ko do, niche wala
   "AI Prompt Template" use karke.
2. AI se aaya hua formatted text copy karo.
3. Us text ko is bot ko bhej do (ya `.txt` file bana kar upload karo).
4. Bot automatically Telegram Quiz Poll bana kar bhej dega.

---

## 1. BotFather se Bot Token lena

1. Telegram me `@BotFather` ko message karo.
2. `/newbot` bhejo, naam aur username set karo.
3. Wo jo token dega (kuch is tarah: `123456:ABC-DEF...`) use safe rakho.

---

## 2. Local setup (apne computer par test karne ke liye)

```bash
cd telegram_quiz_bot
python -m venv venv
source venv/bin/activate      # Windows par: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env file kholo aur BOT_TOKEN=xxxx me apna asli token daalo

python bot.py
```

Bot chalu ho jayega. Ab Telegram me apne bot ko `/start` bhejo, phir `/format`
bhej kar format dekh lo, aur `example_questions.txt` ka content copy-paste
karke test kar lo.

---

## 3. Question format (yehi format AI ko bhi bolna hai)

```
Q: Bharat ki rajdhani kya hai?
A) Mumbai
B) Delhi
C) Kolkata
D) Chennai
ANSWER: B
EXPLANATION: Delhi bharat ki rajdhani hai (optional line)
```

Rules:
- Har question ke baad ek **khali line** zaroor rakho (agla question alag block me).
- Options `A)` se `J)` tak (max 10 options, min 2).
- `ANSWER:` me sirf sahi option ka letter (jaise `B`).
- `EXPLANATION:` optional hai, poll ke jawab dene ke baad dikhta hai.

---

## 4. AI Prompt Template (isko apne AI tool me paste karo)

Apne raw questions ke saath ye prompt kisi bhi AI ko do:

```
Neeche diye gaye questions ko is exact format me convert karo, koi extra
text ya heading mat jodo:

Q: [question]
A) [option 1]
B) [option 2]
C) [option 3]
D) [option 4]
ANSWER: [sahi option ka letter, jaise B]
EXPLANATION: [ek line explanation, optional]

Har question ke beech ek khali line rakho.

Yahan questions hain:
[apne questions yahan paste karo]
```

AI ka output seedha copy karke bot ko bhej do.

---

## 5. GitHub par daalna

```bash
cd telegram_quiz_bot
git init
git add .
git commit -m "Telegram quiz bot - initial version"
git branch -M main
git remote add origin https://github.com/<aapka-username>/<repo-naam>.git
git push -u origin main
```

`.env` file `.gitignore` me hai, isliye aapka token GitHub par kabhi nahi
jayega — safe hai. GitHub par sirf code jayega, token nahi.

---

## 6. Bot ko GitHub Actions se chalana (button + roz-ka-schedule, dono)

Aapko bot 24x7 nahi, sirf padhai/quiz ke waqt (2-3 ghante) chahiye — isliye
poori GitHub Actions `.github/workflows/bot.yml` file already bana di gayi
hai jisme **dono** tarike ek saath hain:

1. **Jab chaho khud chalu karo** — GitHub repo ke `Actions` tab me jaakar
   "Study Quiz Bot" workflow kholo, "Run workflow" button dabao. Bot turant
   chalu ho jayega.
2. **Roz ek tay samay par apne aap chalu** — abhi file me set hai
   **daily 12:00 PM IST**. Time badalna ho to file me ye line dhoondo:

   ```yaml
   - cron: '30 6 * * *'   # 06:30 UTC = 12:00 PM IST
   ```

   Cron hamesha **UTC** me likha jaata hai (IST = UTC + 5:30). Jaise agar
   shaam 5 baje (IST) chahiye to UTC hoga 11:30, to line hogi
   `cron: '30 11 * * *'`.

**Zaroori limit:** GitHub ka ek single run zyada se zyada **6 ghante** tak
hi chal sakta hai (ye unka hard limit hai, badhaya nahi ja sakta). File me
`timeout-minutes: 355` set hai, matlab 12 baje shuru hokar bot khud-ba-khud
~5:55 PM tak chalega. Agar usse aage bhi chahiye, bas dobara "Run workflow"
button dabao — turant agle kuch ghanto ke liye phir chalu ho jayega.

Workflow me pehle se `concurrency` block bhi hai, isliye agar aap manually
button dabao jab scheduled run already chal rahi ho, purani run apne aap
cancel ho jayegi aur sirf ek hi bot-instance chalega (isse Telegram wala
"Conflict" error kabhi nahi aayega).

### Setup steps

1. Repo me `.github/workflows/bot.yml` file (already di gayi hai) commit
   aur push kar do.
2. GitHub repo kholo → **Settings → Secrets and variables → Actions →
   New repository secret**
   - Name: `BOT_TOKEN`
   - Value: apna BotFather wala token
3. `Actions` tab me jaakar ek baar "Run workflow" dabakar test kar lo.

**Note:** Agar repo me 60 din tak koi bhi commit/activity na ho to GitHub
scheduled workflow ko khud disable kar deta hai — kabhi-kabhaar ek chhota
sa commit (jaise README me kuch edit) karte rehna theek rahega.

### Agar kabhi sach me poora 24x7 chahiye ho

Upar wala tarika sirf **decided hours** ke liye hai. Agar bhavishya me
poore din bot online rakhna pade (jaise koi group/channel handle karna ho),
to GitHub Actions sahi jagah nahi hai — uske liye Railway.app, Render.com
(Background Worker), PythonAnywhere ka "Always-on task", ya ek chhota VPS
(Oracle Cloud free tier) jaisa real hosting use karna better rahega.

---

## Files

| File | Kaam |
|---|---|
| `bot.py` | Main bot — messages/files receive karta hai, quiz poll bhejta hai |
| `quiz_parser.py` | Text format ko parse karke question-list banata hai |
| `requirements.txt` | Python dependencies |
| `.env.example` | Token rakhne ka template (local testing ke liye) |
| `example_questions.txt` | Test karne ke liye sample questions |
| `.github/workflows/bot.yml` | GitHub Actions — button + daily schedule, dono se bot chalane ke liye |

