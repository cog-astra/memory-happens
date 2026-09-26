# Contributing

Use English for code, documentation, reports, tests, commit messages and attribution.
Keep reports small enough to act on. Use synthetic examples instead of personal conversations,
credentials or machine-specific configuration, even while this repository is private.

## Report or propose

Search existing issues first. Include the goal, observed result, expected result and a minimal
reproduction when available. For a design idea, explain which difficulty it addresses and
what observation would tell us it helped. Unknowns are welcome; a proposed solution is optional.

```sh
gh issue list --repo cog-astra/memory-happens --state open
gh issue create --repo cog-astra/memory-happens --title "Short problem statement" --body-file issue.md
```

## Change

Clone this repository into a separate checkout; do not develop in the installed skill directory.
Use one branch per change, link its issue if there is one, and open a PR with the observed
before/after behavior, checks performed and remaining limitations. Until draft PRs are available,
prefix unfinished PR titles with `WIP:` and remove the prefix when ready for review. Do not merge WIP PRs.
Do not commit local settings or test recordings from a real user's archive.

```sh
git clone https://github.com/cog-astra/memory-happens.git
cd memory-happens
git switch -c fix/short-description
# Make and check the change, then commit it.
git push -u origin HEAD
gh pr create --repo cog-astra/memory-happens --title "WIP: Concrete change" --body-file pr.md
```

The import PR must establish the test command and dependencies. Until it lands there is no
implementation on the default branch to validate. Merging a PR does not update installations;
deployment must name and verify the installed revision separately.

## Review

Ask another session to review the PR URL and exact head SHA, with the intent and checks.
Use an existing authorized communication channel; there is no automatic review dispatcher.
Reviewers distinguish what they inspected from what they ran, and report defects with evidence.
Resolve blocking findings before merge. A changed head requires review of the changes.

When sessions share a GitHub account, GitHub cannot record that account approving its own PR.
Use a review comment identifying the reviewing agent and exact SHA instead; it is a workflow
convention, not independently enforced identity. Do not claim a separate human review.
Attribute agent work in the PR or review body without inventing email addresses or accounts.

Authentication belongs to each session's environment. Never put tokens in prompts, issues,
commits or this repository. Additional accounts need repository access before contributing.
