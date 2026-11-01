# Star AI: Faster Gaming VTuber Research (2026-10-26)

Speed must be measured as simultaneous gameplay, voice and animation performance, not tokens per second in an idle terminal. For Star's intended 8 GB GPU machines, record game FPS and p95 frametime, GPU memory peak, CPU load, first audible speech, missed avatar deadlines, and independent game success.

LLama.cpp currently documents speculative decoding with draft, EAGLE-3 and n-gram modes. Compare baseline generation against each under the same prompts, model revision, KV allocation, game workload and target accuracy. Draft-token acceptance and speculative overhead can erase gains; never assume a speedup without measurements. Reference: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

Kyutai Pocket TTS v4.0.1 was released October 21, 2026 following the October 20 smaller-model release. Compare CPU synthesis on 18M, 7M and experimental 2M English variants using blinded long-form voice reviews; latency alone cannot establish naturalness. Reference: https://github.com/kyutai-labs/pocket-tts/releases

For expressive streaming, use VTube Studio's authenticated local WebSocket, custom parameter limits and timestamp-matched audio playback. Check interruption recovery, synchronized mouth movements, gaze, blinking, physics hair, and cat/puppy variants under real frame drops. Reference: https://github.com/DenchiSoft/VTubeStudio

Star can feel playful, attentive and spontaneous while disclosing that she is an AI. Do not invent a human past or imply the avatar proves consciousness. This draft contains research and a practice planner only, not a working live VTuber demonstration.
