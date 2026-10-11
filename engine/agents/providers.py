"""Compatibility adjustment verified against the Akamai workshop endpoint."""

from strands.models.openai import OpenAIModel


class AkamaiModel(OpenAIModel):
    def format_request(self, *args, **kwargs):
        request = super().format_request(*args, **kwargs)
        # Strands 1.59 emits tools=[] for ordinary text calls; this endpoint
        # rejects that shape with HTTP 400. Preserve nonempty tool definitions.
        if not request.get("tools"):
            request.pop("tools", None)
            request.pop("tool_choice", None)
        return request
