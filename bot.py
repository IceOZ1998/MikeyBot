import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import uvicorn
from fastapi import FastAPI, Request, Response
from google import genai
from google.genai import types
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters
from telegram.error import NetworkError

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN  = os.environ["TELEGRAM_TOKEN"]
GOOGLE_API_KEY  = os.environ["GOOGLE_API_KEY"]
GROUP_CHAT_ID   = int(os.getenv("GROUP_CHAT_ID", "-5254931746"))
GEMINI_MODEL    = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
ISRAEL_TZ = ZoneInfo("Asia/Jerusalem")
PORT = int(os.getenv("PORT", "8080"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")

SYSTEM_PROMPT = """
אתה מייקיבוט — החבר הכי טוב של עלמה בטלגרם.

## האישיות שלך
אתה חבר אמיתי, חם, סבלני ומצחיק קלות. אתה מדבר עברית פשוטה וקצרה.
אתה לא רובוט ולא יומן משימות — אתה חבר שאוהב לשוחח.
אתה זוכר שעלמה יש אוטיזם ולקות ראייה, אז אתה תמיד ברור, פשוט וחיובי.

## כללי תקשורת — חשוב מאוד
- אף פעם אל תחזור על רשימת המשימות באמצע שיחה
- אם עלמה שואלת שאלה — עני על השאלה בלבד
- אם עלמה מספרת משהו — הגב כמו חבר, לא כמו מנהל
- אם עלמה אומרת "סיימתי [משימה]" — תן מחמאה קצרה וחמה, זהו
- אל תציין "המשימה הבאה" אלא אם עלמה שאלה ספציפית
- משפטים קצרים תמיד. מקסימום 3-4 משפטים בתשובה
- השתמש באמוג'י בצורה טבעית, לא מוגזמת

## מתי כן מציגים משימות
- רק בהודעת הבוקר האוטומטית בשעה 6:00
- רק אם עלמה מבקשת: "מה המשימות שלי?" / "מה יש היום?" / "תראה לי את הלוז" או בקשה דומה

## הודעת בוקר — שעה 6:00
שלח הודעה חמה עם לוח זמנים מלא מ-6:00 עד 18:00 בפורמט:

"בוקר טוב עלמה! ☀️ מוכנה להיום?

הנה היום שלנו:
🕕 6:00 — קימה ובוקר
🕖 7:00 — ארוחת בוקר 🍳
🕗 9:00 — אימון 30 דקות 💪
🕙 10:00 — [פעילות]
🕛 13:00 — ארוחת צהריים 🥗
🕑 14:00 — [פעילות]
🕓 16:00 — [פעילות]
🕔 17:00 — זמן חופשי 🎵
🕕 18:00 — ארוחת ערב 🍽️

היום נלמד על אחד מהנושאים האלה, מה מתחשק לך?
1️⃣ [נושא מתחום שעלמה אוהבת]
2️⃣ [נושא מתחום אחר]
3️⃣ [נושא מתחום שלישי]"

כללים לבניית הלוח:
- תמיד כלול 3 ארוחות (7:00, 13:00, 18:00)
- תמיד כלול אימון 30 דקות בבוקר
- תמיד כלול זמן חופשי
- ביום חמישי — כלול כביסה
- שבת — לוח קצר ורגוע
- גוון את הפעילויות: בישול, ציור, מוזיקה, למידה, הליכה

נושאי הלמידה לרוטציה:
- בישול ואוכל
- מוזיקה ואמנות
- ספורט וספורטאים
- ילדים והתפתחות
- להיות אדם טוב יותר — סבלנות, אמפתיה, הקשבה

## שיעור יומי — אחרי שעלמה בוחרת נושא
כתוב שיעור מעניין בפורמט:
"מגניב שבחרת! 🌟

[כותרת מושכת]

[הסבר של 5-6 משפטים קצרים עם דוגמה מהחיים]

ידעת ש... [עובדה מפתיעה אחת]

ומה את חושבת — [שאלה פתוחה אחת קצרה]?"

## הודעת ערב — שעה 20:00
"היי עלמה! 🌙

[משפט חיובי אחד על היום]
[דבר אחד ספציפי שעשית טוב]
[הצעה קטנה אחת לא ביקורתית למחר]

לילה טוב! 💤"

## גבולות
- לא רופא, לא נותן עצות רפואיות
- משהו דחוף → "כדאי לספר לאח שלך"
- תמיד חיובי, אף פעם לא שיפוטי
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


async def _ask_gemini(chat_id: int, prompt) -> str:
    """שולח הודעה ל-Gemini. על 429 — נכשל מיד (ללא המתנה). על שגיאה אחרת — ניסיון חוזר אחד."""
    _ensure_session(chat_id)
    async with session_locks[chat_id]:
        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(chat_sessions[chat_id].send_message, prompt),
                timeout=25.0,
            )
            return response.text
        except asyncio.TimeoutError:
            logger.error("Gemini timeout for chat %s", chat_id)
            raise
        except Exception as exc:
            err = str(exc)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                logger.warning("Rate limit hit for chat %s", chat_id)
                raise  # נכשל מיד — אין המתנה של דקה
            # שגיאה אחרת — ניסיון חוזר אחד אחרי 2 שניות
            logger.warning("Gemini error, retrying once: %s", exc)
            await asyncio.sleep(2)
            response = await asyncio.wait_for(
                asyncio.to_thread(chat_sessions[chat_id].send_message, prompt),
                timeout=25.0,
            )
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
        err = str(exc)
        logger.error("Gemini error in chat %s: %s", chat_id, exc)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            reply = "עלמה, יש לי הרבה מדי שאלות עכשיו 😅 נסי שוב בעוד דקה!"
        else:
            reply = "רגע אחד עלמה, אני חושב... נסי שוב עוד שנייה 😊"
    await update.message.reply_text(reply)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.voice:
        return
    chat_id = update.message.chat_id
    try:
        voice_file = await update.message.voice.get_file()
        audio_bytes = await voice_file.download_as_bytearray()
        prompt = [
            types.Part.from_bytes(data=bytes(audio_bytes), mime_type="audio/ogg"),
            "האזן להודעה הקולית. הבן מה עלמה אומרת וענה לה בעברית כמו שהיית עונה להודעת טקסט.",
        ]
        reply = await _ask_gemini(chat_id, prompt)
    except Exception as exc:
        err = str(exc)
        logger.error("Voice error in chat %s: %s", chat_id, exc)
        if "429" in err or "RESOURCE_EXHAUSTED" in err:
            reply = "עלמה, יש לי הרבה מדי שאלות עכשיו 😅 נסי שוב בעוד דקה!"
        else:
            reply = "רגע אחד עלמה, אני חושב... נסי שוב עוד שנייה 😊"
    await update.message.reply_text(reply)


async def send_morning_message(app: Application) -> None:
    now = datetime.now(ISRAEL_TZ)
    day = _hebrew_day(now)
    extra = ""
    if now.weekday() == 3:
        extra = "היום יום חמישי — חובה לכלול כביסה בלוח."
    elif now.weekday() == 5:
        extra = "היום שבת — לוח קצר ורגוע."
    prompt = (
        f"שלח הודעת בוקר לעלמה ליום {day}. {extra} "
        "כלול לוח זמנים מלא מ-6:00 עד 18:00 עם 3 ארוחות (7:00, 13:00, 18:00), "
        "אימון בבוקר, זמן חופשי, ופעילות מגוונת. אחרי הלוח — 3 אפשרויות נושא למידה."
    )
    try:
        reply = await _ask_gemini(GROUP_CHAT_ID, prompt)
        await app.bot.send_message(chat_id=GROUP_CHAT_ID, text=reply)
        logger.info("Morning message sent")
    except Exception as exc:
        logger.error("Failed to send morning message: %s", exc)



async def send_evening_message(app: Application) -> None:
    now = datetime.now(ISRAEL_TZ)
    day = _hebrew_day(now)
    prompt = (
        f"שלח הודעת ערב לעלמה — יום {day} מסתיים. "
        "כלול תיאור חיובי קצר של היום, הישג ספציפי אחד, ורעיון קטן למחר. "
        "לפי פורמט הודעת ערב המוגדר."
    )
    try:
        reply = await _ask_gemini(GROUP_CHAT_ID, prompt)
        await app.bot.send_message(chat_id=GROUP_CHAT_ID, text=reply)
        logger.info("Evening message sent")
    except Exception as exc:
        logger.error("Failed to send evening message: %s", exc)


# ── Telegram Application ──────────────────────────────────────────────────────
application = Application.builder().token(TELEGRAM_TOKEN).updater(None).build()
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.VOICE, handle_voice))


# ── FastAPI ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app_web: FastAPI):
    # Start bot
    await application.initialize()
    await application.start()

    # Register webhook with Telegram
    if WEBHOOK_URL:
        await application.bot.set_webhook(
            url=f"{WEBHOOK_URL}/webhook",
            allowed_updates=Update.ALL_TYPES,
        )
        logger.info("Webhook set: %s/webhook", WEBHOOK_URL)
    else:
        logger.warning("WEBHOOK_URL not set — webhook not registered")

    # Start scheduler
    scheduler = AsyncIOScheduler(timezone=ISRAEL_TZ)
    scheduler.add_job(send_morning_message, "cron", hour=6,  minute=0, args=[application])
    scheduler.add_job(send_evening_message, "cron", hour=20, minute=0, args=[application])
    scheduler.start()
    logger.info("Scheduler started — morning 06:00, evening 20:00 (Israel time)")
    logger.info("מייקיבוט ready!")

    yield

    scheduler.shutdown()
    await application.stop()
    await application.shutdown()


web = FastAPI(lifespan=lifespan)


@web.post("/webhook")
async def webhook(request: Request) -> Response:
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return Response(status_code=200)


@web.get("/health")
async def health() -> dict:
    return {"status": "ok", "bot": "מייקיבוט"}


if __name__ == "__main__":
    uvicorn.run(web, host="0.0.0.0", port=PORT)
