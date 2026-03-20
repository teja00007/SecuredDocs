"""Live call transcription — WebSocket endpoint.

Protocol
--------
Client → Server:
  Binary frames: raw audio chunks (webm/ogg from browser MediaRecorder API)
  Text frame:    JSON {"type": "config", "mime_type": "audio/webm", "language": "en"}
  Text frame:    JSON {"type": "stop"}   → flush buffer and close

Server → Client:
  Text frames:   JSON {"type": "segment", "text": "...", "is_final": true}
  Text frame:    JSON {"type": "error", "detail": "..."}
  Text frame:    JSON {"type": "done"}

Usage (JavaScript):
  const ws = new WebSocket(`wss://nexus.example.com/api/v1/transcription/ws?token=<jwt>`);
  ws.binaryType = "arraybuffer";

  const recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
  recorder.ondataavailable = (e) => ws.send(e.data);
  recorder.start(3000);   // 3-second chunks

  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.type === "segment") appendTranscript(msg.text);
  };
"""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from src.config import get_settings
from src.core.security import decode_access_token
from src.services.transcription_service import TranscriptionService, LiveTranscriptionSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/transcription", tags=["transcription"])


@router.websocket("/ws")
async def live_transcription_ws(websocket: WebSocket, token: str = ""):
    """WebSocket endpoint for real-time audio transcription.

    Authenticate via `?token=<jwt>` query parameter.
    Accepts binary audio chunks from the browser MediaRecorder API.
    """
    # ── Auth ──────────────────────────────────────────────────────────────────
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        payload = decode_access_token(token)
        if not payload:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    settings = get_settings()
    svc = TranscriptionService(settings=settings)
    session = LiveTranscriptionSession(svc)

    try:
        while True:
            message = await websocket.receive()

            # Binary frame → audio chunk
            if "bytes" in message and message["bytes"] is not None:
                audio_chunk = message["bytes"]
                if not audio_chunk:
                    continue
                text = await session.push(audio_chunk)
                if text:
                    await websocket.send_text(json.dumps({
                        "type": "segment",
                        "text": text,
                        "is_final": True,
                    }))

            # Text frame → control message
            elif "text" in message and message["text"] is not None:
                try:
                    ctrl = json.loads(message["text"])
                except json.JSONDecodeError:
                    continue

                msg_type = ctrl.get("type", "")

                if msg_type == "config":
                    mime = ctrl.get("mime_type", "audio/webm")
                    session.set_mime_type(mime)

                elif msg_type == "stop":
                    # Flush remaining buffer and close
                    text = await session.flush()
                    if text:
                        await websocket.send_text(json.dumps({
                            "type": "segment",
                            "text": text,
                            "is_final": True,
                        }))
                    await websocket.send_text(json.dumps({"type": "done"}))
                    break

    except WebSocketDisconnect:
        logger.info("Transcription WebSocket disconnected for user %s", payload.get("sub", "?"))
    except Exception as exc:
        logger.error("Transcription WebSocket error: %s", exc)
        try:
            await websocket.send_text(json.dumps({"type": "error", "detail": str(exc)}))
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
