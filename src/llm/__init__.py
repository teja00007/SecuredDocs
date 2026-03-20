"""LLM provider factory."""

from src.core.interfaces import ILLM
from src.config import Settings


def get_llm(settings: Settings) -> ILLM:
    """Instantiate the configured LLM provider."""
    provider = settings.LLM_PROVIDER.lower()

    if provider == "ollama":
        from src.llm.ollama_llm import OllamaLLM
        return OllamaLLM(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.LLM_MODEL,
            timeout=180.0,
        )
    elif provider == "anthropic":
        from src.llm.anthropic_llm import AnthropicLLM
        return AnthropicLLM(api_key=settings.ANTHROPIC_API_KEY, model=settings.LLM_MODEL)
    elif provider == "openai":
        from src.llm.openai_llm import OpenAILLM
        return OpenAILLM(api_key=settings.OPENAI_API_KEY, model=settings.LLM_MODEL)
    elif provider == "gemini":
        from src.llm.providers.gemini_llm import GeminiLLM
        return GeminiLLM(api_key=settings.GEMINI_API_KEY, model=settings.LLM_MODEL)
    elif provider == "azure":
        from src.llm.providers.azure_openai_llm import AzureOpenAILLM
        return AzureOpenAILLM(
            api_key=settings.AZURE_OPENAI_API_KEY,
            endpoint=settings.AZURE_OPENAI_ENDPOINT,
            deployment=settings.LLM_MODEL,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )
    elif provider == "bedrock":
        from src.llm.providers.bedrock_llm import BedrockLLM
        return BedrockLLM(
            model_id=settings.LLM_MODEL,
            region=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
    elif provider == "vllm":
        from src.llm.providers.vllm_llm import VLLMProvider
        return VLLMProvider(base_url=settings.VLLM_BASE_URL, model=settings.LLM_MODEL)
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider!r}. "
            "Use 'ollama', 'anthropic', 'openai', 'gemini', 'azure', 'bedrock', or 'vllm'."
        )


__all__ = ["get_llm", "ILLM"]
