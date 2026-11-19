<!-- prompt: propose_contract v1 -->
A person described what their change should do. Turn it into a short, editable scope they
can confirm.

{{task}}

Folders in this project (top levels only):
{{folders}}

Give:
- `goal`: the description as one clear sentence.
- `allowed_paths`: glob patterns (like `services/segment/**`) for folders the change will
  probably need to touch, including their tests. Only use folders from the list above.
- `forbidden_paths`: glob patterns for sensitive folders the description gives no reason to
  touch (login/auth, infrastructure, CI, payments, migrations), if they exist in the list.
- `allowed_behaviors`: up to 4 short phrases for what should change.
- `forbidden_behaviors`: up to 4 short phrases for what must keep working as before.
