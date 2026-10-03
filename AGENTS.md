# Repository rules for coding agents

- Do all changes on a feature branch. Never commit or push directly to `main`.
- Every change to `main` must go through a GitHub pull request and its required checks.
- Before merging, create a real pull request, provide its link, and confirm that the required checks pass. Merge using GitHub's pull request merge operation; do not merge locally and push the result to `main`.
- If GitHub API access prevents opening or merging a pull request, push the feature branch and provide the GitHub compare link. State that the pull request still needs to be opened or merged; never describe a branch as a pull request.
- Commit and push useful checkpoints while working. Keep `main` intact.
- Azure infrastructure is configured manually by the owner. Workflows may publish images and update existing applications/jobs, but must not provision resources without an explicit request.
