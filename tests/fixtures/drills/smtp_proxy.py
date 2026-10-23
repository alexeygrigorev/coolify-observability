"""Disposable SMTP transport switch; Mailpit remains queryable during outage."""
import select
import socket
import socketserver


class Relay(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection(('mailpit', 1025), timeout=3) as upstream:
            sockets = [self.request, upstream]
            while True:
                ready, _, _ = select.select(sockets, [], [], 5)
                if not ready:
                    return
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.request else self.request).sendall(data)


socketserver.ThreadingTCPServer.allow_reuse_address = True
socketserver.ThreadingTCPServer(('0.0.0.0', 1025), Relay).serve_forever()
