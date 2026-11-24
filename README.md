# sophiehatter572621 Runners Linux agent

This independent, non-fork repository contributes one standard Ubuntu 24.04
GitHub-hosted machine to the existing Runners fleet, tagged `github-linux-sophie`.
The bootstrap, workflow and tests are stored in this repository. It does not
check out, invoke workflows from, or require credentials from another pool.
The current native fleet agent is downloaded from the fleet control plane and
verified against its SHA-256 digest before execution.

## Independent scheduling

An hourly trigger at minute **43 UTC** requests a replacement. The three
account triggers are staggered: Eowyn :23, Sophie :43 and Luna :03. GitHub scopes
the concurrency group to this repository; it permits one active machine and
one pending replacement. New requests preserve the running job and replace
an older pending request. There is no shared pool scheduler or cross-account
API token in the workflow.

Each scheduled lease has a 345-minute budget and drains before GitHub's
six-hour job limit. A shorter manual first lease can stagger initial retirements;
later scheduled leases return to 345 minutes. The pending run starts after the
active run finishes. GitHub can delay or drop scheduled requests, and public
repository schedules disable after 60 days without repository activity. These
are best-effort schedules, with no uninterrupted-hosting guarantee.

## Configuration

Repository variable `CONTROL_URL` points to the existing HTTPS fleet origin.
Repository secret `JOIN_TOKEN` holds this repository's copy of the fleet join
credential. No GitHub API token is given to the native agent or its workloads.
Checkout credentials are not persisted. Workloads and persistent application
storage are managed by the existing fleet controller.

Use Actions → Linux fleet agent → Run workflow to request a run. The optional
`runtime_minutes` input accepts 30–345 minutes; scheduled runs always use 345.
Disable the workflow to stop requesting replacements, and cancel its active
run to stop the current machine. Other account pools are unaffected.

## Checks

`python3 -m unittest discover -s tests -v`

GitHub references: [job limits](https://docs.github.com/en/actions/reference/limits),
[concurrency](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency),
[schedule behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
