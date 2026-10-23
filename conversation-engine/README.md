# Hermes 3 for AiMediaStudio

Local NousResearch Hermes 3 Llama 3.1 8B Q4_K_M. Model and official llama.cpp CPU/CUDA runtimes are used by the Studio Writing assistant. Checksums/provenance remain in installation.json and MODEL_CARD.md. The Studio adapter is freevideo-trial/local-conversation.cjs; studio-chat-worker.cjs selects loopback port 57848 and a private key. Never expose worker command lines containing that key.

Chat history/runtime settings are in freevideo-trial/studio-data. GPU mode checks resource availability; CPU is slower. Media generation and chat take turns. Model loading is lazy, idle workers unload after five minutes, and Studio offers manual unload. No companion persona or old online history is used. Model limits and unreliable tool output still apply.
