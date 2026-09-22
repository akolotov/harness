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
│       ├── _lib/                 # Shared helpers used by skill scripts
│       ├── research-codebase/    # Skill
│       │   └── SKILL.md
│       ├── implementation-plan-review/
│       │   └── SKILL.md
│       ├── review-plan-findings-feedback/
│       │   └── SKILL.md
│       ├── save-review-comments/
│       │   └── SKILL.md
│       ├── spawn-review-sessions/
│       │   └── SKILL.md
│       └── wait-what-ru/
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
    ├── implementation-plan-review/SKILL.md
    ├── review-plan-findings-feedback/SKILL.md
    ├── save-review-comments/SKILL.md
    ├── spawn-review-sessions/SKILL.md
    ├── wait-what-ru/SKILL.md
    └── test-writer/SKILL.md       # future
```

A skill may depend on a sibling skill in the same plugin: `review-plan-findings-feedback`
reuses the protocol, report template, and scripts of `implementation-plan-review` through
relative paths such as `../implementation-plan-review/scripts/new_scratchpads_dir.sh`, and
`spawn-review-sessions` consumes the comments file that `save-review-comments` writes.
Directories under `skills/` that contain no `SKILL.md` (such as `_lib/`) are not skills;
they ship with the plugin and hold code shared between skills.

## Currently published

| Plugin   | Skills                           | Description                                                                      |
| :------- | :------------------------------- | :------------------------------------------------------------------------------- |
| `ak-dev` | `research-codebase`              | Evidence-backed codebase research written to a reusable research note             |
| `ak-dev` | `implementation-plan-review`     | Expert review of an implementation plan against an issue and the codebase         |
| `ak-dev` | `review-plan-findings-feedback`  | Re-review after plan-review findings were addressed; adjudicates only new problems |
| `ak-dev` | `save-review-comments`           | Persists the surviving actionable comments of a review as tagged Markdown blocks   |
| `ak-dev` | `spawn-review-sessions`          | Spawns one backgrounded Claude Code Remote Control session per saved review comment |
| `ak-dev` | `wait-what-ru`                   | Asks the agent to re-explain its last message in simple Russian, context first    |

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
