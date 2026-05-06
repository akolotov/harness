# ak-harness

A Claude Code plugin marketplace published from this repository.

## Repository structure

The repository is organized as a marketplace that contains one or more plugins, each of which can ship one or more skills (and other component types supported by Claude Code, such as agents, hooks, MCP servers, or LSP servers).

```text
harness/
├── .claude-plugin/
│   └── marketplace.json          # Marketplace manifest (ak-harness)
├── dev/                          # Plugin: ak-dev
│   ├── .claude-plugin/
│   │   └── plugin.json           # Plugin manifest
│   └── skills/
│       └── research-codebase/    # Skill
│           └── SKILL.md
└── README.md
```

### Marketplace

`.claude-plugin/marketplace.json` is the catalog. It lists every plugin published from this repo and points to each plugin's directory via the `source` field. Adding more plugins later means appending entries to the `plugins` array and creating their directories alongside `dev/`:

```text
harness/
├── .claude-plugin/marketplace.json
├── dev/                          # Plugin #1
├── ops/                          # Plugin #2 (future)
└── research/                     # Plugin #3 (future)
```

### Plugins

Each plugin lives in its own top-level directory and is self-contained. The plugin's manifest at `<plugin>/.claude-plugin/plugin.json` declares metadata (name, version, author, license) and points at the plugin's component directories.

### Skills

Skills live under `<plugin>/skills/<skill-name>/SKILL.md`. A plugin can ship multiple skills by adding more subdirectories:

```text
dev/
├── .claude-plugin/plugin.json
└── skills/
    ├── research-codebase/SKILL.md
    ├── refactor-helper/SKILL.md   # future
    └── test-writer/SKILL.md       # future
```

## Currently published

| Plugin   | Skills              | Description                          |
| :------- | :------------------ | :----------------------------------- |
| `ak-dev` | `research-codebase` | Development-focused skills for Claude Code |

## Install a plugin from this marketplace

In any Claude Code session, add the marketplace once, then install plugins from it.

1. Add the marketplace:

   ```text
   /plugin marketplace add akolotov/harness
   ```

2. Install a specific plugin (replace `<plugin-name>` with one from the table above):

   ```text
   /plugin install <plugin-name>@ak-harness
   ```

   For example:

   ```text
   /plugin install ak-dev@ak-harness
   ```

3. Browse, enable, or remove installed plugins interactively:

   ```text
   /plugin
   ```

4. Pull future updates published to this marketplace:

   ```text
   /plugin marketplace update ak-harness
   ```

## License

MIT
