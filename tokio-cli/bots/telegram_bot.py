"""
Telegram Bot - Full conversational interface to CLI
Like OpenClaw but via Telegram
"""
import os
import asyncio
import logging
import base64
from typing import Optional, Tuple
from datetime import datetime
from telegram import Update, Bot
from telegram.error import TimedOut as TelegramTimedOut, NetworkError as TelegramNetworkError
from telegram.request import HTTPXRequest
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# Avoid leaking bot token in verbose HTTP logs
logging.getLogger("httpx").setLevel(logging.WARNING)

# CLI Service URL
CLI_SERVICE_URL = os.getenv("CLI_SERVICE_URL", "http://tokio-cli:8100")

# Vision (Telegram attachments -> text)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
TOKIO_IMAGE_MAX_BYTES = int(os.getenv("TOKIO_IMAGE_MAX_BYTES", "2000000"))  # 2MB default

# Access control
TELEGRAM_OWNER_ID = os.getenv("TELEGRAM_OWNER_ID", "").strip()
TELEGRAM_ALLOWED_IDS = os.getenv("TELEGRAM_ALLOWED_IDS", "").strip()

# User sessions (user_id -> session_id mapping)
user_sessions = {}
allowed_user_ids = set()

async def _safe_send_chat_action(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    action: str,
):
    # Chat actions are "nice to have"; never let them break the update flow.
    for attempt in range(2):
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=action)
            return
        except (TelegramTimedOut, TelegramNetworkError) as e:
            logger.warning(f"send_chat_action failed (attempt={attempt+1}): {e}")
            await asyncio.sleep(0.7 * (attempt + 1))
        except Exception as e:
            logger.warning(f"send_chat_action unexpected error: {e}")
            return


async def _safe_reply_text(update: Update, text: str):
    # Telegram network timeouts happen sporadically (DNS/IPv6 jitter, mobile networks).
    # Retry a couple times so the bot feels responsive.
    if not update.message:
        return
    for attempt in range(3):
        try:
            await update.message.reply_text(text)
            return
        except (TelegramTimedOut, TelegramNetworkError) as e:
            logger.warning(f"reply_text failed (attempt={attempt+1}): {e}")
            await asyncio.sleep(1.0 * (attempt + 1))
        except Exception as e:
            logger.error(f"reply_text unexpected error: {e}")
            return


def _parse_allowed_ids(raw: str):
    result = set()
    for token in (raw or "").split(","):
        token = token.strip()
        if token.isdigit():
            result.add(int(token))
    return result


def _init_access_control():
    global allowed_user_ids
    allowed_user_ids = _parse_allowed_ids(TELEGRAM_ALLOWED_IDS)
    if TELEGRAM_OWNER_ID.isdigit():
        allowed_user_ids.add(int(TELEGRAM_OWNER_ID))


def _is_owner(user_id: int) -> bool:
    return TELEGRAM_OWNER_ID.isdigit() and user_id == int(TELEGRAM_OWNER_ID)


def _is_authorized(user_id: int) -> bool:
    # If no ACL configured, keep backward compatibility and allow all.
    if not TELEGRAM_OWNER_ID and not TELEGRAM_ALLOWED_IDS:
        return True
    return user_id in allowed_user_ids


