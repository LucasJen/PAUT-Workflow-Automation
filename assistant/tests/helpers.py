"""Test helpers: a scripted provider (no network) and a small text PDF."""
from decimal import Decimal

from assistant.providers.base import ModelInfo, Provider, ProviderError, Reply, TextDelta, ToolCall, Usage


class ScriptedProvider(Provider):
    """Replies from a script: each item is ('text', str) or ('tool', name, input) or ('error', message)."""
    key = 'scripted'
    label = 'Scripted'
    default_model = 'scripted-1'

    def __init__(self, *script):
        self.script = list(script)
        self.requests = []          # the messages each respond() call got

    def known_models(self):
        return [ModelInfo('scripted-1', 'Scripted', Decimal('1'), Decimal('5'))]

    def models(self, api_key=None):
        return self.known_models()

    def user_message(self, text):
        return {'role': 'user', 'text': text}

    def assistant_text(self, text):
        return {'role': 'assistant', 'text': text}

    def tool_results_messages(self, results):
        return [{'role': 'tool', 'results': [list(r) for r in results]}]

    def respond(self, api_key, model, system, messages, tools):
        self.requests.append(list(messages))
        step = self.script.pop(0)
        if step[0] == 'error':
            raise ProviderError(step[1])
        usage = Usage(input_tokens=1000, output_tokens=100)
        if step[0] == 'tool':
            call = ToolCall(f'call{len(self.requests)}', step[1], step[2])
            yield Reply(message={'role': 'assistant', 'calls': [step[1]]}, text='', tool_calls=[call],
                        stop='tool_use', usage=usage, model=model)
            return
        for word in step[1].split(' '):
            yield TextDelta(word + ' ')
        yield Reply(message={'role': 'assistant', 'text': step[1]}, text=step[1], usage=usage, model=model)


def text_pdf(*pages):
    """A minimal PDF with one line of Helvetica text per page (readable by pypdfium2)."""
    objects = ['<< /Type /Catalog /Pages 2 0 R >>']
    kids = ' '.join(f'{3 + 2 * i} 0 R' for i in range(len(pages)))
    objects.append(f'<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>')
    font = 3 + 2 * len(pages)
    for i, text in enumerate(pages):
        stream = f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R '
                       f'/Resources << /Font << /F1 {font} 0 R >> >> >>')
        objects.append(f'<< /Length {len(stream)} >>\nstream\n{stream}\nendstream')
    objects.append('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    out, offsets = b'%PDF-1.4\n', []
    for n, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f'{n} 0 obj\n{body}\nendobj\n'.encode('latin-1')
    xref = len(out)
    out += f'xref\n0 {len(objects) + 1}\n0000000000 65535 f \n'.encode()
    out += b''.join(f'{o:010d} 00000 n \n'.encode() for o in offsets)
    out += f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return out
