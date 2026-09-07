# Contributing

## Scope comes first

This package does exactly one thing: it gives node_exporter's `rapl`
collector read access to the RAPL energy counters on EL9 with the least
privilege that achieves it. Pull requests that turn it into a general
node_exporter configuration package, add collectors, ship a node_exporter
build, or widen the access beyond the `rapl` group will be declined. The
mechanism is deliberately small (a group, a udev rule, a template unit, a
drop-in) and changes to it need to keep the properties documented in
README.md: no world-readable counters, no capabilities for the exporter,
works in every SELinux mode without a policy module, re-applies on module
reload.

There is no code and there are no dependencies to manage. Dependabot
opens weekly, grouped pull requests for the workflow actions only
(`.github/dependabot.yml`); its generated commit messages are exempt from
the commit-message checks below.

## Commit messages

Every commit follows [Conventional Commits](https://www.conventionalcommits.org/):
`<type>(<scope>): <description>` with types
`feat fix docs test refactor perf build ci chore revert` and scopes
`udev systemd sysusers rpm ci docs scripts deps`. Subject in the
imperative mood, lower case after the type, no trailing period, at most
72 characters. Prefer a bullet-point body, one bullet per discrete change
or rationale, over prose. Breaking changes use `!` and a
`BREAKING CHANGE:` footer.

Commits must state self-contained facts. A message has to remain fully
intelligible to someone reading `git log` years from now with no access
to any surrounding context: state what changed and why in terms of the
files and the system, never in terms of the process that produced the
change. Do not reference conversations, review rounds, tickets that may
become unreachable, relative time ("yesterday", "the previous commit")
or the author's working state. If a bug motivated the change, describe
its observable symptom and mechanism in the body. Issue/PR numbers may
be added as trailers for convenience, but the message must stand alone
if those links die. Commit messages must not reference AI tooling: no
co-author trailers, no generation notes.

CI enforces structure with commitlint (`.commitlintrc.yml`) and the
context rule heuristically with `scripts/check-commit-context.sh`, both
over the full PR commit range. Run the same checks locally per commit by
opting into the shipped hook:

```console
$ git config core.hooksPath .githooks
```

## Merge policy: signed commits, fast-forward only

`main` accepts only signed commits, and neither force pushes nor
deletion (repository rulesets: *Require signed commits*, *Block force
pushes*, *Restrict deletions*; keep them across maintainer changes).
Sign your commits with GPG or SSH (`git config commit.gpgsign true`).
Unsigned commits cannot reach `main` at all.

Pull requests are merged by fast-forwarding `main` to the PR head, never
by squash or merge commits. Squash merging would discard the individual
commit messages that commit linting exists to protect, and a merge
commit would break the linear history; keep both buttons disabled in the
repository settings. GitHub's "Rebase and merge" button is unusable as
well: it rewrites every commit with GitHub as the committer, which drops
the authors' signatures, so GitHub refuses it on a branch that requires
signed commits. A maintainer merges from a clone instead:

```console
$ gh pr checkout <number>            # CI green, every commit signed
$ git switch main
$ git merge --ff-only @{-1}          # fast-forward to the PR head
$ git push origin main
```

GitHub marks the pull request as merged once `main` contains its head
commit. If `main` moved after the PR was last rebased, rebase the PR
branch and push it first; the person rebasing re-signs the commits.
Every commit therefore reaches `main` verbatim and each linted message
survives into permanent history. A PR title check is deliberately
absent, because titles never reach `main`.

The corollary: every commit in a PR is a public commit and must
independently satisfy the rules above and build cleanly. Clean up your
branch with an interactive rebase before requesting review; do not append
"fix typo" commits.

## Tests

CI has no hardware and no running udev, so it checks what can be checked
statically and in a container: `shellcheck` over the scripts,
`udevadm verify` over the rule, `systemd-sysusers --dry-run` over the
group file, `systemd-analyze verify` over the template unit, one
instance of it and the drop-in (against a stand-in exporter unit), and
`systemd-analyze security` with a threshold on the template. The RPM is
built in a Rocky 9 container (required) and in Rocky 10 and Fedora
(advisory), rebuilt from its SRPM outside the checkout so the SRPM has
to be self-contained, passed through the rpmlint policy check
(`scripts/run-rpmlint.sh`), then installed, verified with that
container's own systemd (which must accept every directive), and
removed again.

What CI cannot do is fire the udev rule against real powercap zones.
Any change to the rule, the template or the scriptlets therefore needs
the README's verification steps run on a real node, including a reboot
and a `modprobe -r intel_rapl_msr && modprobe intel_rapl_msr`, and the
commit body says so.

## Releases

Semantic versioning, `CHANGELOG.md` in Keep a Changelog format. A release
is a `vX.Y.Z` tag: the release workflow verifies tag, spec `Version:` and
the newest CHANGELOG entry agree, then builds and attaches the RPM, SRPM
and `SHA256SUMS` to the GitHub release. Bump `Version:` and add the spec
`%changelog` entry in the same commit as the CHANGELOG entry.
