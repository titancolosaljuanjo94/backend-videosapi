import os
import time
import subprocess
import requests
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from elevenlabs.client import ElevenLabs

# ─── Configuración ────────────────────────────────────────────────
load_dotenv()

client_veo = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
client_eleven = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

NUM_CLIPS  = 1
DURACION   = 8
MODELO_VEO = "veo-3.1-generate-preview"
VOZ_ID     = "EXAVITQu4vr4xnSDxMaL"  # "Sarah" — voz en inglés/español


# ─── Funciones ────────────────────────────────────────────────────

def pedir_imagen():
    ruta = input("\n📁 Ruta de tu imagen (Enter para omitir): ").strip()
    if not ruta:
        print("   ⚠️  Sin imagen — solo prompt de texto.")
        return None
    ruta_path = Path(ruta)
    if not ruta_path.exists():
        print(f"   ✗ No se encontró: {ruta}")
        return None
    mime_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                  ".png": "image/png",  ".webp": "image/webp"}
    mime = mime_types.get(ruta_path.suffix.lower(), "image/jpeg")
    imagen_bytes = ruta_path.read_bytes()
    print(f"   ✓ Imagen cargada: {ruta_path.name} ({len(imagen_bytes)//1024} KB)")
    return types.Image(image_bytes=imagen_bytes, mime_type=mime)


def pedir_prompt():
    print("\n✏️  Prompt para el video (movimiento, estilo, iluminación):")
    print("   Ejemplo: 'Slow cinematic zoom, warm studio light, dark background'")
    prompt = input("\n   Prompt: ").strip()
    if not prompt:
        prompt = "Cinematic slow motion, professional studio lighting"
        print(f"   ⚠️  Usando prompt por defecto: '{prompt}'")
    return prompt


def pedir_guion():
    print("\n🎙️  Guión que dirá el personaje (Enter para omitir voz):")
    print("   Ejemplo: 'Este producto cambió mi vida, no puedo vivir sin él'")
    guion = input("\n   Guión: ").strip()
    if not guion:
        print("   ⚠️  Sin guión — el clip no tendrá voz.")
        return None
    return guion


def generar_video_veo(prompt, imagen, numero):
    """Genera un clip con Veo 3 y lo descarga."""
    print(f"\n   🎬 Generando video {numero}/{NUM_CLIPS}...")
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
            print(f"      ⏳ Esperando... ({intentos * 10}s)")

        if not op.done:
            print(f"   ✗ Tiempo agotado clip {numero}")
            return None

        if op.response and op.response.generated_videos:
            video_uri = op.response.generated_videos[0].video.uri
        else:
            print(f"   ✗ Sin video en respuesta")
            return None

        ruta_video = OUTPUT_DIR / f"video_{numero:02d}_{int(time.time())}.mp4"
        print(f"   ⬇️  Descargando video {numero}...")
        resp = requests.get(
            video_uri,
            headers={"x-goog-api-key": os.getenv("GEMINI_API_KEY")},
            stream=True
        )
        with open(ruta_video, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"   ✓ Video guardado: {ruta_video.name}")
        return ruta_video

    except Exception as e:
        print(f"   ✗ Error Veo clip {numero}: {e}")
        return None


def generar_voz_elevenlabs(guion, numero):
    """Genera el audio del guión con ElevenLabs."""
    print(f"   🎙️  Generando voz para clip {numero}...")
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
        print(f"   ✓ Voz guardada: {ruta_audio.name}")
        return ruta_audio

    except Exception as e:
        print(f"   ✗ Error ElevenLabs clip {numero}: {e}")
        return None


def combinar_video_voz(ruta_video, ruta_audio, numero):
    """Une video y voz con FFmpeg."""
    print(f"   🔗 Combinando video + voz clip {numero}...")
    ruta_final = OUTPUT_DIR / f"clip_final_{numero:02d}_{int(time.time())}.mp4"
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(ruta_video),
        "-i", str(ruta_audio),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-shortest",
        str(ruta_final)
    ]
    
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    
    if resultado.returncode == 0:
        print(f"   ✓ Clip final: {ruta_final.name}")
        return ruta_final
    else:
        print(f"   ✗ Error FFmpeg: {resultado.stderr[-200:]}")
        return None


def generar_variantes(prompt, imagen, guion):
    variaciones = [
        prompt,
        prompt + ", alternative angle, slightly different framing",
        prompt + ", different camera movement, varied composition",
    ]
    clips_finales = []

    for i, p in enumerate(variaciones[:NUM_CLIPS], start=1):
        print(f"\n{'─'*45}")
        print(f"   VARIANTE {i} de {NUM_CLIPS}")
        print(f"{'─'*45}")

        # Paso 1: generar video
        ruta_video = generar_video_veo(p, imagen, i)
        if not ruta_video:
            continue

        # Paso 2: generar voz (si hay guión)
        if guion:
            ruta_audio = generar_voz_elevenlabs(guion, i)
            if ruta_audio:
                # Paso 3: combinar
                ruta_final = combinar_video_voz(ruta_video, ruta_audio, i)
                if ruta_final:
                    clips_finales.append(str(ruta_final))
            else:
                # Si falla la voz, guardar el video solo
                clips_finales.append(str(ruta_video))
        else:
            clips_finales.append(str(ruta_video))

        if i < NUM_CLIPS:
            print(f"\n   ⏸  Pausa 5s...")
            time.sleep(5)

    return clips_finales


def mostrar_resumen(clips, prompt, guion):
    print("\n" + "═" * 45)
    print("✅  GENERACIÓN COMPLETADA")
    print("═" * 45)
    print(f"\n   Prompt : {prompt[:55]}")
    print(f"   Guión  : {guion[:55] if guion else 'sin voz'}")
    print(f"   Clips  : {len(clips)}/{NUM_CLIPS}")
    print(f"\n   📂 Archivos en: ./outputs/")
    for i, clip in enumerate(clips, start=1):
        nombre = Path(clip).name
        tamaño = Path(clip).stat().st_size // 1024
        print(f"\n   [{i}] {nombre} ({tamaño} KB)")
    print("\n   👉 Revisa los clips y elige tu favorito.")
    print("═" * 45)


# ─── Main ─────────────────────────────────────────────────────────

def main():
    print("═" * 45)
    print("🎥  VEO 3 + ELEVENLABS — GENERADOR DE CLIPS")
    print("═" * 45)
    print(f"   Modelo : {MODELO_VEO}")
    print(f"   Clips  : {NUM_CLIPS} variantes | {DURACION}s c/u")

    imagen = pedir_imagen()
    prompt = pedir_prompt()
    guion  = pedir_guion()

    print(f"\n{'─'*45}")
    print("   RESUMEN:")
    print(f"   • Imagen : {'✓ cargada' if imagen else '✗ sin imagen'}")
    print(f"   • Prompt : {prompt[:50]}")
    print(f"   • Guión  : {guion[:50] if guion else '✗ sin voz'}")
    costo_veo = NUM_CLIPS * DURACION * 0.15
    costo_eleven = (len(guion) / 1000 * 0.18 * NUM_CLIPS) if guion else 0
    print(f"   • Costo aprox: ${costo_veo + costo_eleven:.2f} USD")
    print(f"{'─'*45}")

    confirmar = input("\n   ¿Continuar? (s/n): ").strip().lower()
    if confirmar != "s":
        print("   Cancelado.")
        return

    clips = generar_variantes(prompt, imagen, guion)

    if clips:
        mostrar_resumen(clips, prompt, guion)
    else:
        print("\n   ✗ No se generó ningún clip.")


if __name__ == "__main__":
    main()
