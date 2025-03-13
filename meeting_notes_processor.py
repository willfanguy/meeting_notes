from dotenv import load_dotenv
import os

load_dotenv()  # Load variables from .env
import os
import openai
import ffmpeg
import json
import requests
from flask import Flask, request, render_template, redirect, url_for
from datetime import datetime

# Configuration
UPLOAD_FOLDER = "/home/will/meeting_notes/uploads"
OUTPUT_FOLDER = "/home/will/meeting_notes/summaries"

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Load API keys from environment variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# Initialize OpenAI Client
if not OPENAI_API_KEY:
    print("⚠️ ERROR: OpenAI API key is missing! Set it as an environment variable.")
    exit(1)

client = openai.OpenAI(api_key=OPENAI_API_KEY)

# Flask App Setup
app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


@app.route("/")
def index():
    return render_template("upload.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    """Handles file upload from the web interface"""
    if "file" not in request.files:
        return redirect(request.url)

    file = request.files["file"]
    meeting_name = request.form.get("meeting_name", "Unnamed Meeting")
    meeting_date = request.form.get("meeting_date", "")
    meeting_time = request.form.get("meeting_time", "")

    if file.filename == "":
        return redirect(request.url)

    # Create meeting metadata
    meeting_metadata = {
        "name": meeting_name,
        "date": meeting_date,
        "time": meeting_time,
        "original_filename": file.filename,
    }

    file_path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(file_path)
    process_file(file_path, meeting_metadata)

    return redirect(url_for("index"))


def send_discord_notification(message):
    """Sends a message to Discord via webhook"""
    if not DISCORD_WEBHOOK_URL:
        print(
            "⚠️ WARNING: Discord webhook URL is missing! Set it as an environment variable."
        )
        return

    payload = {"content": message}
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        print(f"✅ Sent Discord notification: {message}")
    except Exception as e:
        print(f"⚠️ Failed to send Discord notification: {e}")


def create_output_folder(meeting_metadata):
    """Creates a timestamped folder for output files"""
    meeting_date = meeting_metadata["date"].replace("-", "")
    meeting_name = meeting_metadata["name"].replace(" ", "_")
    folder_name = f"{meeting_date}_{meeting_name}"
    subfolder_path = os.path.join(OUTPUT_FOLDER, folder_name)
    os.makedirs(subfolder_path, exist_ok=True)

    # Save metadata
    metadata_file = os.path.join(subfolder_path, "metadata.json")
    with open(metadata_file, "w") as f:
        json.dump(meeting_metadata, f, indent=4)

    send_discord_notification(
        f"📂 Created folder `{folder_name}` for meeting: {meeting_metadata['name']}"
    )
    return subfolder_path


def transcribe_audio(audio_path, subfolder):
    """Transcribes audio using OpenAI's Whisper API"""
    with open(audio_path, "rb") as audio_file:
        response = client.audio.transcriptions.create(
            model="whisper-1", file=audio_file
        )

    transcript = response.text
    transcript_file = os.path.join(subfolder, "transcript.txt")

    with open(transcript_file, "w", encoding="utf-8") as file:
        file.write(transcript)

    send_discord_notification(f"📝 Transcript generated and saved.")
    return transcript


def summarize_text(text, subfolder):
    """Summarizes the transcript using GPT-4"""
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {
                "role": "system",
                "content": "Please provide a detailed, verbose, and thorough summary of the following transcript. Include all key action items, contextual insights, and any relevant details. Create a section at the end for action items, and ensure the summary is well-structured and easy to read.",
            },
            {"role": "user", "content": text},
        ],
    )

    summary = response.choices[0].message.content
    summary_file = os.path.join(subfolder, "summary.txt")

    with open(summary_file, "w", encoding="utf-8") as file:
        file.write(summary)

    send_discord_notification(f"✅ Summary generated and saved.")
    return summary


def process_file(file_path, meeting_metadata):
    """Handles processing of uploaded files"""
    subfolder = create_output_folder(meeting_metadata)

    if file_path.endswith((".mp4", ".mkv", ".avi", ".mov")):
        audio_file = os.path.join(subfolder, "audio.mp3")
        ffmpeg.input(file_path).output(
            audio_file, format="mp3", acodec="libmp3lame"
        ).run(overwrite_output=True)

        transcript = transcribe_audio(audio_file, subfolder)
        summarize_text(transcript, subfolder)

    elif file_path.endswith((".txt", ".md")):
        with open(file_path, "r", encoding="utf-8") as file:
            transcript = file.read()

        summarize_text(transcript, subfolder)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
