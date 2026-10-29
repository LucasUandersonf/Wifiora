"""E-mail da agência: envio por SMTP e leitura de respostas por IMAP (bibliotecas padrão, sem dependência extra).

Sem SMTP configurado, nada sai: o e-mail é registrado como "simulated" (aparece no painel).
Todo e-mail comercial leva identificação da empresa, motivo do contato e link de descadastro
(e o cabeçalho List-Unsubscribe), e respeita a lista de supressão.
"""

from __future__ import annotations

import asyncio
import email
import imaplib
import logging
import re
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr
from typing import Any

from sqlalchemy import select

from app.config import Settings
from app.db import session_scope
from app.models import EmailLog, Suppression

log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def smtp_ready(st: Settings) -> bool:
    return bool(st.smtp_host and st.smtp_from)


def imap_ready(st: Settings) -> bool:
    return bool(st.imap_host and st.imap_user and st.imap_password)


def domain_of(addr: str) -> str:
    return addr.rsplit("@", 1)[-1].lower().strip() if "@" in addr else ""


async def suppressed(addr: str) -> bool:
    addr = addr.lower().strip()
    async with session_scope() as s:
        hit = (await s.execute(select(Suppression.value).where(Suppression.value.in_([addr, domain_of(addr)])))).first()
    return hit is not None


async def suppress(value: str, reason: str) -> None:
    value = value.lower().strip()
    if not value:
        return
    async with session_scope() as s:
        if await s.get(Suppression, value) is None:
            s.add(Suppression(value=value, reason=reason[:60]))


def _send_sync(st: Settings, msg: EmailMessage) -> None:
    with smtplib.SMTP(st.smtp_host, st.smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        if st.smtp_port != 25:
            smtp.starttls()
            smtp.ehlo()
        if st.smtp_user:
            smtp.login(st.smtp_user, st.smtp_password or "")
        smtp.send_message(msg)


async def send(
    st: Settings, *, to: str, subject: str, body: str, kind: str, prospect_id: str | None = None,
    unsubscribe_url: str | None = None, transactional: bool = False, html: str | None = None, from_addr: str | None = None,
    log_body: str | None = None,
) -> EmailLog:
    """Envia (ou simula) e registra. Comercial (não transacional) respeita a supressão."""
    status, error = "sent", None
    if not transactional and await suppressed(to):
        status, error = "failed", "destinatário descadastrado"
    elif not smtp_ready(st):
        status = "simulated"
    else:
        msg = EmailMessage()
        sender = from_addr or st.smtp_from
        msg["From"], msg["To"], msg["Subject"] = sender, to, subject
        msg["Message-ID"] = make_msgid(domain=domain_of(parseaddr(sender or "")[1]) or None)
        if unsubscribe_url:
            msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        msg.set_content(body)
        if html:
            msg.add_alternative(html, subtype="html")  # texto puro continua como alternativa (entregabilidade)
        try:
            await asyncio.to_thread(_send_sync, st, msg)
        except Exception as e:  # noqa: BLE001
            status, error = "failed", str(e)[:500]
            log.warning("falha ao enviar e-mail para %s: %s", to, e)
    async with session_scope() as s:
        row = EmailLog(prospect_id=prospect_id, direction="out", kind=kind, to_addr=to, from_addr=from_addr or st.smtp_from or "", subject=subject[:300],
                       body=body if log_body is None else log_body, status=status, error=error)
        s.add(row)
    return row


def _text_of(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


def strip_quoted(text: str) -> str:
    """Remove o histórico citado ("Em ... escreveu:", linhas com ">")."""
    out = []
    for line in text.splitlines():
        if line.startswith(">") or re.match(r"^(Em|On) .+(escreveu|wrote):", line.strip()):
            break
        out.append(line)
    return "\n".join(out).strip()[:4000]


def _fetch_sync(st: Settings, limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with imaplib.IMAP4_SSL(st.imap_host) as imap:  # type: ignore[arg-type]
        imap.login(st.imap_user or "", st.imap_password or "")
        imap.select("INBOX")
        _, data = imap.search(None, "UNSEEN")
        for num in (data[0].split() if data and data[0] else [])[:limit]:
            _, parts = imap.fetch(num, "(RFC822)")
            raw = parts[0][1] if parts and isinstance(parts[0], tuple) else b""
            msg = email.message_from_bytes(raw)
            out.append({
                "from": parseaddr(msg.get("From", ""))[1].lower(),
                "subject": str(make_header(decode_header(msg.get("Subject", "")))),
                "body": strip_quoted(_text_of(msg)),
            })
    return out


async def fetch_replies(st: Settings, limit: int = 30) -> list[dict[str, Any]]:
    if not imap_ready(st):
        return []
    try:
        return await asyncio.to_thread(_fetch_sync, st, limit)
    except Exception as e:  # noqa: BLE001
        log.warning("falha ao ler caixa de entrada: %s", e)
        return []
