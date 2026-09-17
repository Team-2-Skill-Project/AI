# LLM Architecture Rule

All LLM-backed features in SkillMatch must obtain their model from
`src.core.llm.get_llm()`:

```python
from src.core.llm import get_llm

llm = get_llm()
```

Feature code must not instantiate provider SDKs, read provider API keys from
`os.getenv()`, hardcode model names, or create another LLM service abstraction.
Provider selection, credentials, timeout/retry policy, and model settings are
owned by the central `LLMSettings` configuration. There is no compatibility
service or custom provider adapter in the supported architecture. New code
must use `get_llm()` directly and must not create another service abstraction.
The future AI Mentor must use the same `get_llm()` path.
