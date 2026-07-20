# PostHog Engineering Impact - Submission

**Live dashboard:** https://posthog-engineering-impact.netlify.app
**Repo analysed:** [PostHog/posthog](https://github.com/PostHog/posthog)
**Window:** last 90 days (2026-04-20 to 2026-07-19), 10,165 merged PRs, 228 contributors

---

## Approach (short description for the form)

Counting commits, lines of code, or PR counts rewards volume, not impact. So instead of a
single number I score every engineer on six transparent signals and show the raw numbers
behind each one, so a busy leader can validate any ranking at a glance.

| Signal | Weight | What it captures |
|---|---|---|
| Scope & Ownership | 16% | Distinct PRs shipped. Self-contained units of work, not lines of code |
| Criticality | 20% | How much of the work lands in hot, shared, core code (backend, migrations, product logic) vs. tests or generated files. Each file is weighted by how many other engineers also touch it |
| Review Leverage | 20% | How many distinct teammates they unblock through code review, measured from every inline review comment over the full 90 days |
| Collaboration Centrality | 16% | Eigenvector centrality in the engineer co-edit network. Engineers who work across the same files as many teammates sit at the center of coordination |
| Consistency | 15% | Share of the 13 weeks with at least one shipped PR. Sustained contribution, not a one-week spike |
| Reliability | 13% | Did their work stick? Starts at 100 and is penalised when their PRs are later reverted |

Count-based signals (Scope, Criticality, Review Leverage, Collaboration) are normalised to a
0-100 percentile rank among the 137 engineers with 3 or more merged PRs. Reliability and
Consistency use direct, interpretable formulas. Impact is the weighted average of the six.
Bots and automated accounts are excluded, and every score is reproducible from the numbers
shown on each card.

### The two signals I care most about
The whole point is that impact is not output. Two of the signals are built specifically to
capture leverage over other people rather than personal throughput:

- **Review Leverage.** I pull every inline code-review comment for the last 90 days (50,400 of
  them) and join each one to the PR author, so I can count how many distinct teammates an
  engineer unblocks. This is high-value, mostly invisible work that no output metric captures.
- **Collaboration Centrality.** I build a graph where engineers are nodes and an edge exists
  when two people edit the same files, weighted so that rare shared files count more than
  ubiquitous ones (a lockfile everyone touches carries little signal, a core service two people
  co-own carries a lot). Eigenvector centrality then surfaces whose work is most entangled with,
  and therefore most enabling of, the rest of the team.

You can see this pay off in the ranking: **Georgiy Tarasov (skoob13) makes the top 5 on 171
PRs** because he reviews broadly (22 teammates unblocked across 67 PRs), while the single
highest-volume author (1,397 PRs) drops to #5 once leverage is taken into account.

## Top 5 most impactful engineers

1. **pauldambra** (Paul D'Ambra), 98.9. Signature: Collaboration Centrality. 640 PRs, active all 13 weeks.
2. **webjunkie** (Julian), 97.8. Signature: Criticality.
3. **rafaeelaudibert** (Rafael Audibert), 96.7. Signature: Collaboration Centrality. High impact on only 140 PRs.
4. **skoob13** (Georgiy Tarasov), 96.3. Signature: Review Leverage. Unblocked 22 teammates via review.
5. **Gilbert09** (Tom Owers), 94.3. Signature: Criticality. Data-warehouse lead, very high volume.

## Data and methodology (how to reproduce)

1. **Complete, not sampled.** I clone the last 90 days of history (`git clone --shallow-since`)
   and extract the full squash-merge history into `data/git_log.txt` (11,444 commits). PostHog
   squash-merges, so each merge commit maps 1:1 to a PR via the `(#NNNNN)` suffix, which gives
   complete author, file, date, and area data offline with no rate limits and no missing data.
2. **Reviews and identity** come from the GitHub API (`scripts/fetch_github.py`): every inline
   review comment for the window, plus a commit-email to GitHub-login map for names and avatars.
   This needs an authenticated token because of PostHog's review volume (around 900 comments a
   day), so the script reads a token from the environment or a gitignored file.
3. `scripts/analyze.py` computes the six signals and writes one self-contained
   `dashboard/public/data.json` (about 200 KB) that the static dashboard reads, so the page
   loads instantly with no live API calls.

## Tech stack
Python standard library for the pipeline (including a small hand-written power-iteration
eigenvector centrality, no heavy dependencies). React and Vite with a hand-rolled SVG radar and
no chart library for a roughly 49 KB gzipped, sub-second static dashboard.

---

## Deploy

The production build is already in `dashboard/dist/`. Pick one:

**Vercel (recommended):**
```bash
cd dashboard
npx vercel --prod
```

**Netlify Drop (no CLI):** open https://app.netlify.com/drop and drag the `dashboard/dist`
folder onto the page.

**GitHub Pages:** push this repo and enable Pages, or use a `gh-pages` action, then paste the
URL at the top of this file.

To regenerate the data from scratch:
```bash
# from the repo root, with the posthog clone in data/posthog_repo
python3 scripts/fetch_github.py   # reviews + identity (needs a token in data/gh_token.txt or env)
python3 scripts/analyze.py        # writes dashboard/public/data.json
cd dashboard && npm install && npm run build
```
