# Star AI game learning and streaming roadmap

This change adds a practice-only difficulty planner. It recommends a curated scenario with a symbolic action but never controls games, trains models, or starts broadcasts. Harder scenarios unlock after supported practice evidence, and repeated failures require a diagnosis rather than endless retries.

Research priorities: first connect verified Roblox Studio playtests, then evaluate on unseen game levels. Next benchmark CPU speech against local GPU synthesis while gaming, and compare real frame stability and audible response latency. VTube Studio motion must follow acknowledged playback and recover gracefully from interruptions. For inference, use paired hardware benchmarks to evaluate quantization, prompt caching and speculative decoding.

All feature promotions require independent evaluation and owner approval. No speed or game mastery is claimed in this draft.

Sources:
https://github.com/Roblox/creator-docs/blob/main/content/en-us/studio/mcp.md
https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md
https://github.com/DenchiSoft/VTubeStudio
https://github.com/kyutai-labs/pocket-tts/releases
