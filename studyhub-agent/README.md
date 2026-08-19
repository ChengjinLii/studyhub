# StudyHub Agent

StudyHub Agent is the standalone agent, training, and evaluation workspace for
StudyHub. It is intentionally separated from the website runtime in
`../backend` and `../frontend`.

## Boundaries

- The CLI runs as its own process and does not import the FastAPI application.
- StudyHub data is accessed through approved read-only MCP tools or frozen
  offline snapshots.
- Paid-only material links, purchase data, database credentials, and write
  operations are outside the Agent contract.
- Training, evaluation, reports, and Hermes integration live in this directory.
- Model weights, generated datasets, run artifacts, local state, and the Hermes
  checkout are ignored by Git.

The website keeps its existing API, authorization, persistence, and UI code.
Nothing in this project is loaded by the website unless a separate integration
is explicitly configured later.

The standalone CLI has no Python dependency on `backend/app`. Historical
offline research modules may import exported backend contracts while replaying
frozen experiments; those imports are test-time dependencies only and do not
connect to the website database or process. Shared `backup/` and `models/`
directories are treated as read-only inputs, while new run artifacts are
written below this project.

## Layout

```text
studyhub-agent/
├── studyhub_agent/       # Standalone package and CLI support
├── ml/agentic_platform/  # SFT, RL, collection, and evaluation code
├── integrations/hermes/  # Pinned upstream metadata and minimal patches
├── scripts/              # Agent and research entry points
├── reports/              # Versioned technical reports
├── tests/                # Standalone boundary and launcher tests
└── bin/studyhub-agent    # Stable terminal entry point
```

## CLI

The launcher uses a pinned Hermes source checkout. On this machine it can use
the existing sibling checkout at `/data/chengjin/hermes-agent`; a clean checkout
can instead be prepared under `.vendor/hermes-agent`.

```bash
cd /data/chengjin/studyhub/studyhub-agent
scripts/setup-hermes.sh /data/chengjin/hermes-agent
scripts/install-cli.sh
studyhub-agent --help
```

The command installed in `~/.local/bin/studyhub-agent` delegates only to
`studyhub-agent/bin/studyhub-agent`.

## Research

Research commands resolve paths relative to this directory. Historical modules
retain the `ml.agentic_platform` import name so existing experiment locks and
artifact metadata remain interpretable.

Run documented research commands from the standalone project root:

```bash
cd /data/chengjin/studyhub/studyhub-agent
```

The repository-level `ml/agentic_platform` and
`reports/recagent/agentic-platform` entries are compatibility symlinks. They do
not contain duplicate source or report files.
