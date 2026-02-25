"""
WhatsApp Bot - Via Twilio API
Conversational interface like Telegram
"""
import os
import asyncio
import logging
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# CLI Service URL
CLI_SERVICE_URL = os.getenv("CLI_SERVICE_URL", "http://tokio-cli:8100")

# User sessions
user_sessions = {}

@app.route("/webhook", methods=['POST'])
def webhook():
    """Twilio webhook for incoming messages"""
    try:
        # Get message data
        from_number = request.form.get('From')
        message_text = request.form.get('Body')

        logger.info(f"WhatsApp message from {from_number}: {message_text}")

        # Create response
        resp = MessagingResponse()

        if not message_text:
            resp.message("❌ Mensaje vacío")
            return str(resp)

        # Process message with CLI
        result = process_message_sync(from_number, message_text)

        # Split long messages (WhatsApp limit: 1600 chars)
        if len(result) > 1500:
            chunks = [result[i:i+1500] for i in range(0, len(result), 1500)]
            for chunk in chunks:
                resp.message(chunk)
        else:
            resp.message(result)

        return str(resp)

    except Exception as e:
        logger.error(f"Error in webhook: {e}")
        resp = MessagingResponse()
        resp.message(f"❌ Error: {str(e)}")
        return str(resp)

def process_message_sync(from_number: str, message_text: str) -> str:
    """Process message synchronously (required by Flask)"""
    # Get or create session
    if from_number not in user_sessions:
        user_sessions[from_number] = f"whatsapp-{from_number.replace('+', '')}"

    session_id = user_sessions[from_number]

    try:
        # Send to CLI service (using requests for sync)
        import requests

        # Create job
        response = requests.post(
            f"{CLI_SERVICE_URL}/api/cli/jobs",
            json={
                "command": message_text,
                "session_id": session_id,
                "max_iterations": 10,
                "timeout": 60
            },
            timeout=5
        )

        if response.status_code != 200:
            return f"❌ Error al procesar: {response.text}"

        job_data = response.json()
        job_id = job_data["job_id"]

        # Poll for result (max 60 seconds for WhatsApp)
        max_wait = 60
        poll_interval = 2
        elapsed = 0

        while elapsed < max_wait:
            import time
            time.sleep(poll_interval)
            elapsed += poll_interval

            # Check job status
            status_response = requests.get(
                f"{CLI_SERVICE_URL}/api/cli/jobs/{job_id}",
                timeout=5
            )

            if status_response.status_code != 200:
                continue

            job_status = status_response.json()

            if job_status["status"] in ["completed", "failed"]:
                if job_status["status"] == "completed":
                    return job_status.get("result", "No result")
                else:
                    return f"❌ Error: {job_status.get('error', 'Unknown error')}"

        return "⏱️ Timeout - Comando tomó demasiado tiempo. Sigue ejecutándose."

    except Exception as e:
        logger.error(f"Error processing message: {e}")
        return f"❌ Error: {str(e)}"

@app.route("/health", methods=['GET'])
def health():
    """Health check endpoint"""
    return {"status": "healthy", "service": "whatsapp-bot"}

def main():
    """Start Flask server"""
    # Check Twilio credentials
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")

    if not account_sid or not auth_token:
        logger.warning("⚠️ TWILIO credentials not set")
        logger.warning("Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN")

    port = int(os.getenv("WHATSAPP_BOT_PORT", 5000))

    logger.info(f"🟢 WhatsApp Bot starting on port {port}")
    logger.info(f"Webhook URL: http://your-domain:{port}/webhook")
    logger.info("Configure this URL in Twilio Console")

    app.run(host='YOUR_IP_ADDRESS', port=port)

if __name__ == "__main__":
    main()
