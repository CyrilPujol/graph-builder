# Graph Builder development version

The version shown at the end of the `?` guide comes from
`graph_builder_core/version.py`. Keep it equal to the version in `pyproject.toml`.
The current development sequence starts at `1.0.0.0`. On each later user prompt
about this project, increment the fourth component exactly once, including a
discussion-only prompt. Do not increment for tool calls, test runs, or assistant
continuations of the same prompt. Change the first three components only when
the user chooses a new major, update, or patch release.
