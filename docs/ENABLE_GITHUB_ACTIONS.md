# Enable GitHub Actions CI

The box `gh` OAuth app token has scopes `gist`, `read:org`, `repo` but **not** `workflow`.
GitHub refuses any push that creates or updates paths under `.github/workflows/`.

CI definition is ready at [`ci.yml.workflow-pending`](ci.yml.workflow-pending).

## Activate (operator)

```bash
gh auth refresh -h github.com -s workflow
# or use a PAT with the workflow scope
mkdir -p .github/workflows
cp docs/ci.yml.workflow-pending .github/workflows/ci.yml
git add .github/workflows/ci.yml
git commit -m "ci: enable docker alert-drill workflow"
git push
```
