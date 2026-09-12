# Claude Code instructions

Read [AGENTS.md](AGENTS.md) and its governing [engineering policy](ENGINEERING.md).
This file adds only Claude Code behavior. Older workflow preferences cannot
restore heavier verification defaults.

## Merge alignment

Before a merge that needs approval, prepare the concrete change, relevant
verification, remaining risks, and the requested merge action. Use plan mode
when it helps make a substantial design reviewable. Do not require a separate
plan approval before routine authorized implementation, tests, or retries.
Specific merge approval still applies. If scope changes materially, explain the
change before the gated action.

## Optional tools

Use planning subagents, loops, and additional reviewers when they justify their
cost for the actual work. They are not default phases. Preserve stop conditions
for expensive or dangerous jobs and all external-action gates.

The [skills index](docs/SKILLS.md) and [command reference](docs/COMMANDS.md)
route to optional tools. [README.md](README.md#release-status) owns release truth.
Keep this file lean and put durable product decisions in their existing owner.
