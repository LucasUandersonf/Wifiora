"""Inicializa o servidor HTTP escutando IPv4 E IPv6 na mesma porta.

Por quê: a rede privada do Railway (usada pelo portal Next.js para falar com este backend) resolve
para IPv6 em ambientes legados, enquanto health check e tráfego público chegam por IPv4.
`uvicorn --host ::` não resolve isso: o asyncio liga IPV6_V6ONLY e o IPv4 é recusado.
"""

from __future__ import annotations

import os
import socket

import uvicorn


def dual_stack_socket(port: int) -> socket.socket:
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("::", port))
    except OSError:  # host sem IPv6: cai para IPv4
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
    sock.listen(2048)
    sock.set_inheritable(True)
    return sock


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    config = uvicorn.Config("app.main:app", proxy_headers=True, forwarded_allow_ips="*", log_level=os.getenv("LOG_LEVEL", "info").lower())
    uvicorn.Server(config).run(sockets=[dual_stack_socket(port)])


if __name__ == "__main__":
    main()
