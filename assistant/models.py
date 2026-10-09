"""
The assistant: a chat that answers from the app's reports, setups and documents (assistant/chat.py),
through a language model provider (assistant/providers/). Settings live in one AssistantSettings
row; each conversation keeps its questions as Turns, with the provider's own transcript of each so
later questions continue the same conversation.
"""
from django.db import models

from . import secrets


class AssistantSettings(models.Model):
    """
    Preferences › Assistant (one row): the provider and model in use, each provider's API key
    (encrypted) and model list, Ollama's address, prices for models without a known price, and the
    monthly spend cap.
    """
    provider = models.CharField(max_length=30, default='anthropic')
    model = models.CharField(max_length=100, default='claude-haiku-4-5')
    api_keys = models.JSONField(default=dict, blank=True)        # {provider: encrypted key}
    model_lists = models.JSONField(default=dict, blank=True)     # {provider: [{'id', 'label'}]}, fetched with its key
    ollama_url = models.CharField('Ollama address', max_length=200, default='http://localhost:11434')
    input_price = models.DecimalField('Input price (USD per million tokens)', max_digits=8, decimal_places=3,
                                      null=True, blank=True)
    output_price = models.DecimalField('Output price (USD per million tokens)', max_digits=8, decimal_places=3,
                                       null=True, blank=True)
    monthly_cap = models.DecimalField('Monthly spending cap (USD)', max_digits=8, decimal_places=2, null=True,
                                      blank=True, help_text='The chat stops for the month when its estimated '
                                                            'spend reaches this. Blank = no cap.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = 'assistant settings'

    @classmethod
    def load(cls):
        settings, _ = cls.objects.get_or_create(pk=1)
        return settings

    def key_for(self, provider):
        stored = self.api_keys.get(provider)
        return secrets.decrypt(stored) if stored else ''

    def set_key(self, provider, value):
        keys = dict(self.api_keys)
        if value:
            keys[provider] = secrets.encrypt(value)
        else:
            keys.pop(provider, None)
            self.model_lists = {k: v for k, v in self.model_lists.items() if k != provider}
        self.api_keys = keys

    @property
    def api_key(self):
        """The key of the provider in use ('' when it has none)."""
        return self.key_for(self.provider)

    @api_key.setter
    def api_key(self, value):
        self.set_key(self.provider, value)

    def has_key_for(self, provider):
        return bool(self.api_keys.get(provider))

    @property
    def has_key(self):
        return self.has_key_for(self.provider)

    @property
    def model_list(self):
        return self.model_lists.get(self.provider, [])

    @model_list.setter
    def model_list(self, value):
        self.model_lists = {**self.model_lists, self.provider: value}


class Conversation(models.Model):
    title = models.CharField(max_length=200, blank=True)
    # The provider whose transcripts the turns hold; another provider replays them as plain text
    provider = models.CharField(max_length=30, default='anthropic')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-pk']

    def __str__(self):
        return self.title or f'Conversation {self.pk}'

    @property
    def cost(self):
        return sum((t.cost for t in self.turns.all() if t.cost is not None), 0)


class Turn(models.Model):
    """One question and its answer, with what the model read on the way."""
    OK, ERROR, STOPPED = 'ok', 'error', 'stopped'
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='turns')
    question = models.TextField()
    answer = models.TextField(blank=True)
    answer_html = models.TextField(blank=True)
    status = models.CharField(max_length=10, default=OK)
    provider = models.CharField(max_length=30)
    model = models.CharField(max_length=100)
    # The provider's own messages for this turn (question, tool calls and results, answer), replayed
    # unchanged on later questions; empty for a turn that failed part-way
    transcript = models.JSONField(default=list, blank=True)
    sources = models.JSONField(default=list, blank=True)      # [{'label', 'url'}]
    steps = models.JSONField(default=list, blank=True)        # what it looked up, for the page: ['Searched ...']
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    cache_write_tokens = models.PositiveIntegerField(default=0)
    cost = models.DecimalField(max_digits=10, decimal_places=5, null=True, blank=True)   # None: price unknown
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']


class IndexedItem(models.Model):
    """What the search index (assistant/index.py) holds for one report, setup or document, by stamp and fingerprint."""
    kind = models.CharField(max_length=20)
    object_id = models.PositiveIntegerField()
    fingerprint = models.CharField(max_length=64)
    # A cheap sign of change (index._stamps): the item is only read again when it differs
    stamp = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['kind', 'object_id'], name='assistant_indexed_item_unique')]
