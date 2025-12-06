import os
import io
import logging
import requests
from flask import Flask, request, jsonify
from openai import OpenAI

# ============= إعداد الأساسيات =============

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = app.logger

# مفاتيح البيئة من Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WHAPI_BASE_URL = os.getenv("WHAPI_BASE_URL", "https://gate.whapi.cloud")
WHAPI_TOKEN = os.getenv("WHAPI_TOKEN")

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is not set!")

if not WHAPI_BASE_URL or not WHAPI_TOKEN:
    logger.warning("WHAPI_BASE_URL or WHAPI_TOKEN is not set!")

# عميل OpenAI (المكتبة الجديدة)
client = OpenAI(api_key=OPENAI_API_KEY)

# ============= دوال مساعدة =============

def send_whapi_text(to_number: str, body: str):
    """
    إرسال رسالة نصية عبر Whapi إلى رقم واتساب.
    to_number مثال: "213776206336"
    """
    if not (WHAPI_BASE_URL and WHAPI_TOKEN):
        logger.error("Cannot send message: WHAPI_BASE_URL / WHAPI_TOKEN missing.")
        return

    url = f"{WHAPI_BASE_URL}/messages/text"
    headers = {"Authorization": f"Bearer {WHAPI_TOKEN}"}
    payload = {
        "to": to_number,
        "body": body,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        logger.info("Whapi send response: %s %s", resp.status_code, resp.text)
    except Exception as e:
        logger.exception("Error sending message via Whapi: %s", e)


def transcribe_from_url(audio_url: str, mime_type: str = "audio/ogg"):
    """
    تحميل ملف صوتي من رابط (من Whapi) ثم تفريغه نصيًا باستخدام OpenAI.
    يُرجع نص التفريغ أو None في حالة الخطأ.
    """
    try:
        logger.info("Downloading audio from: %s", audio_url)
        r = requests.get(audio_url, timeout=30)
        r.raise_for_status()
        audio_bytes = r.content

        buf = io.BytesIO(audio_bytes)
        buf.name = "voice_message.oga"  # اسم افتراضي ليقبله OpenAI

        transcript = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=buf,
            # يمكن ترك اللغة ليكتشفها النموذج تلقائياً
            # language="ar"
        )
        text = transcript.text.strip()
        logger.info("Transcription result: %s", text)
        return text
    except Exception as e:
        logger.exception("Error while transcribing audio: %s", e)
        return None


def generate_reply(user_text: str) -> str:
    """
    توليد رد ذكي من OpenAI بناءً على نص المستخدم.
    """
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "أنت وكيل افتراضي لمطعم جزائري. "
                        "ترد باللهجة الجزائرية البسيطة أو العربية أو الفرنسية حسب لغة الزبون. "
                        "ساعد الزبون في طلب الأكل، اقتراح الأطباق، طرح أسئلة للتوضيح، "
                        "واطلب العنوان ورقم الهاتف إذا كان طلب توصيل."
                    ),
                },
                {
                    "role": "user",
                    "content": user_text,
                },
            ],
        )
        answer = completion.choices[0].message.content.strip()
        logger.info("LLM reply: %s", answer)
        return answer
    except Exception as e:
        logger.exception("Error calling OpenAI: %s", e)
        return "صار مشكل تقني صغير في السيرفر، جرّب تعاود بعد دقيقـة برك."


def extract_from_number(msg: dict) -> str | None:
    """
    استخراج رقم المرسل من payload الخاص بـ Whapi.
    """
    from_number = msg.get("from")
    if from_number:
        return from_number

    chat_id = msg.get("chat_id")
    if chat_id and "@s.whatsapp.net" in chat_id:
        return chat_id.split("@")[0]

    return None

# ============= المسارات =============

@app.route("/")
def index():
    return "WhatsApp Voice/Text bot is running.", 200


@app.route("/whapi", methods=["POST"])
def whapi_webhook():
    """
    Webhook يستقبل الأحداث القادمة من Whapi:
    - رسائل نصية
    - رسائل صوتية (voice)
    """
    data = request.get_json(force=True, silent=True) or {}
    logger.info("Incoming Whapi webhook: %s", data)

    # إذا كان الحدث ليس من نوع messages (مثلاً statuses) نكتفي بالتأكيد
    event = data.get("event") or {}
    if event.get("type") != "messages":
        return jsonify({"ok": True})

    messages = data.get("messages") or []
    if not messages:
        return jsonify({"ok": True})

    msg = messages[0]
    msg_type = msg.get("type")
    logger.info("Message type: %s", msg_type)

    from_number = extract_from_number(msg)
    if not from_number:
        logger.warning("No from_number in webhook payload.")
        return jsonify({"ok": True})

    # ---------- رسائل نصية ----------
    if msg_type == "text":
        user_text = (msg.get("text") or {}).get("body", "").strip()
        if not user_text:
            return jsonify({"ok": True})

        reply = generate_reply(user_text)
        send_whapi_text(from_number, reply)
        return jsonify({"ok": True})

    # ---------- رسائل صوتية ----------
    if msg_type in ("voice", "audio"):
        voice_info = msg.get("voice") or msg.get("audio") or {}
        audio_link = voice_info.get("link")
        mime_type = voice_info.get("mime_type", "audio/ogg")

        if not audio_link:
            logger.warning("Voice message received but no 'link' field found.")
            send_whapi_text(
                from_number,
                "استقبلت فويس لكن ما قدرش نحمّل الملف، جرّب تعاود ترسلو."
            )
            return jsonify({"ok": True})

        text = transcribe_from_url(audio_link, mime_type=mime_type)
        if not text:
            send_whapi_text(
                from_number,
                "صار مشكل في قراءة الرسالة الصوتية، جرّب تبعث فويس آخر أو ابعثلي نص."
            )
            return jsonify({"ok": True})

        reply = generate_reply(text)
        send_whapi_text(from_number, reply)
        return jsonify({"ok": True})

    # ---------- أنواع أخرى نتجاهلها حالياً ----------
    logger.info("Ignoring non-supported message type: %s", msg_type)
    return jsonify({"ok": True})


# ============= تشغيل محلي (اختياري) =============
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
