import os
from dataclasses import dataclass
from typing import Optional, Any

from langchain_ollama import ChatOllama

from langchain_nvidia_ai_endpoints import ChatNVIDIA

from langchain_google_genai import ChatGoogleGenerativeAI

from dotenv import load_dotenv
load_dotenv()

@dataclass(frozen=True)
class LLMConfig:
    name: str
    provider: str
    model: str
    temperature: float = 0.2
    base_url: Optional[str] = None


def build_llm(cfg: LLMConfig) -> Any:
    """
    Returns a LangChain chat model instance.
    Provider behavior matches your txt skeletons (Ollama Cloud / NIM / Gemini).
    """

    if cfg.provider == "gemini":
        return ChatGoogleGenerativeAI(
            model=cfg.model,
            temperature=cfg.temperature,
        )

    if cfg.provider == "ollama_cloud":
        base_url = cfg.base_url or os.getenv("OLLAMA_BASE_URL")
        api_key = os.getenv("OLLAMA_API_KEY")

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        return ChatOllama(
            model=cfg.model,
            temperature=cfg.temperature,
            base_url=base_url,
            client_kwargs={"headers": headers} if headers else None,
        )

    if cfg.provider == "nim":
        api_key = os.getenv("NVIDIA_API_KEY")
        if not api_key:
            raise RuntimeError(
                "NVIDIA_API_KEY is missing. Django likely isn't loading .env. "
                "Load dotenv in settings.py or set the env var in your OS."
            )
        base_url = cfg.base_url or os.getenv("NVIDIA_NIM_BASE_URL") or None

        kwargs = {
            "model": cfg.model,
            "temperature": cfg.temperature,
        }
        if api_key:
            kwargs["api_key"] = api_key

        if base_url:
            try:
                return ChatNVIDIA(**kwargs, base_url=base_url)
            except TypeError:
                pass

        return ChatNVIDIA(**kwargs)


    raise ValueError(f"Unknown provider: {cfg.provider}")
