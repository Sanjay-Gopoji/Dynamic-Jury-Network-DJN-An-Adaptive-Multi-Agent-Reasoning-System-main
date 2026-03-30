from .llms import LLMConfig

JUDGE = LLMConfig(
    name="judge_gemini",
    provider="gemini",
    model="gemini-2.5-flash-lite",
    temperature=0.2,
)

JURORS = [
    LLMConfig(name="gpt-oss-20b", provider="ollama_cloud", model="gpt-oss:20b-cloud", temperature=0.4),
    LLMConfig(name="gpt-oss-120b", provider="ollama_cloud", model="gpt-oss:120b-cloud", temperature=0.35),
    LLMConfig(name="deepseek-v3.1-671b", provider="ollama_cloud", model="deepseek-v3.1:671b-cloud", temperature=0.35),
    LLMConfig(name="qwen3-coder-480b", provider="ollama_cloud", model="qwen3-coder:480b-cloud", temperature=0.35),
    LLMConfig(name="qwen3-vl-235b", provider="ollama_cloud", model="qwen3-vl:235b-cloud", temperature=0.35),
    LLMConfig(name="minimax-m2", provider="ollama_cloud", model="minimax-m2:cloud", temperature=0.35),
    LLMConfig(name="glm-4.6", provider="ollama_cloud", model="glm-4.6:cloud", temperature=0.35),

    LLMConfig(
        name="nemotron-3-nano-30b-a3b",
        provider="nim",
        model="nvidia/nemotron-3-nano-30b-a3b",
        temperature=0.35,
    )

]
