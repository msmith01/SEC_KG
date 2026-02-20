#!/usr/bin/env bash
# Polls Neo4j every 5 min and logs milestones.
# Run: bash monitor_graph.sh

LOG=/home/matt/Documents/projects/SEC/logs/graph_monitor.log
LAST_MILESTONE=0

echo "Graph monitor started $(date)" | tee -a $LOG

while true; do
  NODES=$(python3 -c "
from neo4j import GraphDatabase
d = GraphDatabase.driver('bolt://localhost:7687', auth=('neo4j','password'))
with d.session() as s:
    print(s.run('MATCH (n) RETURN count(n) as c').single()[0])
d.close()
" 2>/dev/null)

  RF=$(find /home/matt/Documents/projects/SEC/edgar_RiskFactors -name "*.txt" 2>/dev/null | wc -l)
  BD=$(find /home/matt/Documents/projects/SEC/edgar_BusinDescr  -name "*.txt" 2>/dev/null | wc -l)
  MD=$(find /home/matt/Documents/projects/SEC/edgar_MgmtDisc    -name "*.txt" 2>/dev/null | wc -l)
  DISK=$(df -h / | awk 'NR==2{print $4" free ("$5" used)"}')

  echo "$(date '+%H:%M') | Nodes: ${NODES:-0} | Files RF:$RF BD:$BD MD:$MD | Disk: $DISK" | tee -a $LOG

  # Milestone notifications
  for milestone in 1000 5000 10000 50000 100000 500000; do
    if [ "${NODES:-0}" -ge "$milestone" ] && [ "$LAST_MILESTONE" -lt "$milestone" ]; then
      echo "" | tee -a $LOG
      echo "*** MILESTONE: ${NODES} nodes in Neo4j! ***" | tee -a $LOG
      echo "    Companies collected: RF=$RF BD=$BD MD=$MD" | tee -a $LOG
      echo "" | tee -a $LOG
      LAST_MILESTONE=$milestone
    fi
  done

  sleep 300
done
