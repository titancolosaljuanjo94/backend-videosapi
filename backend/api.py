import os
import uuid
import time
import sqlite3
import json
import subprocess
import requests
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from google import genai
from google.genai import types
from elevenlabs.client import ElevenLabs

load_dotenv()

client_veo = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
client_eleven = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

DURACION   = 8
MODELO_VEO = "veo-3.1-generate-preview"
VOZ_ID     = "EXAVITQu4vr4xnSDxMaL"
DB_PATH    = "jobs.db"

app = FastAPI(title="Veo 3 + ElevenLabs API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "OPTIONS", "PATCH"],  # Excluye DELETE
    allow_headers=["*"]
)
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")


# ─── Base de datos ────────────────────────────────────────────────

def _db():
    return sqlite3.connect(DB_PATH)

def _init_db():
    with _db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                job_id     TEXT PRIMARY KEY,
                status     TEXT NOT NULL,
                prompt     TEXT,
                guion      TEXT,
                clips      TEXT,
                error      TEXT,
                created_at TEXT NOT NULL
            )
        """)

_init_db()


def _job_create(job_id: str, prompt: str, guion: Optional[str]):
    with _db() as con:
        con.execute(
            "INSERT INTO jobs (job_id, status, prompt, guion, clips, error, created_at) VALUES (?,?,?,?,?,?,?)",
            (job_id, "pending", prompt, guion, "[]", None, time.strftime("%Y-%m-%d %H:%M:%S"))
        )

def _job_update(job_id: str, status: str, clips: list = None, error: str = None):
    with _db() as con:
        con.execute(
            "UPDATE jobs SET status=?, clips=?, error=? WHERE job_id=?",
            (status, json.dumps(clips or []), error, job_id)
        )

def _job_get(job_id: str) -> Optional[dict]:
    with _db() as con:
        row = con.execute(
            "SELECT job_id, status, prompt, guion, clips, error, created_at FROM jobs WHERE job_id=?",
            (job_id,)
        ).fetchone()
    if not row:
        return None
    return {
        "job_id": row[0], "status": row[1], "prompt": row[2],
        "guion": row[3], "clips": json.loads(row[4]),
        "error": row[5], "created_at": row[6],
    }

def _jobs_list() -> list:
    with _db() as con:
        rows = con.execute(
            "SELECT job_id, status, prompt, created_at FROM jobs ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    return [{"job_id": r[0], "status": r[1], "prompt": r[2], "created_at": r[3]} for r in rows]


# ─── Lógica de generación ─────────────────────────────────────────

def _generar_video_veo(prompt: str, imagen: Optional[types.Image], numero: int) -> Optional[Path]:
    try:
        config = types.GenerateVideosConfig(
            duration_seconds=DURACION,
            aspect_ratio="16:9",
            number_of_videos=1,
        )
        if imagen:
            op = client_veo.models.generate_videos(
                model=MODELO_VEO, prompt=prompt, image=imagen, config=config)
        else:
            op = client_veo.models.generate_videos(
                model=MODELO_VEO, prompt=prompt, config=config)

        intentos = 0
        while not op.done and intentos < 30:
            time.sleep(10)
            op = client_veo.operations.get(op)
            intentos += 1

        if not op.done or not op.response or not op.response.generated_videos:
            return None

        video_uri = op.response.generated_videos[0].video.uri
        ruta_video = OUTPUT_DIR / f"video_{numero:02d}_{int(time.time())}.mp4"
        resp = requests.get(
            video_uri,
            headers={"x-goog-api-key": os.getenv("GEMINI_API_KEY")},
            stream=True,
        )
        with open(ruta_video, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return ruta_video

    except Exception as e:
        print(f"Error Veo clip {numero}: {e}")
        return None


def _generar_voz(guion: str, numero: int) -> Optional[Path]:
    try:
        audio = client_eleven.text_to_speech.convert(
            voice_id=VOZ_ID,
            text=guion,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
        ruta_audio = OUTPUT_DIR / f"voz_{numero:02d}_{int(time.time())}.mp3"
        with open(ruta_audio, "wb") as f:
            for chunk in audio:
                f.write(chunk)
        return ruta_audio
    except Exception as e:
        print(f"Error ElevenLabs clip {numero}: {e}")
        return None


def _combinar(ruta_video: Path, ruta_audio: Path, numero: int) -> Optional[Path]:
    ruta_final = OUTPUT_DIR / f"clip_final_{numero:02d}_{int(time.time())}.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(ruta_video),
        "-i", str(ruta_audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-shortest",
        str(ruta_final),
    ]
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    return ruta_final if resultado.returncode == 0 else None


def _run_job(job_id: str, prompt: str, guion: Optional[str], imagen_bytes: Optional[bytes], mime: str):
    _job_update(job_id, "processing")
    clips = []

    imagen = types.Image(image_bytes=imagen_bytes, mime_type=mime) if imagen_bytes else None

    variaciones = [
        prompt,
        prompt + ", alternative angle, slightly different framing",
        prompt + ", different camera movement, varied composition",
    ]

    for i, p in enumerate(variaciones[:1], start=1):  # 1 variante por defecto
        ruta_video = _generar_video_veo(p, imagen, i)
        if not ruta_video:
            continue

        if guion:
            ruta_audio = _generar_voz(guion, i)
            if ruta_audio:
                ruta_final = _combinar(ruta_video, ruta_audio, i)
                clips.append(str(ruta_final or ruta_video))
            else:
                clips.append(str(ruta_video))
        else:
            clips.append(str(ruta_video))

    if clips:
        _job_update(job_id, "done", [f"/outputs/{Path(c).name}" for c in clips])
    else:
        _job_update(job_id, "error", error="No se generó ningún clip.")


# ─── Endpoints ────────────────────────────────────────────────────

@app.post("/generate")
async def generate(
    background_tasks: BackgroundTasks,
    prompt: str = Form(...),
    guion: Optional[str] = Form(None),
    imagen: Optional[UploadFile] = File(None),
):
    job_id = str(uuid.uuid4())
    _job_create(job_id, prompt, guion)

    imagen_bytes = None
    mime = "image/jpeg"
    if imagen:
        mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".webp": "image/webp"}
        mime = mime_map.get(Path(imagen.filename).suffix.lower(), "image/jpeg")
        imagen_bytes = await imagen.read()

    background_tasks.add_task(_run_job, job_id, prompt, guion, imagen_bytes, mime)
    return {"job_id": job_id, "status": "pending"}


@app.get("/job/{job_id}")
def get_job(job_id: str):
    job = _job_get(job_id)
    if not job:
        return JSONResponse(status_code=404, content={"error": "Job no encontrado"})
    return job


@app.get("/jobs")
def list_jobs():
    return _jobs_list()


@app.get("/")
def root():
    return {"message": "Veo 3 + ElevenLabs API — POST /generate | GET /job/{job_id} | GET /jobs"}
