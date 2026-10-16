"""
A headless browser for the checks that must run the page's own JavaScript (grading, the views): Microsoft
Edge, which every Windows PC has (Chrome as a fallback), driven over the DevTools protocol. Python's
standard library only - a small WebSocket client below - so nothing needs installing on a demo PC.

    with Browser() as b:
        b.navigate('http://127.0.0.1:8000/analysis/')
        b.eval('1 + 1')            # -> 2 (awaits promises, returns JSON values)
        png = b.screenshot()       # bytes
"""
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from urllib.parse import urlparse

CANDIDATES = [
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
]


class BrowserError(Exception):
    pass


def find_browser():
    for path in CANDIDATES:
        if os.path.isfile(path):
            return path
    for name in ('msedge', 'chrome', 'chromium'):
        found = shutil.which(name)
        if found:
            return found
    return None


class _WebSocket:
    """Just enough of RFC 6455 for DevTools: text frames, client masking, fragmented and long replies."""

    def __init__(self, url, timeout=60):
        parts = urlparse(url)
        self.sock = socket.create_connection((parts.hostname, parts.port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f'GET {parts.path} HTTP/1.1\r\nHost: {parts.hostname}:{parts.port}\r\nUpgrade: websocket\r\n'
                           f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        head = b''
        while b'\r\n\r\n' not in head:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise BrowserError('The browser closed the DevTools connection.')
            head += chunk
        if b' 101 ' not in head.split(b'\r\n', 1)[0]:
            raise BrowserError(f'DevTools refused the connection: {head[:80]!r}')
        self.buffer = head.split(b'\r\n\r\n', 1)[1]

    def _read(self, n):
        while len(self.buffer) < n:
            chunk = self.sock.recv(max(65536, n - len(self.buffer)))
            if not chunk:
                raise BrowserError('The browser closed the DevTools connection.')
            self.buffer += chunk
        out, self.buffer = self.buffer[:n], self.buffer[n:]
        return out

    def send(self, text):
        data = text.encode()
        head = bytes([0x81])
        n = len(data)
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 1 << 16:
            head += bytes([0x80 | 126]) + struct.pack('>H', n)
        else:
            head += bytes([0x80 | 127]) + struct.pack('>Q', n)
        mask = os.urandom(4)
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self):
        message = b''
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack('>H', self._read(2))[0]
            elif n == 127:
                n = struct.unpack('>Q', self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            opcode = b0 & 0x0F
            if opcode == 0x8:
                raise BrowserError('The browser closed the DevTools connection.')
            if opcode == 0x9:   # ping
                continue
            message += data
            if b0 & 0x80:
                return message.decode('utf-8')

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class Browser:
    def __init__(self, width=1400, height=950, timeout=60):
        self.width, self.height, self.timeout = width, height, timeout
        self.process = self.ws = None
        self.profile = None
        self._id = 0
        self.errors = []   # uncaught page errors and console.error lines

    def __enter__(self):
        exe = find_browser()
        if not exe:
            raise BrowserError('No Microsoft Edge or Chrome found to run the page in.')
        self.profile = tempfile.mkdtemp(prefix='validation-browser-')
        self.process = subprocess.Popen(
            [exe, '--headless=new', '--disable-gpu-sandbox', '--remote-debugging-port=0', f'--user-data-dir={self.profile}',
             f'--window-size={self.width},{self.height}', '--no-first-run', '--no-default-browser-check', 'about:blank'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = os.path.join(self.profile, 'DevToolsActivePort')
        for _ in range(100):
            if os.path.isfile(port_file):
                with open(port_file) as f:
                    port = f.readline().strip()
                if port:
                    break
            time.sleep(0.1)
        else:
            self.__exit__()
            raise BrowserError('The browser did not start.')
        targets = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list', timeout=10).read())
        page = next(t for t in targets if t.get('type') == 'page')
        self.ws = _WebSocket(page['webSocketDebuggerUrl'], self.timeout)
        self.send('Runtime.enable')
        self.send('Page.enable')
        self.send('Emulation.setDeviceMetricsOverride', width=self.width, height=self.height, deviceScaleFactor=1, mobile=False)
        return self

    def __exit__(self, *exc):
        if self.ws:
            self.ws.close()
        if self.process:
            self.process.kill()
            try:
                self.process.wait(10)
            except subprocess.TimeoutExpired:
                pass
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)

    def send(self, method, **params):
        self._id += 1
        self.ws.send(json.dumps({'id': self._id, 'method': method, 'params': params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get('method') == 'Runtime.exceptionThrown':
                self.errors.append(message['params']['exceptionDetails'].get('exception', {}).get('description')
                                   or message['params']['exceptionDetails'].get('text'))
            elif message.get('method') == 'Runtime.consoleAPICalled' and message['params'].get('type') == 'error':
                self.errors.append(' '.join(str(a.get('value', a.get('description', ''))) for a in message['params']['args']))
            if message.get('id') == self._id:
                if 'error' in message:
                    raise BrowserError(message['error'].get('message', str(message['error'])))
                return message.get('result', {})

    def eval(self, expression):
        """The value of a JavaScript expression in the page (promises awaited), as JSON."""
        result = self.send('Runtime.evaluate', expression=expression, awaitPromise=True, returnByValue=True)
        if 'exceptionDetails' in result:
            details = result['exceptionDetails']
            raise BrowserError(details.get('exception', {}).get('description') or details.get('text', 'JavaScript error'))
        return result.get('result', {}).get('value')

    def navigate(self, url, settle=1.5):
        self.send('Page.navigate', url=url)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            time.sleep(0.2)
            try:
                if self.eval('document.readyState') == 'complete':
                    break
            except BrowserError:
                pass
        time.sleep(settle)

    def wait_for(self, expression, timeout=None, step=0.25):
        """Waits until the expression is truthy; returns its value (or raises after `timeout` s)."""
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            value = self.eval(expression)
            if value:
                return value
            time.sleep(step)
        raise BrowserError(f'Timed out waiting for {expression}')

    def screenshot(self):
        return base64.b64decode(self.send('Page.captureScreenshot', format='png')['data'])

    def click(self, x, y, modifiers=0):
        for kind in ('mousePressed', 'mouseReleased'):
            self.send('Input.dispatchMouseEvent', type=kind, x=x, y=y, button='left', buttons=1 if kind == 'mousePressed' else 0,
                      clickCount=1, modifiers=modifiers)
