import os
import io
import base64
import requests
from flask import Flask, request, Response
from openai import OpenAI

# ==========================
# إعدادات عامة
# ==========================

app = Flask(__name__)

# مفتاح OpenAI من متغيرات البيئة في Render
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# إعدادات UltraMsg (استعمل بيانات الـ Instance الخاصة بك)
ULTRA_INSTANCE_ID = "instance154392"   # Instance ID
ULTRA_TOKEN = "qr5ee4h37ptjvz53"       # Token


# ==========================
# دالة مساعدة: رد ذكي من AI
# ==========================

def generate_ai_response(user_message: str) -> str:
    """
    تأخذ رسالة المستخدم نصاً وتعيد ردّاً ذكياً من نموذج GPT.
    """
    try:
        resp = client.responses.create(
            model="gpt-4o-mini",
            input=user_message,
        )
        # أسهل طريقة للحصول على النص
        return resp.output_text
    except Exception as e:
        # في حالة الخطأ نرجّع رسالة بسيطة
        return f"صار مشكل مؤقت في الرد، جرّب تعاود بعد لحظات. (تفاصيل تقنية: {e})"


# ==========================
# 1) صفحة بسيطة لاختبار السيرفر
# ==========================

@app.route("/")
def index():
    return "Bot is running"


# ==========================
# 2) مسار نصّي /voice (للتجارب من المتصفح)
#    مثال:
#    https://yourapp.onrender.com/voice?msg=سلام
# ==========================

@app.route("/voice")
def voice():
    msg = request.args.get("msg", "").strip()

    if not msg:
        return "Please provide ?msg= in the URL", 400

    reply = generate_ai_response(msg)

    return reply


# ==========================
# 3) مسار /speak لتحويل نص إلى صوت MP3
#    يرجّع ملف صوتي يمكن للمتصفح تشغيله
# ==========================

@app.route("/speak")
def speak():
    text = request.args.get("text", "").strip()

    if not text:
        return "Please provide ?text= in the URL", 400

    try:
        speech = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=text,
        )

        audio_bytes = speech.read()

        return Response(
            audio_bytes,
            mimetype="audio/mpeg",
            headers={
                "Content-Disposition": 'inline; filename="reply.mp3"'
            },
        )
    except Exception as e:
        return f"Error while generating speech: {e}", 500


# ==========================
# 4) صفحة ويب بسيطة لاختبار رفع ملف صوتي
# ==========================

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


# ==========================
# 5) استقبال ملف صوتي وتفريغه نصًّا
# ==========================

@app.route("/transcribe", methods=["POST"])
def transcribe():
    audio_file = request.files.get("audio")

    if not audio_file:
        return "No audio file uploaded with name 'audio'.", 400

    try:
        audio_file.stream.seek(0)
        filename = audio_file.filename or "audio-file.ogg"

        transcript = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=(filename, audio_file.stream.read(), "audio/ogg"),
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
        return f"Error while transcribing audio: {e}", 500


# ==========================
# 6) Webhook للواتساب من UltraMsg
#    يستقبل الرسائل ويردّ عليها
#    (حاليًا: نص فقط، وسنضيف الصوت لاحقاً)
# ==========================

@app.route("/whatsapp", methods=["POST"])
def whatsapp_webhook():
    try:
        event = request.json or {}

        # UltraMsg ترسل البيانات بهذا الشكل تقريباً:
        # {
        #   "event_type": "message_received",
        #   "instanceId": "xxxx",
        #   "data": { ... تفاصيل الرسالة ... }
        # }
        data = event.get("data", {})

        sender = data.get("from")        # رقم المرسل (chatId)
        msg_type = data.get("type")      # chat, audio, image ...
        body = data.get("body", "")      # نص الرسالة

        if not sender:
            return "no sender", 200

        # ===== نص فقط في هذه النسخة =====
        if msg_type == "chat":
            user_text = body.strip()
            if not user_text:
                return "empty text", 200

            reply_text = generate_ai_response(user_text)

            # نرسل الرد إلى نفس الرقم عبر UltraMsg
            api_url = f"https://api.ultramsg.com/{ULTRA_INSTANCE_ID}/messages/chat"

            payload = {
                "token": ULTRA_TOKEN,
                "to": sender,
                "body": reply_text,
                "priority": "high",
            }

            requests.post(api_url, data=payload)
            return "ok", 200

        # أنواع أخرى (صوت، صورة...) سنضيفها لاحقًا
        return "unsupported_type", 200

    except Exception as e:
        # مفيد لرؤية الأخطاء في Logs في Render
        return f"Webhook error: {e}", 500


# ==========================
# تشغيل التطبيق محلياً أو على Render
# ==========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
