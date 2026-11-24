# sophiehatter572621 Runners Linux pool

This independent repository contributes two standard Ubuntu 24.04 GitHub-hosted
machines to my existing Runners fleet. Both use the account's `github-linux-sophie` pool tag;
worker 2 has a distinct label. This repository is not a fork. It contains its
own bootstrap, workflows and tests, and does not check out another account's
repository or use another account's GitHub credentials.

## Independent worker schedules

| Worker | Workflow | Hourly trigger, UTC | Concurrency group |
| --- | --- | --- | --- |
| 1 | agent.yml | :43 | runners-single-agent |
| 2 | agent-2.yml | :13 | runners-single-agent-2 |

The six fleet triggers are staggered at :03, :13, :23, :33, :43 and :53.
Each worker has its own active job and pending replacement. Its group is scoped
to this repository and cannot block another worker or account. New requests
replace an older pending request without cancelling the active worker. There
is no central pool scheduler or cross-account API token in these workflows.

Scheduled leases use a 345-minute budget, drain and end before GitHub's
six-hour job limit. The second worker initially uses a shorter lease to offset
its first renewal by about half a lease cycle from worker 1; future scheduled
leases return to 345 minutes. GitHub can delay or drop scheduled requests,
and public repository schedules disable after 60 days without repository
activity. These are best-effort schedules, without an uninterrupted-hosting
guarantee. Runtime volumes are ephemeral; persistent data belongs in external
storage managed by the fleet's applications.

## Configuration and controls

Repository variable `CONTROL_URL` points to the existing HTTPS fleet origin.
Repository secret `JOIN_TOKEN` holds this repository's copy of the fleet join
credential. The native agent bundle comes from that control plane and is
verified against its SHA-256 digest. The agent receives no GitHub API token,
and checkout credentials are not persisted.

Use Actions → Linux fleet agent 1 or 2 → Run workflow to request a run for that
worker. The optional `runtime_minutes` input accepts 30–345 minutes. Disable
that worker's workflow to stop replacements, and cancel its active run to stop
its current machine. The other worker and account pools are unaffected.

## Checks

`python3 -m unittest discover -s tests -v`

GitHub references: [job limits](https://docs.github.com/en/actions/reference/limits),
[concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency),
[schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
