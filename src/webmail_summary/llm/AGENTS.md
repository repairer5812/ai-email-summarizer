# AGENTS.md | llm domain

## Meta Context
- **Domain**: LLM abstraction and orchestration.
- **Complexity**: Manages dual-path execution (Local `llama.cpp` vs. Remote Cloud APIs).
- **Goal**: High-quality, noise-free summarization with minimal latency.

## Core Modules
- **`provider.py`**: The central factory for LLM instances.
    - Orchestrates backend selection: `local` (llama.cpp) or `cloud` (OpenRouter/OpenAI/etc.).
    - **Priority**: Prefers `llama-server.exe` (persistent) over `llama-cli.exe` to eliminate model reload time per mail.
- **`local_engine.py`**: Automated binary lifecycle management.
    - Downloads/extracts `llama.cpp` Windows x64 binaries directly from GitHub releases.
    - Installs to `%LOCALAPPDATA%\WebmailSummary\engines\llama.cpp\<tag>\`.
- **`long_summarize.py`**: Advanced pipeline for oversized emails.
    - **Chunking**: Split-aware logic (paragraph boundaries) for bodies exceeding token limits.
    - **Synthesis**: Tiered prompt strategy (Fast/Standard/Cloud) based on model capability.
    - **Noise Stripping**: Post-processing to remove common newsletter cruft (unsubscribe links, legal footers).

## Authentication & Security
- **Keyring Enforcement**: API keys MUST NEVER be written to the database or plaintext configs.
- Always use `keyring` for credential retrieval:
  ```python
  api_key = keyring.get_password(f"webmail-summary::{provider_name}", "api_key")
  ```

## Prompting Guidelines
- **Tier-Awareness**:
    - `fast`: Focus on raw bullet points for < 3B parameter models.
    - `standard`: Use markdown headers (`###`) and structured sections for 3B-12B models.
    - `cloud`: Detailed strategic analysis with "Why it matters" insights.
- **Language**: Summaries must always be in **Korean** unless explicitly requested otherwise.
- **Compactness**: Limit final output to `max_bullets` (default: 15) to maintain Obsidian readability.
