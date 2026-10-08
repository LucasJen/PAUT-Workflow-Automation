"""
API keys at rest, encrypted with Windows' per-user data protection (DPAPI, through pywin32): the
stored value can only be decrypted by the same Windows user on the same PC, so a copied db.sqlite3
doesn't leak the key. Elsewhere (no pywin32) the key is only encoded, marked 'plain:'.
"""
import base64

try:
    import win32crypt
except ImportError:  # not Windows
    win32crypt = None

DESCRIPTION = 'PAUT Report Automation API key'


class SecretError(Exception):
    """The stored key can't be decrypted (another Windows user or PC encrypted it)."""


def encrypt(text):
    data = text.encode('utf-8')
    if win32crypt is None:
        return 'plain:' + base64.b64encode(data).decode('ascii')
    blob = win32crypt.CryptProtectData(data, DESCRIPTION, None, None, None, 0)
    return 'dpapi:' + base64.b64encode(blob).decode('ascii')


def decrypt(stored):
    kind, _, payload = stored.partition(':')
    raw = base64.b64decode(payload)
    if kind == 'plain':
        return raw.decode('utf-8')
    if kind != 'dpapi' or win32crypt is None:
        raise SecretError('This API key was saved on another computer; enter it again in Preferences › Assistant.')
    try:
        _, data = win32crypt.CryptUnprotectData(raw, None, None, None, 0)
    except Exception as e:  # pywintypes.error: another user / PC
        raise SecretError('This API key was saved by another Windows user or PC; enter it again in '
                          'Preferences › Assistant.') from e
    return data.decode('utf-8')
