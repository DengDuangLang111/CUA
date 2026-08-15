# taskgen — versioned copies of the (unversioned) WSL generator

The executing copy lives at `/mnt/d/research/os-simple-taskgen-v8/ostg/` on
WSL, which is NOT a git repo (CLAUDE.md §8). Load-bearing files get copied
here after changes, same pattern as `control/`. Sync = push file + compare
md5 (CLAUDE.md §9).

- `gen.py` — as of 2026-08-15: protocol adapter added. `--protocol
  auto|anthropic|openai` (auto: claude* → Anthropic `/v1/messages`, everything
  else → OpenAI `/v1/chat/completions`); OpenAI branch translates tools /
  tool_choice / responses back into the Anthropic shape so extract() and the
  retry loop are untouched; default regime for non-claude = enable_thinking
  false + forced tool_choice (the exact v11 production mechanism — verified
  against the gateway; thinking mode rejects forced calls on qwen AND
  anthropic alike); `--thinking` = thinking + auto. Claude path byte-identical
  (regression: 2/2 specs). WSL backup: `ostg/gen.py.bak-preqwen`.
