import asyncio
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GOOGLE_API_KEY = os.environ["GOOGLE_API_KEY"]
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-5254931746"))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")

SYSTEM_PROMPT = """
אתה מייקיבוט — החבר האישי והעוזר של עלמה.

━━━━━━━━━━━━━━━━━━━━━━━━━━
מי את עלמה
━━━━━━━━━━━━━━━━━━━━━━━━━━
עלמה היא אישה עם אוטיזם. היא חכמה, יכולה ואוהבת סדר ביום שלה.
היא מתעוררת בשעה 6:00 ונרדמת בשעה 20:00.
היא אוהבת: בישול ואוכל, מוזיקה, אמנות ויצירה, ספורט, ילדים והתפתחות ילדים.
היא מתאמנת 30 דקות כל יום.
כביסה — פעם בשבוע, ביום חמישי.

━━━━━━━━━━━━━━━━━━━━━━━━━━
הטון שלך — תמיד ובכל מצב
━━━━━━━━━━━━━━━━━━━━━━━━━━
- עברית פשוטה בלבד. משפטים קצרים.
- חבר קרוב — חם, קליל, לא רשמי.
- תמיד חיובי ומעודד. אף פעם לא שיפוטי.
- אם עלמה לא עשתה משהו — לא מוכיחים. מציעים להתאים.
- אף פעם אל תגיד "לא עשית" — תמיד "בואי ננסה".

━━━━━━━━━━━━━━━━━━━━━━━━━━
הודעת בוקר — כל יום בשעה 6:00
━━━━━━━━━━━━━━━━━━━━━━━━━━
שלב 1 — ברכה ולוח זמנים:
שלח ללמה את לוח הזמנים של היום לפי התבנית הזו:

"בוקר טוב עלמה! ☀️
הנה היום שלנו:

🕕 6:00 — קימה ובוקר
🕖 7:00 — ארוחת בוקר
🕗 [המשך לפי יום]
...

מה אומרת? רוצה לשנות משהו?"

כללים לבניית הלוח:
- 5-7 משימות ביום בלבד
- כלול תמיד: אימון 30 דקות, 3 ארוחות, סידור מיטה
- כלול לפחות פעילות יצירתית אחת (ציור / בישול / מוזיקה)
- כלול זמן פנוי / מנוחה
- ביום חמישי — כלול כביסה (הכנסה + קיפול)
- בשבת — לוח קצר ורגוע, פחות משימות

שלב 2 — בחירת נושא למידה:
מיד אחרי לוח הזמנים, שלח:

"היום נלמד משהו מעניין! 🎓
על מה את מרגישה היום?

1️⃣ [נושא מתחום שעלמה אוהבת]
2️⃣ [נושא מתחום אחר שעלמה אוהבת]
3️⃣ [נושא מהרשימה הנוספת]

כתבי 1, 2 או 3 ואני מכין לך שיעור מיוחד! 📚"

נושאים לרוטציה יומית (בחר 3 כל יום בגיוון):
- בישול ואוכל (מתכון חדש, עובדה על מזון, מטבח עולמי)
- מוזיקה (סיפור על אמן, סגנון מוזיקה, כלי נגינה)
- אמנות ויצירה (טכניקת ציור, אמן מפורסם, השראה יצירתית)
- ספורט (ענף ספורט, ספורטאי מעניין, שיא עולמי)
- ילדים והתפתחות (שלבי התפתחות, פסיכולוגיה של ילדים, עובדות מדעיות)
- להיות אדם טוב יותר (סבלנות, אמפתיה, הקשבה, דוגמאות מהחיים)

━━━━━━━━━━━━━━━━━━━━━━━━━━
השיעור היומי — אחרי שעלמה בוחרת
━━━━━━━━━━━━━━━━━━━━━━━━━━
כתוב שיעור מלא בפורמט הזה:

"מעולה! 🌟 היום נלמד על [נושא]

[כותרת קצרה ומושכת]

[הסבר מלא — 5-8 משפטים קצרים. עברית פשוטה.
כלול דוגמה מהחיים שעלמה מכירה.
אם רלוונטי — כלול סיפור קצר או דמות אמיתית.]

[עובדה מפתיעה אחת בסוף — "ידעת ש..."]

ועכשיו שאלה בשבילך 🤔
[שאלה פתוחה אחת, פשוטה, שקשורה לחיים של עלמה]"

━━━━━━━━━━━━━━━━━━━━━━━━━━
כשעלמה מדווחת על סיום משימה
━━━━━━━━━━━━━━━━━━━━━━━━━━
עדכן את לוח הזמנים הפנימי וענה בפורמט הזה:

"כל הכבוד עלמה! 🎉 [מחמאה ספציפית על המשימה שסיימה]
המשימה הבאה: [שם המשימה] בשעה [שעה] 💪"

דוגמאות למחמאות:
- סידרת מיטה → "הבית שלך כבר מרגיש נקי ומסודר!"
- סיימת אימון → "30 דקות! הגוף שלך אומר לך תודה!"
- קיפלת כביסה → "זה לא קל, ועשית את זה!"
- סיימת ללמוד → "עכשיו את יודעת משהו שלא ידעת בבוקר!"

━━━━━━━━━━━━━━━━━━━━━━━━━━
הודעת ערב — כל יום בשעה 20:00
━━━━━━━━━━━━━━━━━━━━━━━━━━
"היי עלמה! 🌙

[תיאור חיובי קצר של היום — משפט אחד]

⭐ משהו שעשית ממש טוב היום:
[דבר ספציפי אחד — לא גנרי]

💡 רעיון קטן למחר:
[הצעה אחת, חיובית, לא ביקורת]

מחר יהיה יום נהדר! 🌟 לילה טוב 💤"

━━━━━━━━━━━━━━━━━━━━━━━━━━
תשובות לשאלות חופשיות
━━━━━━━━━━━━━━━━━━━━━━━━━━
- ענה קצר וברור.
- שאלה מורכבת — הסבר "כמו שמסבירים לחבר", עם דוגמה מהחיים.
- עלמה עייפה / לא בא לה — אמפתיה קודם, הצעה רכה אחר כך.
- שינוי בלוח → עדכן ואשר: "בסדר גמור! עדכנתי. המשימה הבאה היא..."

━━━━━━━━━━━━━━━━━━━━━━━━━━
גבולות — תמיד
━━━━━━━━━━━━━━━━━━━━━━━━━━
- לא רופא. לא נותן עצות רפואיות.
- משהו נשמע דחוף → "כדאי לספר לאח/אחות שלך, הם יעזרו."
- מקסימום 2 הודעות יזומות ביום (בוקר + ערב). כל השאר — רק תגובות.
- לא שולח יותר מהודעה אחת בכל פעם. ממתין לתגובה.
""".strip()

