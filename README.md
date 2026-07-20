# Most impactful engineers at PostHog

Live dashboard: **https://posthog-engineering-impact.netlify.app**

An interactive dashboard that answers one question for a busy engineering leader:
who are the most impactful engineers on [PostHog/posthog](https://github.com/PostHog/posthog),
and why. It covers the last 90 days (2026-04-20 to 2026-07-19): 10,165 merged PRs across
228 contributors.

## How impact is defined

Counting commits or lines of code rewards volume, not impact. Every engineer is scored on six
transparent signals, and the raw numbers behind each are shown on the card so any ranking can
be checked.

| Signal | Weight | What it captures |
|---|---|---|
| Scope & Ownership | 16% | Distinct PRs shipped, not lines of code |
| Criticality | 20% | Work in hot, shared, core code, weighted by how many others touch each file |
| Review Leverage | 20% | Distinct teammates unblocked through code review (every inline review comment, full 90 days) |
| Collaboration Centrality | 16% | Eigenvector centrality in the engineer co-edit network |
| Consistency | 15% | Share of the 13 weeks with at least one shipped PR |
| Reliability | 13% | Starts at 100, drops when their PRs are later reverted |

The count-based signals are percentile ranked among the 137 engineers with 3 or more PRs, and
impact is the weighted average. Two signals (Review Leverage and Collaboration Centrality) are
built specifically to measure leverage over other people rather than personal output, so a
broad reviewer can outrank a high-volume author.

## Top 5

1. pauldambra (Paul D'Ambra), 98.9
2. webjunkie (Julian), 97.8
3. rafaeelaudibert (Rafael Audibert), 96.7
4. skoob13 (Georgiy Tarasov), 96.3
5. Gilbert09 (Tom Owers), 94.3

## Data and stack

Data comes from the complete squash-merge history of the repo (11,444 commits, pulled with
git) plus the GitHub API for the 90-day review graph and contributor identities. The pipeline
(`scripts/`) writes one static `data.json`, so the dashboard loads in under a second with no
live API calls. Built with Python (standard library) and React + Vite.
