import json

from django.contrib import messages
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import chat, index
from .forms import SettingsForm
from .models import AssistantSettings, Conversation
from .providers import ProviderError, get_provider
from .secrets import SecretError


def assistant(request, pk=None):
    """The chat page: past conversations on the left, the open one (or a new one) on the right."""
    settings = AssistantSettings.load()
    conversation = get_object_or_404(Conversation, pk=pk) if pk else None
    provider = get_provider(settings.provider)
    model = next((m['label'] for m in settings.model_list if m['id'] == settings.model), None) or next(
        (m.label for m in provider.known_models() if m.id == settings.model), settings.model)
    return render(request, 'assistant/chat.html', {
        'conversations': Conversation.objects.all()[:100],
        'conversation': conversation,
        'turns': conversation.turns.all() if conversation else [],
        'settings': settings, 'model_label': model,
        'month_spend': chat._money(chat.month_spend()),
    })


@require_POST
def ask(request):
    """Streams the answer to a question as newline-delimited JSON events (chat.ask)."""
    question = request.POST.get('question', '').strip()
    if not question:
        return JsonResponse({'error': 'Type a question first.'}, status=400)
    pk = request.POST.get('conversation')
    conversation = get_object_or_404(Conversation, pk=pk) if pk else Conversation.objects.create()

    def events():
        yield json.dumps({'type': 'conversation', 'id': conversation.pk}) + '\n'
        for event in chat.ask(conversation, question):
            yield json.dumps(event) + '\n'

    response = StreamingHttpResponse(events(), content_type='application/x-ndjson')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@require_POST
def delete_conversation(request, pk):
    get_object_or_404(Conversation, pk=pk).delete()
    return redirect('assistant')


def assistant_settings(request):
    """Preferences › Assistant: provider, key, model, spending cap and the search index."""
    settings = AssistantSettings.load()
    if request.method == 'POST':
        if 'rebuild_index' in request.POST:
            count = index.rebuild()
            messages.success(request, f'Search index rebuilt ({count} reports, setups and documents read).')
            return redirect('assistant-settings')
        form = SettingsForm(request.POST, instance=settings)
        if form.is_valid():
            settings = form.save()
            if settings.has_key and ('check_key' in request.POST or form.cleaned_data.get('api_key')):
                _refresh_models(request, settings)
            else:
                messages.success(request, 'Assistant settings saved.')
            return redirect('assistant-settings')
    else:
        form = SettingsForm(instance=settings)
    return render(request, 'assistant/settings.html', {
        'form': form, 'settings': settings, 'index': index.stats(), 'month_spend': chat._money(chat.month_spend()),
    })


def _refresh_models(request, settings):
    """Checks the key with the provider and saves the models it offers."""
    provider = get_provider(settings.provider)
    try:
        models = provider.models(settings.api_key)
    except (ProviderError, SecretError) as e:
        messages.error(request, f'Settings saved, but the key didn\'t work: {e}')
        return
    settings.model_list = [{'id': m.id, 'label': m.label} for m in models]
    if settings.model not in {m.id for m in models}:
        settings.model = provider.default_model if provider.default_model in {m.id for m in models} else models[0].id
    settings.save()
    messages.success(request, f'The key works: {len(models)} models available.')