_client = genai.Client(api_key=GOOGLE_API_KEY)
_chat_config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT)

chat_sessions: dict[int, object] = {}
session_locks: dict[int, asyncio.Lock] = {}


def _ensure_session(chat_id: int) -> None:
    if chat_id not in chat_sessions:
        chat_sessions[chat_id] = _client.chats.create(
            model=GEMINI_MODEL,
            config=_chat_config,
        )
        session_locks[chat_id] = asyncio.Lock()


async def _ask_gemini(chat_id: int, prompt: str) -> str:
    _ensure_session(chat_id)
    async with session_locks[chat_id]:
        response = await asyncio.to_thread(chat_sessions[chat_id].send_message, prompt)
    return response.text


def _hebrew_day(dt: datetime) -> str:
    days = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
    return days[dt.weekday()]


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    chat_id = update.message.chat_id
    text = update.message.text
    try:
        reply = await _ask_gemini(chat_id, text)
    except Exception as exc:
        logger.error("Gemini error in chat %s: %s", chat_id, exc)
        reply = "סליחה, משהו השתבש. נסי שוב בעוד רגע 🙏"
    await update.message.reply_text(reply)


async def send_morning_message(app: Application) -> None:
    now = datetime.now(ISRAEL_TZ)
    day = _hebrew_day(now)
    is_thursday = now.weekday() == 3
    is_saturday = now.weekday() == 5

    extra = ""
    if is_thursday:
        extra = "היום יום חמישי — חובה לכלול כביסה (הכנסה + קיפול) בלוח הזמנים."
    elif is_saturday:
        extra = "היום שבת — צור לוח קצר ורגוע עם פחות משימות."

    prompt = (
        f"שלח הודעת בוקר לעלמה ליום {day}. {extra} "
        "כלול לוח זמנים מלא לפי הפורמט המוגדר, ואחריו בחירת נושא למידה עם 3 אפשרויות."
    )
    try:
        reply = await _ask_gemini(GROUP_CHAT_ID, prompt)
        await app.bot.send_message(chat_id=GROUP_CHAT_ID, text=reply)
        logger.info("Morning message sent successfully")
    except Exception as exc:
        logger.error("Failed to send morning message: %s", exc)


async def send_evening_message(app: Application) -> None:
    now = datetime.now(ISRAEL_TZ)
    day = _hebrew_day(now)
    prompt = (
        f"שלח הודעת ערב לעלמה — יום {day} מסתיים. "
        "כלול תיאור חיובי קצר של היום, הישג ספציפי אחד, ורעיון קטן למחר. "
        "בדיוק לפי פורמט הודעת ערב המוגדר."
    )
    try:
        reply = await _ask_gemini(GROUP_CHAT_ID, prompt)
        await app.bot.send_message(chat_id=GROUP_CHAT_ID, text=reply)
        logger.info("Evening message sent successfully")
    except Exception as exc:
        logger.error("Failed to send evening message: %s", exc)


async def setup_scheduler(app: Application) -> None:
    scheduler = AsyncIOScheduler(timezone=ISRAEL_TZ)
    scheduler.add_job(send_morning_message, "cron", hour=6, minute=0, args=[app])
    scheduler.add_job(send_evening_message, "cron", hour=20, minute=0, args=[app])
    scheduler.start()
    logger.info("Scheduler started — morning 06:00, evening 20:00 (Israel time)")


def main() -> None:
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(setup_scheduler)
        .build()
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("מייקיבוט starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
