import http.server
import ssl
from pathlib import Path

server = http.server.HTTPServer(('0.0.0.0', 443), http.server.SimpleHTTPRequestHandler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
prefix = 'invalid' if Path('/tmp/bad-tls').exists() else 'server'
context.load_cert_chain(f'/certs/{prefix}.crt', f'/certs/{prefix}.key')
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
