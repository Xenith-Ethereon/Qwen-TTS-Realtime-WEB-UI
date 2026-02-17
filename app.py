import os
import uuid
import base64
import pathlib
import requests as http_requests
from io import BytesIO

from flask import Flask, request, jsonify, send_file, render_template
from flask_cors import CORS
from dotenv import load_dotenv

import dashscope
from dashscope.audio.qwen_tts_realtime import (
    QwenTtsRealtime,
    QwenTtsRealtimeCallback,
    AudioFormat,
)
import threading
import struct
import time

load_dotenv()

app = Flask(__name__)
CORS(app)

API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
PORT = int(os.getenv("PORT", 5000))

OUTPUT_DIR = pathlib.Path(__file__).parent / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

DASHSCOPE_CUSTOMIZATION_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
)
DASHSCOPE_WS_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"

MIME_MAP = {
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
}

NON_STREAMING_MODELS = {
    "qwen3-tts-vc-2026-01-22",
}

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/voice/create", methods=["POST"])
def voice_create():
    if "audio" not in request.files:
        return jsonify({"success": False, "error": "未上传音频文件"}), 400

    audio_file = request.files["audio"]
    target_model = request.form.get("target_model", "qwen3-tts-vc-realtime-2026-01-15")
    preferred_name = request.form.get("preferred_name", "custom_voice")

    ext = pathlib.Path(audio_file.filename).suffix.lower()
    mime_type = MIME_MAP.get(ext, "audio/wav")

    audio_bytes = audio_file.read()
    b64 = base64.b64encode(audio_bytes).decode()
    data_uri = f"data:{mime_type};base64,{b64}"

    payload = {
        "model": "qwen-voice-enrollment",
        "input": {
            "action": "create",
            "target_model": target_model,
            "preferred_name": preferred_name,
            "audio": {"data": data_uri},
        },
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = http_requests.post(
            DASHSCOPE_CUSTOMIZATION_URL, json=payload, headers=headers, timeout=60
        )
        if resp.status_code == 200:
            data = resp.json()
            voice = data["output"]["voice"]
            return jsonify(
                {
                    "success": True,
                    "voice": voice,
                    "target_model": data["output"].get("target_model", target_model),
                }
            )
        else:
            return jsonify(
                {"success": False, "error": f"API 错误 {resp.status_code}: {resp.text}"}
            ), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/voice/list", methods=["GET"])
def voice_list():
    page_index = request.args.get("page_index", 0, type=int)
    page_size = request.args.get("page_size", 20, type=int)

    payload = {
        "model": "qwen-voice-enrollment",
        "input": {
            "action": "list",
            "page_size": page_size,
            "page_index": page_index,
        },
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = http_requests.post(
            DASHSCOPE_CUSTOMIZATION_URL, json=payload, headers=headers, timeout=30
        )
        if resp.status_code == 200:
            data = resp.json()
            voice_list = data.get("output", {}).get("voice_list", [])
            return jsonify({"success": True, "voices": voice_list})
        else:
            return jsonify(
                {"success": False, "error": f"API 错误 {resp.status_code}: {resp.text}"}
            ), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/voice/delete", methods=["POST"])
def voice_delete():
    data = request.get_json()
    voice = data.get("voice", "")

    if not voice:
        return jsonify({"success": False, "error": "未指定音色名称"}), 400

    payload = {
        "model": "qwen-voice-enrollment",
        "input": {"action": "delete", "voice": voice},
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        resp = http_requests.post(
            DASHSCOPE_CUSTOMIZATION_URL, json=payload, headers=headers, timeout=30
        )
        if resp.status_code == 200:
            return jsonify({"success": True, "message": "音色删除成功"})
        else:
            return jsonify(
                {"success": False, "error": f"API 错误 {resp.status_code}: {resp.text}"}
            ), resp.status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


class SynthCallback(QwenTtsRealtimeCallback):

    def __init__(self):
        self.audio_chunks: list[bytes] = []
        self.complete_event = threading.Event()
        self.error: str | None = None

    def on_open(self):
        pass

    def on_close(self, code, msg):
        self.complete_event.set()

    def on_event(self, response: dict):
        try:
            event_type = response.get("type", "")
            if event_type == "response.audio.delta":
                self.audio_chunks.append(base64.b64decode(response["delta"]))
            elif event_type == "session.finished":
                self.complete_event.set()
            elif event_type == "error":
                self.error = str(response.get("error", "未知错误"))
                self.complete_event.set()
        except Exception as e:
            self.error = str(e)
            self.complete_event.set()

    def wait(self, timeout=120):
        self.complete_event.wait(timeout=timeout)

    def get_pcm_data(self) -> bytes:
        return b"".join(self.audio_chunks)


def pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, bits: int = 16) -> bytes:
    data_size = len(pcm_data)
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8

    buf = BytesIO()
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))
    buf.write(struct.pack("<H", 1))
    buf.write(struct.pack("<H", channels))
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", byte_rate))
    buf.write(struct.pack("<H", block_align))
    buf.write(struct.pack("<H", bits))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm_data)
    return buf.getvalue()


