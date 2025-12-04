from flask import Flask, request, Response
import os
from openai import OpenAI

app = Flask(__name__)

# عميل OpenAI باستعمال المفتاح من Render
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


# ===============================
#       الصفحة الرئيسية
# ===============================
@app.route("/")
def index():
    return "Bot is running"


# ===============================
#    ذكاء نصي (فهم الطلبات)
# ===============================
@app.route("/voice")
def voice():
    user_msg = request.args.get("msg", "").strip()

    if not user_msg:
        return "Please provide ?msg= in the URL", 400

    prompt = f"""
أنت وكيل ذكي لمطعم بيتزا في الجزائر.
الزبون قال: "{user_msg}"

مهمتك:
- إذا طلب المنيو، أعطه منيو مختصراً.
- إذا أراد طلباً، لخّص ما يريد: الأطباق، الكميات، الأحجام.
- اسأله بلطف عن العنوان إذا لم يذكره.
- استعمل الدارجة الجزائرية السهلة.
- الرد لا يتجاوز 3 أسطر.
"""

    try:
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
        )
        ai_reply = response.output[0].content[0].text
        return ai_reply

    except Exception as e:
        return f"Error while contacting AI: {e}", 500



# ===============================
#  تحويل النص إلى صوت (TTS)
# ===============================
@app.route("/speak")
def speak():
    text = request.args.get("msg", "").strip()

    if not text:
        return "Please provide ?msg= in the URL", 400

    try:
        # توليد الصوت من النص
        speech = client.audio.speech.create(
            model="gpt-4o-mini-tts",
            voice="alloy",
            input=text,
        )

        audio_bytes = speech.read()

        return Response(
            audio_bytes,
            mimetype="audio/mpeg",
            headers={"Content-Disposition": 'inline; filename="reply.mp3"'}
        )

    except Exception as e:
        return f"Error while generating speech: {e}", 500



# ===============================
#   صفحة اختبار رفع صوت
# ===============================
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


# ===============================
#    تفريغ صوت إلى نص (Whisper)
# ===============================
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
        return f"Error while transcribing audio: {e}", 500



# ===============================
#     تشغيل السيرفر
# ===============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