async def _guard_access(update: Update) -> bool:
    user_id = update.effective_user.id if update.effective_user else 0
    if _is_authorized(user_id):
        return True
    await _safe_reply_text(update, "⛔ No autorizado para usar este bot.")
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command - welcome message"""
    if not await _guard_access(update):
        return
    user = update.effective_user
    await _safe_reply_text(
        update,
        f"🤖 Hola {user.first_name}!\n\n"
        "Soy el Tokio CLI Agent con inteligencia OpenClaw.\n\n"
        "Puedo ayudarte con:\n"
        "• Gestión de infraestructura\n"
        "• Control de tenants y WAF\n"
        "• Análisis de logs y seguridad\n"
        "• Control de dispositivos IoT\n"
        "• Lectura de imágenes (foto/adjunto)\n"
        "• Y mucho más...\n\n"
        "Simplemente escribe tu comando o pregunta."
    )

async def _run_cli_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    command: str,
):
    # Show typing indicator
    await _safe_send_chat_action(context, chat_id=update.effective_chat.id, action="typing")

    # Get or create session for user
    if user_id not in user_sessions:
        user_sessions[user_id] = f"telegram-{user_id}"
    session_id = user_sessions[user_id]

    timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
    limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        try:
            response = await client.post(
                f"{CLI_SERVICE_URL}/api/cli/jobs",
                json={
                    "command": command,
                    "session_id": session_id,
                    "max_iterations": 10,
                    "timeout": 120,
                },
            )
        except Exception as e:
            await _safe_reply_text(update, f"❌ Error conectando al CLI: {str(e)[:200]}")
            return

        if response.status_code != 200:
            await _safe_reply_text(update, f"❌ Error al procesar: {response.text}")
            return

        job_data = response.json()
        job_id = job_data["job_id"]

        # Poll for result
        max_wait = 120  # seconds
        poll_interval = 2
        elapsed = 0

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            if elapsed % 10 == 0:
                await _safe_send_chat_action(context, chat_id=update.effective_chat.id, action="typing")

            # Reduce pressure on tokio-cli over time (backoff).
            if elapsed >= 60:
                poll_interval = 5
            elif elapsed >= 30:
                poll_interval = 3

            try:
                status_response = await client.get(f"{CLI_SERVICE_URL}/api/cli/jobs/{job_id}")
            except Exception:
                # Keep polling; the job may still be running.
                continue
            if status_response.status_code != 200:
                continue

            job_status = status_response.json()
            if job_status["status"] in ["completed", "failed"]:
                if job_status["status"] == "completed":
                    result = job_status.get("result", "No result")
                    if len(result) > 4000:
                        chunks = [result[i : i + 4000] for i in range(0, len(result), 4000)]
                        for chunk in chunks:
                            await _safe_reply_text(update, chunk)
                    else:
                        await _safe_reply_text(update, result)
                else:
                    error = job_status.get("error", "Unknown error")
                    await _safe_reply_text(update, f"❌ Error: {error}")
                return

        await _safe_reply_text(
            update,
            "⏱️ Timeout - El comando está tomando demasiado tiempo. Sigue ejecutándose en segundo plano."
        )


def _detect_image_mime(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:16]:
        return "image/webp"
    return "application/octet-stream"


async def _download_telegram_file_bytes(context: ContextTypes.DEFAULT_TYPE, file_id: str) -> bytes:
    tg_file = await context.bot.get_file(file_id)
    # Prefer in-memory download
    for method_name in ("download_as_bytearray", "download_as_bytes"):
        method = getattr(tg_file, method_name, None)
        if method:
            data = await method()
            return bytes(data)
    # Fallback to disk
    import tempfile
    import pathlib

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name
    try:
        await tg_file.download_to_drive(tmp_path)
        return pathlib.Path(tmp_path).read_bytes()
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


async def _openai_vision_to_text(image_bytes: bytes, caption: str = "") -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY no configurado")

    mime = _detect_image_mime(image_bytes)
    if mime == "application/octet-stream":
        # Still attempt, but inform the model.
        mime = "image/png"

    if len(image_bytes) > TOKIO_IMAGE_MAX_BYTES:
        raise RuntimeError(
            f"Imagen muy grande ({len(image_bytes)} bytes). Límite: {TOKIO_IMAGE_MAX_BYTES}."
        )

    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    user_text = (
        "Analiza la imagen adjunta y responde en Espanol.\n"
        "1) Describe lo que ves (resumen).\n"
        "2) Extrae TODO el texto visible (OCR) tal cual.\n"
        "3) Si hay informacion tecnica (logs, errores, pantallas), explica lo importante.\n"
        "4) Si hay indicadores de seguridad (IPs, dominios, comandos), listalos.\n"
        "Devuelve un resultado claro y util para que un agente pueda actuar.\n"
    )
    if caption:
        user_text += f"\nContexto del usuario (caption): {caption}\n"

    payload = {
        "model": OPENAI_VISION_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "Eres un analista experto. Se conciso y preciso.",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        "max_tokens": 900,
        "temperature": 0.2,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json=payload,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI vision error: {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        return (data["choices"][0]["message"]["content"] or "").strip()


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo/image documents by converting them to text first (vision/OCR)"""
    if not await _guard_access(update):
        return
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    caption = (update.message.caption or "").strip()

    # Pick file_id from photo or image document
    image_file_id: Optional[str] = None
    if update.message.photo:
        # Choose a reasonable size to avoid huge payloads
        candidates = [p for p in update.message.photo if getattr(p, "file_id", None)]
        if candidates:
            # Prefer the largest that is <= TOKIO_IMAGE_MAX_BYTES if size info is present
            chosen = candidates[-1]
            for p in reversed(candidates):
                fs = getattr(p, "file_size", None)
                if fs and fs <= TOKIO_IMAGE_MAX_BYTES:
                    chosen = p
                    break
            image_file_id = chosen.file_id
    elif update.message.document and (update.message.document.mime_type or "").startswith("image/"):
        image_file_id = update.message.document.file_id

    if not image_file_id:
        await _safe_reply_text(update, "⚠️ Recibí un adjunto, pero no parece ser una imagen.")
        return

    await _safe_send_chat_action(context, chat_id=update.effective_chat.id, action="typing")

    try:
        image_bytes = await _download_telegram_file_bytes(context, image_file_id)
    except Exception as e:
        logger.error(f"Failed to download image: {e}")
        await _safe_reply_text(update, "❌ No pude descargar la imagen. Reintenta.")
        return

    if not OPENAI_API_KEY:
        await _safe_reply_text(
            update,
            "🖼️ Imagen recibida.\n\n"
            "⚠️ Para que Tokio pueda leer imágenes, configura `OPENAI_API_KEY` (vision) en el bot.\n"
            "Mientras tanto, describe la imagen o reenviá el texto."
        )
        return

    try:
        await _safe_reply_text(update, "🖼️ Imagen recibida. Leyendo (vision/OCR)...")
        vision_text = await _openai_vision_to_text(image_bytes, caption=caption)
    except Exception as e:
        logger.error(f"Vision analysis failed: {e}")
        await _safe_reply_text(update, f"❌ Error leyendo imagen: {str(e)[:200]}")
        return

    # Build a command for the CLI agent
    command = (
        "Tengo una imagen adjunta del usuario.\n\n"
        "ANALISIS (vision/OCR):\n"
        f"{vision_text}\n\n"
    )
    if caption:
        command += f"INSTRUCCION DEL USUARIO (caption): {caption}\n"
    else:
        command += "INSTRUCCION DEL USUARIO: (sin caption)\n"

    logger.info(f"User {user_id}: [image] caption_len={len(caption)} vision_len={len(vision_text)}")

    try:
        await _run_cli_command(update, context, user_id, command)
    except Exception as e:
        logger.error(f"Error handling image message: {e}")
        await _safe_reply_text(update, f"❌ Error: {str(e)[:200]}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user text messages"""
    if not await _guard_access(update):
        return
    user_id = update.effective_user.id
    message_text = update.message.text

    logger.info(f"User {user_id}: {message_text}")

    try:
        await _run_cli_command(update, context, user_id, message_text)
    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await _safe_reply_text(
            update,
            f"❌ Error: {str(e)[:200]}\n\nAsegúrate de que el servicio CLI esté funcionando.",
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    if not await _guard_access(update):
        return
    await _safe_reply_text(
        update,
        "📖 AYUDA - Tokio CLI Bot\n\n"
        "Comandos disponibles:\n"
        "/start - Iniciar bot\n"
        "/help - Esta ayuda\n"
        "/status - Estado del servicio\n"
        "/tools - Listar herramientas disponibles\n\n"
        "Seguridad (solo owner):\n"
        "/myid - Ver tu user_id/chat_id\n"
        "/allow <id> - Autorizar usuario\n"
        "/deny <id> - Revocar usuario\n"
        "/acl - Ver ACL actual\n\n"
        "Ejemplos de comandos:\n"
        "• 'muéstrame los contenedores docker'\n"
        "• 'agrega el sitio ejemplo.com'\n"
        "• 'lista los tenants configurados'\n"
        "• 'hazme un backup de la base de datos'\n"
        "• 'enciende las luces de la sala'\n"
        "• 'inicia la aspiradora'\n"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check CLI service status"""
    if not await _guard_access(update):
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{CLI_SERVICE_URL}/health")

            if response.status_code == 200:
                data = response.json()
                status_icon = "✅" if data["status"] == "healthy" else "⚠️"

                text = f"{status_icon} Estado del servicio: {data['status']}\n\n"
                text += "Componentes:\n"

                for comp, status in data["components"].items():
                    icon = "✅" if status == "healthy" else "❌"
                    text += f"{icon} {comp}: {status}\n"

                await _safe_reply_text(update, text)
            else:
                await _safe_reply_text(update, "❌ Servicio no disponible")
    except Exception as e:
        await _safe_reply_text(update, f"❌ Error: {str(e)[:200]}")

async def tools_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List available tools"""
    if not await _guard_access(update):
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{CLI_SERVICE_URL}/api/cli/tools")

            if response.status_code == 200:
                data = response.json()
                tools = data["tools"]

                text = f"🔧 Herramientas disponibles: {len(tools)}\n\n"

                # Group by category
                categories = {}
                for tool in tools:
                    cat = tool.get("category", "General")
                    if cat not in categories:
                        categories[cat] = []
                    categories[cat].append(tool)

                for cat, cat_tools in sorted(categories.items()):
                    text += f"**{cat}**\n"
                    for tool in cat_tools:
                        text += f"• {tool['name']}\n"
                    text += "\n"

                await _safe_reply_text(update, text)
            else:
                await _safe_reply_text(update, "❌ No se pudieron obtener las herramientas")
    except Exception as e:
        await _safe_reply_text(update, f"❌ Error: {str(e)[:200]}")

async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages - transcribe and process"""
    if not await _guard_access(update):
        return
    user_id = update.effective_user.id
    voice = update.message.voice
    
    # Show typing indicator
    await _safe_send_chat_action(context, chat_id=update.effective_chat.id, action="typing")
    
    try:
        # Download voice file
        file = await context.bot.get_file(voice.file_id)
        
        # Try to transcribe using OpenAI Whisper API or similar
        # For now, we'll use a simple approach: download and attempt transcription
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.ogg') as tmp_file:
            await file.download_to_drive(tmp_file.name)
            tmp_path = tmp_file.name
        
        # Try transcription using Gemini API
        transcription = None
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        
        logger.info(f"Voice handler: GEMINI_API_KEY present: {bool(gemini_api_key)}")
        
        if gemini_api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_api_key)
                
                # Convert OGG to format Gemini accepts (MP3 or WAV)
                import subprocess
                mp3_path = tmp_path.replace('.ogg', '.mp3')
                # Try to convert to MP3 (Gemini accepts MP3, WAV, etc.)
                result = subprocess.run(
                    ['ffmpeg', '-i', tmp_path, '-ar', '16000', '-ac', '1', '-f', 'mp3', mp3_path],
                    capture_output=True,
                    check=False
                )
                
                if result.returncode == 0 and os.path.exists(mp3_path):
                    logger.info("MP3 conversion successful, uploading to Gemini...")
                    # Upload audio to Gemini
                    audio_file = genai.upload_file(path=mp3_path)
                    logger.info(f"Audio uploaded: {audio_file.name}")
                    
                    # Use Gemini to transcribe
                    # Try gemini-2.0-flash first, fallback to gemini-1.5-flash
                    try:
                        model = genai.GenerativeModel('gemini-2.0-flash')
                        logger.info("Using gemini-2.0-flash model")
                    except Exception as model_error:
                        logger.warning(f"gemini-2.0-flash failed, trying gemini-1.5-flash: {model_error}")
                        model = genai.GenerativeModel('gemini-1.5-flash')
                        logger.info("Using gemini-1.5-flash model")
                    
                    # Add timeout to prevent hanging
                    try:
                        response = await asyncio.wait_for(
                            asyncio.to_thread(
                                model.generate_content,
                                [
                                    "Transcribe this audio to text in Spanish. Only return the transcription, no additional text.",
                                    audio_file
                                ]
                            ),
                            timeout=30.0  # 30 seconds max
                        )
                        transcription = response.text.strip() if response.text else None
                        logger.info(f"Transcription result: {transcription[:50] if transcription else 'None'}...")
                    except asyncio.TimeoutError:
                        logger.error("Gemini transcription timeout after 30 seconds")
                        transcription = None
                        await _safe_reply_text(
                            update,
                            "⚠️ Timeout transcribiendo audio (más de 30 segundos). "
                            "Intenta enviar el mensaje como texto."
                        )
                        # Cleanup
                        try:
                            genai.delete_file(audio_file.name)
                        except:
                            pass
                        os.unlink(mp3_path)
                        os.unlink(tmp_path)
                        return
                    
                    # Cleanup uploaded file
                    try:
                        genai.delete_file(audio_file.name)
                    except:
                        pass
                    os.unlink(mp3_path)
                else:
                    logger.warning(f"MP3 conversion failed. Return code: {result.returncode}, stderr: {result.stderr[:200]}")
                    # Fallback: try WAV format
                    wav_path = tmp_path.replace('.ogg', '.wav')
                    result = subprocess.run(
                        ['ffmpeg', '-i', tmp_path, '-ar', '16000', '-ac', '1', wav_path],
                        capture_output=True,
                        check=False
                    )
                    
                    if result.returncode == 0 and os.path.exists(wav_path):
                        logger.info("WAV conversion successful, uploading to Gemini...")
                        audio_file = genai.upload_file(path=wav_path)
                        logger.info(f"Audio uploaded: {audio_file.name}")
                        
                        # Try gemini-2.0-flash first, fallback to gemini-1.5-flash
                        try:
                            model = genai.GenerativeModel('gemini-2.0-flash')
                            logger.info("Using gemini-2.0-flash model")
                        except Exception as model_error:
                            logger.warning(f"gemini-2.0-flash failed, trying gemini-1.5-flash: {model_error}")
                            model = genai.GenerativeModel('gemini-1.5-flash')
                            logger.info("Using gemini-1.5-flash model")
                        
                        # Add timeout to prevent hanging
                        try:
                            response = await asyncio.wait_for(
                                asyncio.to_thread(
                                    model.generate_content,
                                    [
                                        "Transcribe this audio to text in Spanish. Only return the transcription, no additional text.",
                                        audio_file
                                    ]
                                ),
                                timeout=30.0  # 30 seconds max
                            )
                            transcription = response.text.strip() if response.text else None
                            logger.info(f"Transcription result: {transcription[:50] if transcription else 'None'}...")
                        except asyncio.TimeoutError:
                            logger.error("Gemini transcription timeout after 30 seconds (WAV)")
                            transcription = None
                            await _safe_reply_text(
                                update,
                                "⚠️ Timeout transcribiendo audio (más de 30 segundos). "
                                "Intenta enviar el mensaje como texto."
                            )
                            # Cleanup
                            try:
                                genai.delete_file(audio_file.name)
                            except:
                                pass
                            os.unlink(wav_path)
                            os.unlink(tmp_path)
                            return
                        
                        try:
                            genai.delete_file(audio_file.name)
                        except:
                            pass
                        os.unlink(wav_path)
                    else:
                        logger.error(f"WAV conversion also failed. Return code: {result.returncode}, stderr: {result.stderr[:200]}")
            except Exception as e:
                logger.error(f"Gemini transcription failed: {e}", exc_info=True)
                # Log the full error for debugging
                transcription = None
                # Send error message to user
                await _safe_reply_text(
                    update,
                    f"⚠️ Error al transcribir audio: {str(e)}\n\n"
                    "Intenta enviar el mensaje como texto."
                )
                # Cleanup
                try:
                    os.unlink(tmp_path)
                except:
                    pass
                return
        else:
            # No GEMINI_API_KEY configured
            await _safe_reply_text(
                update,
                "🎤 Nota de voz recibida.\n\n"
                "⚠️ Para procesar audios, configura GEMINI_API_KEY en el .env\n"
                "O envía el mensaje como texto."
            )
            # Cleanup
            try:
                os.unlink(tmp_path)
            except:
                pass
            return
        
        # Cleanup
        try:
            os.unlink(tmp_path)
        except:
            pass
        
        # Check if transcription succeeded
        if not transcription:
            # Transcription failed but we had API key
            await _safe_reply_text(
                update,
                "⚠️ No se pudo transcribir el audio.\n\n"
                "Intenta enviar el mensaje como texto."
            )
            return
        
        if transcription:
            # Process transcription as regular message
            logger.info(f"Processing transcription: {transcription}")
            await _safe_reply_text(update, f"🎤 Transcrito: {transcription}\n\nProcesando...")
            
            # Get or create session
            if user_id not in user_sessions:
                user_sessions[user_id] = f"telegram-{user_id}"
            
            session_id = user_sessions[user_id]
            
            # Send to CLI service
            try:
                timeout = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
                limits = httpx.Limits(max_connections=20, max_keepalive_connections=10)
                async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
                    logger.info(f"Sending transcription to CLI: {CLI_SERVICE_URL}/api/cli/jobs")
                    response = await client.post(
                        f"{CLI_SERVICE_URL}/api/cli/jobs",
                        json={
                            "command": transcription,
                            "session_id": session_id,
                            "max_iterations": 10,
                            "timeout": 120
                        }
                    )
                    logger.info(f"CLI response status: {response.status_code}")
                
                    if response.status_code == 200:
                        job_data = response.json()
                        job_id = job_data["job_id"]
                        logger.info(f"Job created: {job_id}")
                        
                        # Poll for result (same as handle_message)
                        max_wait = 120
                        poll_interval = 2
                        elapsed = 0
                        
                        while elapsed < max_wait:
                            await asyncio.sleep(poll_interval)
                            elapsed += poll_interval
                            
                            if elapsed % 10 == 0:
                                await _safe_send_chat_action(
                                    context,
                                    chat_id=update.effective_chat.id,
                                    action="typing",
                                )
                            if elapsed >= 60:
                                poll_interval = 5
                            elif elapsed >= 30:
                                poll_interval = 3
                            
                            status_response = await client.get(
                                f"{CLI_SERVICE_URL}/api/cli/jobs/{job_id}"
                            )
                            
                            if status_response.status_code != 200:
                                logger.warning(f"Job status check failed: {status_response.status_code}")
                                continue
                            
                            job_status = status_response.json()
                            logger.debug(f"Job status: {job_status.get('status')}")
                            
                            if job_status["status"] in ["completed", "failed"]:
                                if job_status["status"] == "completed":
                                    result = job_status.get("result", "No result")
                                    logger.info(f"Job completed, result length: {len(result)}")
                                    if len(result) > 4000:
                                        chunks = [result[i:i+4000] for i in range(0, len(result), 4000)]
                                        for chunk in chunks:
                                            await _safe_reply_text(update, chunk)
                                    else:
                                        await _safe_reply_text(update, result)
                                else:
                                    error = job_status.get("error", "Unknown error")
                                    logger.error(f"Job failed: {error}")
                                    await _safe_reply_text(update, f"❌ Error: {error}")
                                return
                        
                        logger.warning(f"Job timeout after {max_wait} seconds")
                        await _safe_reply_text(update, "⏱️ Timeout - El comando está tomando demasiado tiempo.")
                    else:
                        logger.error(f"CLI service error: {response.status_code} - {response.text}")
                        await _safe_reply_text(update, f"❌ Error al procesar: {response.text}")
            except Exception as e:
                logger.error(f"Error sending transcription to CLI: {e}", exc_info=True)
                await _safe_reply_text(
                    update,
                    f"❌ Error enviando transcripción al CLI: {str(e)[:200]}\n\nPor favor, envía el mensaje como texto.",
                )
        else:
            await _safe_reply_text(
                update,
                "🎤 Nota de voz recibida.\n\n"
                "⚠️ Para procesar audios, configura GEMINI_API_KEY en el .env\n"
                "O envía el mensaje como texto."
            )
            
    except Exception as e:
        logger.error(f"Error handling voice: {e}")
        await _safe_reply_text(
            update,
            f"❌ Error procesando audio: {str(e)[:200]}\n\nPor favor, envía el mensaje como texto.",
        )


async def allow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allow a user ID (owner only)"""
    if not update.effective_user:
        return
    if not _is_owner(update.effective_user.id):
        await _safe_reply_text(update, "⛔ Solo el owner puede ejecutar /allow")
        return
    if not context.args or not context.args[0].isdigit():
        await _safe_reply_text(update, "Uso: /allow <telegram_user_id>")
        return
    allowed_id = int(context.args[0])
    allowed_user_ids.add(allowed_id)
    await _safe_reply_text(update, f"✅ Usuario {allowed_id} autorizado")


async def deny_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove an allowed user ID (owner only)"""
    if not update.effective_user:
        return
    if not _is_owner(update.effective_user.id):
        await _safe_reply_text(update, "⛔ Solo el owner puede ejecutar /deny")
        return
    if not context.args or not context.args[0].isdigit():
        await _safe_reply_text(update, "Uso: /deny <telegram_user_id>")
        return
    denied_id = int(context.args[0])
    if TELEGRAM_OWNER_ID.isdigit() and denied_id == int(TELEGRAM_OWNER_ID):
        await _safe_reply_text(update, "⚠️ No puedes remover al owner de la ACL")
        return
    allowed_user_ids.discard(denied_id)
    await _safe_reply_text(update, f"✅ Usuario {denied_id} removido de ACL")


async def acl_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show ACL entries (owner only)"""
    if not update.effective_user:
        return
    if not _is_owner(update.effective_user.id):
        await _safe_reply_text(update, "⛔ Solo el owner puede ejecutar /acl")
        return
    acl_list = sorted(list(allowed_user_ids))
    owner_text = TELEGRAM_OWNER_ID if TELEGRAM_OWNER_ID else "(no configurado)"
    await _safe_reply_text(
        update,
        f"🔐 ACL actual\nOwner: {owner_text}\nPermitidos: {acl_list if acl_list else '[]'}",
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return current user/chat identifiers (useful to configure ACL)."""
    user_id = update.effective_user.id if update.effective_user else None
    chat_id = update.effective_chat.id if update.effective_chat else None
    await _safe_reply_text(update, f"🆔 user_id={user_id}\n🆔 chat_id={chat_id}")

async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors including Conflict gracefully."""
    from telegram.error import Conflict as TelegramConflict

    error = context.error
    if isinstance(error, TelegramConflict):
        logger.warning("⚠️ Conflict error (another getUpdates). Will retry automatically.")
        await asyncio.sleep(5)
        return
    if isinstance(error, (TelegramTimedOut, TelegramNetworkError)):
        logger.warning(f"⚠️ Network error: {error}. Retrying...")
        return
    logger.error(f"❌ Unhandled error: {error}", exc_info=context.error)


def main():
    """Start the bot"""
    import time

    # Get token from environment
    token = os.getenv("TELEGRAM_BOT_TOKEN")

    if not token:
        logger.error("❌ TELEGRAM_BOT_TOKEN not set")
        logger.error("Create bot with @BotFather and set TELEGRAM_BOT_TOKEN")
        return

    _init_access_control()

    # Delete any existing webhook first
    import httpx as _httpx
    try:
        resp = _httpx.get(
            f"https://api.telegram.org/bot{token}/deleteWebhook?drop_pending_updates=false",
            timeout=10,
        )
        logger.info(f"deleteWebhook: {resp.json().get('ok')}")
    except Exception as e:
        logger.warning(f"deleteWebhook failed: {e}")

    # Force-claim polling: short getUpdates to cancel any existing long-poll
    for _ in range(3):
        try:
            _httpx.get(
                f"https://api.telegram.org/bot{token}/getUpdates?offset=-1&timeout=1",
                timeout=5,
            )
        except Exception:
            pass
        time.sleep(2)

    logger.info("🤖 Telegram Bot starting...")

    # Build application with generous timeouts
    request = HTTPXRequest(
        connect_timeout=20.0,
        read_timeout=45.0,
        write_timeout=30.0,
        pool_timeout=20.0,
    )
    application = Application.builder().token(token).request(request).build()

    # Error handler (catches Conflict gracefully)
    application.add_error_handler(_error_handler)

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("tools", tools_command))
    application.add_handler(CommandHandler("allow", allow_command))
    application.add_handler(CommandHandler("deny", deny_command))
    application.add_handler(CommandHandler("acl", acl_command))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(MessageHandler(filters.PHOTO, handle_image))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_image))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.VOICE, voice_handler))

    # Start polling - drop_pending_updates avoids replaying old messages after restart
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        poll_interval=3.0,
        timeout=30,
    )

if __name__ == "__main__":
    main()
