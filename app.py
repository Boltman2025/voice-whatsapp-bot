from flask import Flask, request, jsonify, Response
from openai import OpenAI
import os

app = Flask(__name__)

# --- OpenAI client ---
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


# -----------------------------------------------------
# 🟦 صفحة الفحص الأساسية (Landing)
# -----------------------------------------------------
@app.route("/")
def home():
    return "Bot is running"


# -----------------------------------------------------
# 🟩 1) مسار الرد النصي /voice
# -----------------------------------------------------
@app.route("/voice")
def voice():
    msg = request.args.get("msg", "")

    if not msg:
        return "يرجى إرسال msg ؟msg= ", 400

    try:
        response = client.responses.create(
            model="gpt-4o-mini",
            input=f"""
            أنت مساعد مطعم. تعامل مع هذه الرسالة كما لو أنها طلب من زبون:
            {msg}
            """,
        )

        reply = response.output_text
        return reply

    except Exception as e:
        return f"Error while contacting AI: {e}", 500


# -----------------------------------------------------
# 🟧 2) مسار إنتاج الصوت من نص /speak
# -----------------------------------------------------
@app.route("/speak")
def speak():
    text = request.args.get("text", "")

    if not text:
        return "يرجى إضافة النص: /speak?text=hello", 400

    try:
        # إنشاء ملف صوتي
        result = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=text
        )

        audio_bytes = result.read()

        return Response(
            audio_bytes,
            mimetype="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=reply.mp3"
            }
        )

    except Exception as e:
        return f"Error while generating speech: {e}", 500


# -----------------------------------------------------
# 🟨 3) صفحة رفع ملف صوتي للاختبار /test-upload
# -----------------------------------------------------
@app.route("/test-upload")
def test_upload():
    return """
    <html>
      <body>
        <h3>Test audio transcription</h3>
        <form action="/transcribe" method="post" enctype="multipart/form-data">
          <p>Select an audio file (مثال: رسالة واتساب ogg/mp3):</p>
          <input type="file" name="audio" accept="audio/*" />
          <button type="submit">Transcribe</button>
        </form>
      </body>
    </html>
    """


# -----------------------------------------------------
# 🟨 4) مسار تفريغ الصوت /transcribe
# -----------------------------------------------------
@app.route("/transcribe", methods=["POST"])
def transcribe():
    audio_file = request.files.get("audio")

    if not audio_file:
        return "No audio file uploaded with name 'audio'.", 400

    try:
        # قراءة الملف
        audio_bytes = audio_file.read()

        # تجهيز الملف بالشكل المطلوب من مكتبة OpenAI
        file_tuple = (
            audio_file.filename,
            audio_bytes,
            audio_file.mimetype or "audio/mpeg"
        )

        # طلب التفريغ
        transcript = client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=file_tuple
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


# -----------------------------------------------------
# 🟥 تشغيل السيرفر
# -----------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
