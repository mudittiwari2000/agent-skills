# MCP connection configs

Templates for MCP server entries, with **key names only** — values come from
`~/.config/agent-secrets/.env` (see the repo root README's secrets model).

- `codex-mcp.example.toml` — snippets for `~/.codex/config.toml`
  (`[mcp_servers.*]` tables). Copy the block you need into your config and
  fill env values from the canonical secrets file (or export them in your
  shell before launching Codex — Codex passes the parent environment through
  unless `env` is set explicitly).

Rule of thumb: any token an MCP server needs gets (1) a key in
`secrets/.env.example`, (2) its value in `~/.config/agent-secrets/.env`,
(3) a mention in the consuming config template here. `doctor.sh` then keeps
you honest about which keys actually resolve.