@app.route("/api/tts/synthesize", methods=["POST"])
def tts_synthesize():
    data = request.get_json()
    text = data.get("text", "").strip()
    voice = data.get("voice", "Cherry")
    model = data.get("model", "qwen3-tts-vc-realtime-2026-01-15")
    language_type = data.get("language_type", "Auto")

    if not text:
        return jsonify({"success": False, "error": "合成文本不能为空"}), 400

    dashscope.api_key = API_KEY

    if model in NON_STREAMING_MODELS:
        return _synthesize_non_streaming(text, voice, model)

    return _synthesize_realtime(text, voice, model, language_type)


def _synthesize_non_streaming(text: str, voice: str, model: str):
    try:
        dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"
        response = dashscope.MultiModalConversation.call(
            model=model,
            api_key=API_KEY,
            text=text,
            voice=voice,
            stream=False,
        )

        if hasattr(response, "output") and hasattr(response.output, "audio"):
            audio_url = response.output.audio.url
        elif isinstance(response, dict):
            audio_url = response.get("output", {}).get("audio", {}).get("url", "")
        else:
            return jsonify({"success": False, "error": f"无法解析响应: {response}"}), 500

        if not audio_url:
            return jsonify({"success": False, "error": "API 未返回音频 URL"}), 500

        audio_resp = http_requests.get(audio_url, timeout=60)
        if audio_resp.status_code != 200:
            return jsonify({"success": False, "error": "下载音频失败"}), 500

        audio_data = audio_resp.content

        filename = f"tts_{uuid.uuid4().hex[:8]}.wav"
        filepath = OUTPUT_DIR / filename
        filepath.write_bytes(audio_data)

        return send_file(
            BytesIO(audio_data),
            mimetype="audio/wav",
            as_attachment=False,
            download_name=filename,
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _synthesize_realtime(text: str, voice: str, model: str, language_type: str):
    callback = SynthCallback()

    try:
        tts = QwenTtsRealtime(
            model=model,
            callback=callback,
            url=DASHSCOPE_WS_URL,
        )
        tts.connect()
        tts.update_session(
            voice=voice,
            response_format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            mode="server_commit",
            language_type=language_type,
        )

        chunk_size = 80
        for i in range(0, len(text), chunk_size):
            tts.append_text(text[i : i + chunk_size])
            time.sleep(0.05)

        tts.finish()
        callback.wait(timeout=120)

        if callback.error:
            return jsonify({"success": False, "error": callback.error}), 500

        pcm_data = callback.get_pcm_data()
        if not pcm_data:
            return jsonify({"success": False, "error": "未生成任何音频数据"}), 500

        wav_data = pcm_to_wav(pcm_data)

        filename = f"tts_{uuid.uuid4().hex[:8]}.wav"
        filepath = OUTPUT_DIR / filename
        filepath.write_bytes(wav_data)

        return send_file(
            BytesIO(wav_data),
            mimetype="audio/wav",
            as_attachment=False,
            download_name=filename,
        )

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    if not API_KEY or API_KEY == "sk-your-api-key-here":
        print("请先在 .env 文件中配置 DASHSCOPE_API_KEY")
        print("获取地址: https://help.aliyun.com/zh/model-studio/get-api-key")
    app.run(host="0.0.0.0", port=PORT, debug=True)
