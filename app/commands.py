"""THE ASSISTANT'S MESSAGES, ANSWERED IN THE WORKER.

Owner, 2026-10-01: "This needs to be the approach with every single heavy
operation." A WhatsApp or Telegram message — typed, spoken, a file, the
feedback on a draft — was answered by the command agent in a thread inside
the WEB service: model calls, transcription, media downloads and, through
the agent, whole skill runs, on the process that serves the console. The
webhooks still answer at once; the work is the `command` job, run here, one
at a time and in order (`jobs.KINDS["command"]["serial"]`), because two at
once were the concurrent Google calls that crashed the process (exit 139).

Found on the move: a typed command read `meta.get("chat_id")` where only the
file and Telegram-voice branches had ever set `meta`, so the first typed
message after a restart failed with UnboundLocalError and every later one
went to the agent with no account. The chat id now rides with the message.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger("commands")


def _active_tenant(chat_id: str) -> str:
    """Which account this sender is working on, for the agent's context."""
    from . import tenants as _tn
    try:
        return _tn.active(_tn.user_for_chat(chat_id)) if chat_id else ""
    except Exception:                                            # noqa: BLE001
        return ""


def job(tenant: str = "", *, kind: str, payload: str = "", chat_id: str = "", progress=None) -> dict:
    """One message, answered — the queue's door (`fn(tenant=..., **payload)`)."""
    from . import command_agent, whatsapp
    try:
        if kind == "feedback":
            from . import db, voice_learn
            fb = json.loads(payload)
            if fb["text"].strip().lower() in ("skip", "no", "nvm", "nm"):
                whatsapp.send_text("Okay, nothing learned from that one.")
                return {"ok": True, "why": "nothing learned"}
            with db.SessionLocal() as s:
                ap = s.get(db.Approval, fb["approval_id"])
                account = (ap.payload or {}).get("account", "baci") if ap else "baci"
                orig = (ap.payload or {}).get("body", "") if ap else ""
            if fb["mode"] == "deny":
                voice_learn.add_rule(account, fb["text"])
                # A generalizable lesson is shared with every agent, not only
                # this inbox's.
                from . import memory
                low = fb["text"].lower()
                generalizable = any(k in low for k in (
                    "always", "never", "don't ", "do not", "make sure", "verify", "confirm", "every"))
                if generalizable:
                    memory.add_lesson(fb["text"], scope="global", origin="admin")
                whatsapp.send_text(
                    f"Learned for [{account}]: \"{fb['text']}\""
                    + (" — and shared as a lesson for all agents." if generalizable else
                       " — future drafts there will follow it."))
            else:  # edit -> a revised draft (always the admin agent)
                whatsapp.send_text(command_agent.handle(
                    f"Revise this draft per my instruction and queue it for "
                    f"approval (account {account}).\n\nDRAFT:\n{orig}\n\n"
                    f"MY EDIT:\n{fb['text']}", force_role="admin"))
        elif kind == "file":
            meta = json.loads(payload)
            data, real_mime = whatsapp.download_media(meta["media_id"])
            text = (meta["caption"] or
                    f"[I'm sending you a file: {meta['filename']}] — "
                    "handle it appropriately given our conversation.")
            whatsapp.send_text(command_agent.handle(
                text, attachments=[{"filename": meta["filename"], "data": data,
                                    "mime": meta["mime"] or real_mime}]))
        elif kind == "voice":
            audio, mime = whatsapp.download_media(payload)
            transcript = whatsapp.transcribe(audio, mime)
            if not transcript:
                whatsapp.send_text("I couldn't make out that voice note — try again?")
                return {"ok": True, "why": "an unclear voice note"}
            whatsapp.send_text(f"🎙 Heard: \"{transcript[:300]}\"")
            whatsapp.send_text(command_agent.handle(transcript))
        elif kind == "tg_voice":
            # Telegram's two-hop getFile flow; transcribed here, so the
            # webhook answers at once and Telegram does not retry.
            from . import channel, ops_commands, telegram
            try:
                meta = json.loads(payload)
            except ValueError:
                meta = {"file_id": payload, "chat_id": chat_id}
            audio, mime = telegram.download_media(meta["file_id"])
            transcript = telegram.transcribe(audio, mime)
            if not transcript:
                channel.send_text("I couldn't make out that voice note — try again?")
                return {"ok": True, "why": "an unclear voice note"}
            channel.send_text(f"🎙 Heard: \"{transcript[:300]}\"")
            # Spoken ops commands take the same fast path as typed ones.
            who = meta.get("chat_id", "") or chat_id
            spoken = ops_commands.handle(transcript, who)
            channel.send_text(spoken if spoken is not None
                              else command_agent.handle(transcript, tenant=_active_tenant(who)))
        else:  # a typed command — may carry a quoted message
            from . import channel
            text = payload
            if payload.startswith("{") and '"_quoted"' in payload:
                q = json.loads(payload)
                text = (f"[Replying to your earlier message, which said:\n"
                        f"\"{q['_quoted']}\"]\n\nMy reply: {q['text']}")
            channel.send_text(command_agent.handle(text, tenant=_active_tenant(chat_id)))
    except RuntimeError:
        whatsapp.send_text("Voice notes need a transcription key — add "
                           "OPENAI_API_KEY in Render and I'll handle audio.")
        return {"ok": False, "status": "failed", "why": "no transcription key"}
    except Exception as exc:                                     # noqa: BLE001
        log.exception("command handler error")
        whatsapp.send_text(f"Something broke handling that: {exc.__class__.__name__}: "
                           f"{str(exc)[:400]}")
        return {"ok": False, "status": "failed", "why": f"{exc.__class__.__name__}: {str(exc)[:200]}"}
    return {"ok": True, "why": f"{kind} answered"}
