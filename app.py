import os
import logging
from flask import Flask, request, jsonify
import requests
from openai import OpenAI

# ----- إعدادات عامة -----
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
WHAPI_TOKEN = os.getenv("WHAPI_TOKEN")
WHAPI_BASE_URL = os.getenv("WHAPI_BASE_URL", "https://gate.whapi.cloud")

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is not set!")
if not WHAPI_TOKEN:
    logger.warning("WHAPI_TOKEN is not set!")

client = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)


# ---------- مساعد لإرسال رسالة نصية عبر Whapi ----------
def send_whapi_text(to_number: str, text: str):
    """
    يرسل رسالة نصية عبر Whapi إلى رقم واتساب معيّن.
    to_number بصيغة 213xxxxxxxxx
    """
    if not WHAPI_TOKEN:
        logger.error("Cannot send via Whapi: WHAPI_TOKEN is missing.")
        return

    url = f"{WHAPI_BASE_URL}/messages/text"
    headers = {
        "Authorization": f"Bearer {WHAPI_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "to": to_number,
        "body": text,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        logger.info("Whapi send response: %s %s", resp.status_code, resp.text)
    except Exception as e:
        logger.exception("Error sending message via Whapi: %s", e)


# ---------- مساعد لتوليد رد من الذكاء الاصطناعي ----------
def generate_ai_reply(user_message: str) -> str:
    """
    يولّد رد ذكي بالعربية على رسالة الزبون.
    """
    try:
        completion = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "أنت مساعد صوتي لمطعم في الجزائر. "
                        "تتكلم بالدارجة الجزائرية البسيطة، "
                        "وتساعد الزبون في: الترحيب، عرض المنيو، "
                        "أخذ الطلب (نوع الطبق، الكمية، المشروب)، "
                        "ثم تطلب منه تأكيد العنوان ورقم الهاتف إذا لزم."
                    ),
                },
                {"role": "user", "content": user_message},
            ],
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        logger.exception("Error calling OpenAI: %s", e)
        return "صار مشكل تقني صغير في الخدمة، جرّب تعاود بعد لحظات من فضلك."


# ---------- مسار بسيط لاختبار أن السيرفر شغال ----------
@app.route("/", methods=["GET"])
def index():
    return "Bot is running", 200


# ---------- Webhook من Whapi ----------
@app.route("/whapi", methods=["POST"])
def whapi_webhook():
    """
    هذا هو Webhook الذي يستقبِل كل رسائل واتساب من Whapi.
    سنركّز الآن على الرسائل النصية، والفويس نضيفه بعد أن نرى شكل الـ JSON بالضبط.
    """
    data = request.get_json(force=True, silent=True) or {}
    logger.info("Incoming Whapi webhook: %s", data)

    # نحاول استخراج أهم الحقول بطريقة مرنة
    try:
        # في Whapi عادة يوجد حقل event و payload
        event = data.get("event") or data.get("type") or ""
        payload = data.get("payload") or data

        # رقم المرسل
        from_number = (
            payload.get("from")  # مثال: 213776xxxxx
            or payload.get("chatId")  # في بعض الصيغ
        )

        message_type = payload.get("type") or payload.get("messageType")
        text_body = ""

        # إذا كانت رسالة نصية
        if message_type in ("text", "chat", None):
            text_body = payload.get("text") or payload.get("body") or ""
        # لو كانت فويس أو أوديو الآن نرد برسالة نصية فقط
        elif message_type in ("audio", "voice", "ptt"):
            # نرد عليه برسالة تشرح أن النسخة الحالية تفهم النص فقط
            if from_number:
                send_whapi_text(
                    from_number,
                    "استقبلت فويس 👌 النسخة الحالية من البوت تفهم غير الرسائل المكتوبة. "
                    "ابعتلي واش حاب تطلب في رسالة نصية، ونكمّل معك.",
                )
            return jsonify({"status": "ok"}), 200

        # إذا لم نجد رقم المرسل، لا نفعل شيئاً
        if not from_number:
            logger.warning("No from_number in webhook payload.")
            return jsonify({"status": "no_sender"}), 200

        # إذا لم يكن هناك نص، نخرج بهدوء
        if not text_body:
            logger.info("No text body in message; ignoring.")
            return jsonify({"status": "no_text"}), 200

        # ننادي الذكاء الاصطناعي لتوليد الرد
        reply = generate_ai_reply(text_body)

        # نرسل الرد عبر Whapi
        send_whapi_text(from_number, reply)

        return jsonify({"status": "sent"}), 200

    except Exception as e:
        logger.exception("Error handling Whapi webhook: %s", e)
        return jsonify({"status": "error", "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
