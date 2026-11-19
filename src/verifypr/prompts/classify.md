<!-- prompt: classify v1 -->
{{task}}

{{context}}

Below are the individual changes. For **every** change id, decide how it relates to what
the change should do:

- `intended` — directly does what was asked.
- `supporting` — not asked for by itself, but needed so the asked-for change works: imports,
  updating callers of something that was changed, tests for the asked-for code, config the
  asked-for code needs. Put the id of the change it supports in `supports`.
- `unintended` — not needed for what was asked: drive-by refactors, renames, reformatting
  untouched code, unrelated features or fixes, unrelated config or dependency changes.
- `unclear` — you can't tell from what you see. When unsure, answer `unclear`, never
  `intended`.

For each change also give:
- `reason`: one short plain sentence a non-expert understands ("Renames a function in the
  billing code, which the task doesn't mention").
- `theme`: a 2-4 word label for what the change is about.
- `supports`: the id it supports, or "" if none.
- `confidence`: 0-100, how sure you are.

{{changes}}
