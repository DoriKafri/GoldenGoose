#!/usr/bin/env bash
# Drive PM backlog population on the deployed Railway instance.
# Creates 15 features (5 per persona) with kick_off_research=true,
# then waits for cycles to complete, then triggers ranking.
set -u
BASE="${1:-https://goldengoose-production.up.railway.app}"
LOG="${2:-scripts/drive_pm_population.log}"

# Each line: persona|context_hint  (the hint nudges the persona toward an area)
# Coverage spans the three sidebar groups: FEED, TOOLS, and PM TOOLS.
declare -a IDEAS=(
  # ─── FEED area (News, Threads) ──────────────────────────────────────────
  "cagan|FEED area: News tab — investor opens an article, what's the 'value/viability/usability/feasibility' read on the company in 30 seconds?"
  "torres|FEED area: News tab — capture user reaction snippets per article; feed that signal back to the ventures pipeline as discovery evidence."
  "doshi|FEED area: News tab — LNO tag on every article: which signals are Leverage (likely to spawn a venture) vs Overhead (noise)?"
  "cagan|FEED area: Threads — outcome view of community discussions: which threads correlate with venture decisions made later?"
  "torres|FEED area: Threads — opportunity solution tree synthesised from the day's threads, surfacing alternative bets the community is debating."

  # ─── TOOLS area (Bugs, Slack, Activity, Sim Users, Leaderboard, Live Monitor) ─
  "cagan|TOOLS area: Bugs board — frame each bug by the risk it leaks (value/viability/usability/feasibility) so we fix the riskiest first."
  "doshi|TOOLS area: Bugs board — anti-goals on the bug board: explicit list of bugs we will NOT fix this week, with the tradeoff narrative."
  "torres|TOOLS area: Slack tab — assumption ledger surfaced from the Slack conversation: the riskiest assumption discussed each week, tagged with the channel."
  "doshi|TOOLS area: Activity monitor — friction log overlay: which agents are stuck the longest and which steps eat the most LLM tokens?"
  "cagan|TOOLS area: Leaderboard — replace 'shipped count' with outcome metrics (ventures actually advanced) so output stops masquerading as outcome."

  # ─── PM TOOLS area (the new PM Team tab itself) ─────────────────────────
  "cagan|PM TOOLS area: Backlog view — a per-feature 'risk coverage' badge showing which of the 4 product risks each card has actually addressed."
  "torres|PM TOOLS area: Meetings — auto-extract assumption tests from each standup transcript and tie them to the feature being discussed."
  "doshi|PM TOOLS area: Backlog view — LNO tag on every feature card so backlog grooming is leverage-first; visually demote Overhead items."
  "doshi|PM TOOLS area: Sprints view — decision log per shipped feature: tradeoff narrative + anti-goals + the metric we'll watch post-deploy."
  "torres|PM TOOLS area: Calendar — discovery cadence widget that nudges 'one customer interview this week' for the active sprint's features."
)

mkdir -p "$(dirname "$LOG")"
exec > >(tee -a "$LOG") 2>&1
echo "── PM populator started $(date) BASE=$BASE ──"

declare -a IDS=()
i=0
for line in "${IDEAS[@]}"; do
  i=$((i+1))
  IFS='|' read -r persona hint <<< "$line"
  echo "[$i/15] persona=$persona hint=$hint"
  body=$(jq -n --arg p "$persona" --arg h "$hint" \
        '{persona:$p, context_hint:$h}')
  resp=$(curl -s -X POST "$BASE/api/pm/features" \
         -H "Content-Type: application/json" \
         --data "$body")
  fid=$(echo "$resp" | jq -r '.feature.id // empty')
  if [ -n "$fid" ]; then
    IDS+=("$fid")
    title=$(echo "$resp" | jq -r '.feature.title // ""')
    echo "    -> id=$fid title=$title"
  else
    echo "    -> FAIL: $resp"
  fi
  # Light pacing so we don't hammer the LLM all at once
  sleep 2
done

echo "Created ${#IDS[@]} features. Waiting for research cycles to complete (poll every 60s)…"

# Poll until every created feature is past 'researching' state OR 30 min elapses
deadline=$(( $(date +%s) + 1800 ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  pending=0
  done=0
  for id in "${IDS[@]}"; do
    s=$(curl -s "$BASE/api/pm/features/$id" | jq -r '.feature.status // .status // "unknown"')
    if [ "$s" = "researching" ]; then pending=$((pending+1));
    else done=$((done+1)); fi
  done
  echo "  status: done=$done pending=$pending  ($(date +%H:%M:%S))"
  [ "$pending" = "0" ] && break
  sleep 60
done

echo "Triggering rank…"
curl -s -X POST "$BASE/api/pm/run-rank" | jq .

echo "── Final backlog summary ──"
curl -s "$BASE/api/pm/features" | jq '.features | map({id, title, status, cycles: .research_cycles_completed, final: .final_score, value: .value_score, ease: .ease_score, composite: .composite_rank_score}) | sort_by(.composite // 0) | reverse'

echo "── Done $(date) ──"
