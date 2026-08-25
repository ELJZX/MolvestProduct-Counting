"""Сервис-эмулятор линии — окно браузера для тестирования MolvestCountingSystem.

В окне проверяется подключение к серверу Django, выбираются линии и продукт,
кликом мыши «насчитывается» продукция. Данные отправляются на сервер Django
через тот же API, что использует контроллер ОВЕН (POST /api/v1/counter/),
поэтому весь стек системы работает как с настоящим контроллером.

Запуск (сервер Django должен быть запущен):
    python server.py                    # http://127.0.0.1:8050
    python server.py --port 8051        # другой порт

Параметры через переменные окружения:
    DJANGO_BASE_URL      базовый URL Django (по умолчанию http://127.0.0.1:8000)
    CONTROLLER_API_KEY   ключ из .env проекта (по умолчанию super-secret-controller-key)
"""
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / 'static'

DJANGO_BASE_URL = os.environ.get('DJANGO_BASE_URL', 'http://127.0.0.1:8000/').rstrip('/')
CONTROLLER_API_KEY = os.environ.get('CONTROLLER_API_KEY', 'super-secret-controller-key')
DEFAULT_PORT = int(os.environ.get('PORT', '8050'))

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.png': 'image/png',
    '.svg': 'image/svg+xml',
}


def proxy_request(method, path, body=None):
    url = DJANGO_BASE_URL + path
    headers = {'X-API-Key': CONTROLLER_API_KEY}
    data = None
    if body is not None:
        data = json.dumps(body).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    # ------------------------------------------------------------------
    def _send(self, status, content, content_type='application/json; charset=utf-8'):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(content)

    # ------------------------------------------------------------------
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path in ('/', '/index.html'):
            self._serve_file('index.html')
        elif path.startswith('/static/'):
            self._serve_file(path[len('/static/'):])
        elif path == '/api/config':
            self._send(200, json.dumps({
                'ok': True,
                'django_url': DJANGO_BASE_URL,
                'api_key_configured': bool(CONTROLLER_API_KEY),
            }).encode('utf-8'))
        elif path == '/api/health':
            self._proxy('GET', '/api/v1/health/')
        elif path == '/api/lines':
            self._proxy('GET', '/api/v1/sim/lines/')
        elif path == '/api/products':
            self._proxy('GET', '/api/v1/sim/products/')
        else:
            self._send(404, b'{"ok": false, "error": "not found"}')

    def do_POST(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/count':
            length = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(raw.decode('utf-8') or '{}')
            except ValueError:
                self._send(400, b'{"ok": false, "error": "invalid json"}')
                return
            self._proxy('POST', '/api/v1/counter/', payload)
        elif path == '/api/switch':
            # Смена кода продукта на линии (только по явной команде пользователя
            # с вводом пин-кода). Проксируется на Django, где проверяется пин-код.
            length = int(self.headers.get('Content-Length') or 0)
            raw = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(raw.decode('utf-8') or '{}')
            except ValueError:
                self._send(400, b'{"ok": false, "error": "invalid json"}')
                return
            self._proxy('POST', '/api/v1/sim/switch/', payload)
        else:
            self._send(404, b'{"ok": false, "error": "not found"}')

    # ------------------------------------------------------------------
    def _serve_file(self, name):
        target = (STATIC_DIR / name).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            self._send(404, b'{"ok": false, "error": "not found"}')
            return
        content = target.read_bytes()
        ctype = MIME.get(target.suffix.lower(), 'application/octet-stream')
        self._send(200, content, ctype)

    def _proxy(self, method, django_path, body=None):
        try:
            status, content = proxy_request(method, django_path, body)
            self._send(status, content)
        except urllib.error.HTTPError as exc:
            self._send(exc.code, exc.read())
        except Exception as exc:  # noqa: BLE001 — причина показывается в окне
            self._send(502, json.dumps({'ok': False, 'error': str(exc)}).encode('utf-8'))

    # ------------------------------------------------------------------
    def log_message(self, fmt, *args):
        sys.stderr.write('[simulator] %s\n' % (fmt % args))


def main():
    port = DEFAULT_PORT
    args = sys.argv[1:]
    if args and args[0] == '--port' and len(args) > 1:
        try:
            port = int(args[1])
        except ValueError:
            pass
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    print('Эмулятор линии запущен: http://127.0.0.1:%d' % port)
    print('Сервер Django: %s' % DJANGO_BASE_URL)
    print('Для остановки нажмите Ctrl+C')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nОстановлено.')


if __name__ == '__main__':
    main()
