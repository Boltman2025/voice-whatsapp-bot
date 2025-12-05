import os
import io
import json
import logging

from flask import Flask, request, Response
import requests
from openai import OpenAI

# -----------------------------
# إعدادات أساسية
# -----------------------------
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# مفاتيح البيئة
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ULTRA_INSTANCE_ID = os.environ.get("ULTRA_INSTANCE_ID", "")
ULTRA_TOKEN = os.environ.get("ULTRA_TOKEN", "")
ULTRA_API_URL = os.environ.get(
    "ULTRA_API_URL",
    f"https://api.ultramsg.com/{ULTRA_INSTANCE_ID}"
)

if not OPENAI_API_KEY:
    logger.warning("OPENAI_API_KEY is missing!")
if not ULTRA_INSTANCE_ID or not ULTRA_TOKEN:
    logger.warning("UltraMsg config missing (ULTRA_INSTANCE_ID / ULTRA_TOKEN).")

client = OpenAI(api_key=OPENAI_API_KEY)

# -----------------------------
# صفحة بسيطة للتأكد أن السيرفر شغال
# -----------------------------
@app.route("/")
def index():
    return "Bot is running"

# -----------------------------
# ذكاء المحادثة (نص فقط)
# -----------------------------
def build_menu_text():
    return (
        "📋 *منيو اليوم (مثال تجريبي)*\n"
        "- بيتزا مارجريتا كبيرة: 900 دج\n"
        "- شاورما دجاج: 650 دج\n"
        "- بطاطا مقلية: 250 دج\n"
        "- كولا / مشروب غازي: 120 دج\n\n"
        "تقدر تقول مثلاً: حجز لي بيتزا مارجريتا كبيرة مع كولا للساعة 8."
    )

def ai_reply_for_text(user_text: str) -> str:
    """
    رد ذكي بسيط مبني على GPT-4o-mini.
    """
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "أنت بوت طلبات لمطعم في الجزائر، تتكلم بالدارجة البسيطة "
                        "وتساعد الزبون يطلب الأكل، وتطلب منه توضيح العنوان ورقم الهاتف لو لزم."
                    ),
                },
                {"role": "user", "content": user_text},
            ],
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        logger.exception("Error while contacting AI for text:")
        return "صرا مشكل تقني صغير مع الذكاء الاصطناعي، جرّب تعاود بعد لحظات 🙏."

# -----------------------------
# تحويل نص → صوت (للاختبارات لاحقاً)
# -----------------------------
@app.route("/speak", methods=["GET"])
def speak():
    msg = request.args.get("msg", "مرحبا، هذا صوت تجريبي من البوت.")
    try:
        speech = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=msg,
        )
        audio_bytes = speech.read()
        return Response(
            audio_bytes,
            mimetype="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=reply.mp3"
            },
        )
    except Exception as e:
        logger.exception("Error while generating speech:")
        return f"Error while generating speech: {e}", 500

# -----------------------------
# صفحة اختبار لرفع ملف صوتي يدويًا
# -----------------------------
@app.route("/test-upload", methods=["GET"])
def test_upload():
    return """
    <html>
      <body>
        <h3>Test audio transcription</h3>
        <form action="/transcribe" method="post" enctype="multipart/form-data">
          <p>Select an audio file (مثلاً رسالة واتساب صوتية .ogg أو .mp3):</p>
          <input type="file" name="audio" accept="audio/*" />
          <button type="submit">Transcribe</button>
        </form>
      </body>
    </html>
    """

@app.route("/transcribe", methods=["POST"])
def transcribe():
    audio_file = request.files.get("audio")
    if not audio_file:
        return "No audio file uploaded with name 'audio'.", 400

    try:
        audio_file.stream.seek(0)
        audio_file.name = audio_file.filename or "audio-file"

        transcript = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=audio_file,
        )
        text = transcript.text
        return f"""
        <html>
          <body>
            <h3>Transcription result:</h3>
            <p>{text}</p>
            <hr/>
            <a href="/test-upload">Try another file</a>
          </body>
        </html>
        """
    except Exception as e:
        logger.exception("Error while transcribing audio (manual upload):")
        return f"Error while transcribing audio: {e}", 500

# -----------------------------
# تحميل الصوت من UltraMsg
# -----------------------------
def download_ultramsg_voice(message_sid: str) -> bytes | None:
    """
    يحاول تحميل ملف الـ voice من UltraMsg.
    أحياناً الـ API ترجع JSON فيه رابط ملف، وأحياناً ترجع الملف مباشرة.
    نجرب الحالتين.
    """
    if not ULTRA_INSTANCE_ID or not ULTRA_TOKEN:
        logger.error("UltraMsg config missing (ULTRA_INSTANCE_ID / ULTRA_TOKEN).")
        return None

    # endpoint الذي تستعمله UltraMsg لتحميل الميديا من الـ SID
    media_endpoint = f"{ULTRA_API_URL.rstrip('/')}/messages/media/{message_sid}"

    try:
        resp = requests.get(
            media_endpoint,
            params={"token": ULTRA_TOKEN},
            timeout=25,
        )
        if not resp.ok:
            logger.error(
                "Failed to download media from UltraMsg: %s %s",
                resp.status_code,
                resp.text[:200],
            )
            return None

        content_type = resp.headers.get("Content-Type", "").lower()
        logger.info("UltraMsg media Content-Type: %s", content_type)

        # الحالة 1: أعطانا الملف مباشرة (audio/ogg أو audio/mpeg ...)
        if "audio" in content_type or "application/octet-stream" in content_type:
            return resp.content

        # الحالة 2: رجّع JSON فيه رابط الملف
        if "json" in content_type or "text/plain" in content_type:
            try:
                data = resp.json()
            except Exception:
                # لو JSON غير صحيح
                logger.error("Media response looks like JSON but can't parse: %s", resp.text[:200])
                return None

            media_url = None
            if isinstance(data, dict):
                # احتمال أن يكون مباشرة
                if "url" in data and isinstance(data["url"], str):
                    media_url = data["url"]
                # أو داخل data
                elif "data" in data and isinstance(data["data"], dict) and "url" in data["data"]:
                    media_url = data["data"]["url"]

            if not media_url:
                logger.error("No media URL found in UltraMsg JSON: %s", data)
                return None

            logger.info("Downloading real media from URL: %s", media_url)
            resp2 = requests.get(media_url, timeout=25)
            if not resp2.ok:
                logger.error(
                    "Failed to download real media file: %s %s",
                    resp2.status_code,
                    resp2.text[:200],
                )
                return None

            return resp2.content

        # نوع غير متوقع
        logger.error("Unexpected media Content-Type from UltraMsg: %s", content_type)
        return None

    except Exception as e:
        logger.exception("Exception while downloading media from UltraMsg:")
        return None

