from __future__ import annotations


class ProviderError(Exception):
    """A market-data provider failed to deliver usable data.

    Raised on transport failures, empty/garbage responses, or validation rejects.
    The ingest orchestrator treats this as the signal to attempt fallback.
    """

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider


class RateLimitError(ProviderError):
    """Provider rejected the request for exceeding its quota / rate limit."""

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, provider=provider)
        self.retry_after = retry_after