def transcribe_audio_bytes(audio_bytes: bytes) -> str | None:
    """
    يرسل البايتات إلى نموذج gpt-4o-mini-transcribe ويحصل على النص.
    """
    try:
        file_obj = io.BytesIO(audio_bytes)
        file_obj.name = "voice.ogg"
        transcript = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=file_obj,
        )
        return transcript.text
    except Exception as e:
        logger.exception("Error while transcribing audio bytes:")
        return None

# -----------------------------
# تحويل حدث واتساب (Webhook)
# -----------------------------
@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    """
    UltraMsg ستستدعي هذا المسار عندما يصل أي رسالة.
    """
    try:
        payload = request.get_json(force=True, silent=True) or {}
        logger.info("Webhook event: %s", json.dumps(payload, ensure_ascii=False))

        data = payload.get("data", {})
        msg_type = data.get("type")
        from_jid = data.get("from")
        body = data.get("body", "")
        pushname = data.get("pushname", "")
        sid = data.get("sid") or data.get("id")

        # حالات لا يوجد فيها مرسل أو sid
        if not from_jid:
            return "ok", 200

        # 1) رسالة نصية عادية
        if msg_type == "chat":
            user_text = body or ""
            if user_text.strip() == "":
                reply_text = "مرحبا، اكتب طلبك أو اسأل عن المنيو 👋."
            else:
                # دعم كلمة "منيو"
                if "منيو" in user_text or "menu" in user_text.lower():
                    reply_text = build_menu_text()
                else:
                    reply_text = ai_reply_for_text(user_text)

            send_whatsapp_text(from_jid, reply_text)
            return "ok", 200

        # 2) رسالة صوتية (ptt)
        if msg_type == "ptt":
            if not sid:
                logger.error("Voice message without SID, cannot download media.")
                send_whatsapp_text(
                    from_jid,
                    "استقبلت فويس لكن ما قدرش نحمّل الملف (مشكلة SID)، جرّب تعاود ترسلو أو بعتلي نص."
                )
                return "ok", 200

            audio_bytes = download_ultramsg_voice(sid)
            if not audio_bytes:
                send_whatsapp_text(
                    from_jid,
                    "استقبلت فويس لكن ما قدرش نحمّل الملف، جرّب تعاود ترسلو أو بعتلي نص 🙏."
                )
                return "ok", 200

            text = transcribe_audio_bytes(audio_bytes)
            if not text:
                send_whatsapp_text(
                    from_jid,
                    "حاولت نفهم الرسالة الصوتية لكن صرا مشكل في التفريغ، لو تقدر بعتهالي نص يكون أفضل 🙏."
                )
                return "ok", 200

            # الآن نرد بالذكاء الاصطناعي على النص المستخرج
            ai_answer = ai_reply_for_text(text)
            send_whatsapp_text(from_jid, f"📥 فهمت من الصوت:\n{text}\n\n💬 الرد:\n{ai_answer}")
            return "ok", 200

        # أنواع أخرى من الرسائل
        send_whatsapp_text(
            from_jid,
            "📩 استقبلت رسالتك، لكن حالياً ندعم النصوص والرسائل الصوتية فقط."
        )
        return "ok", 200

    except Exception as e:
        logger.exception("Error in /whatsapp webhook handler:")
        return "error", 500

# -----------------------------
# إرسال رسالة نصية عبر UltraMsg
# -----------------------------
def send_whatsapp_text(to_jid: str, text: str):
    """
    يستعمل UltraMsg API لإرسال رسالة نصية إلى رقم 'to_jid' (مثال: 213xxxx@c.us)
    """
    if not ULTRA_INSTANCE_ID or not ULTRA_TOKEN:
        logger.error("UltraMsg config missing (ULTRA_INSTANCE_ID / ULTRA_TOKEN).")
        return

    url = f"{ULTRA_API_URL.rstrip('/')}/messages/chat"
    data = {
        "token": ULTRA_TOKEN,
        "to": to_jid,
        "body": text,
    }
    try:
        resp = requests.post(url, data=data, timeout=20)
        logger.info("UltraMsg send response: %s %s", resp.status_code, resp.text[:300])
    except Exception:
        logger.exception("Error while sending WhatsApp message via UltraMsg:")

# -----------------------------
# تشغيل محلي فقط (ليس على Render)
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
