#!/bin/bash
# $1 = arm tag (ctrl|treat)
arm="$1"
run_site() {
  url="$1"; slug=$(echo "$url" | sed 's#https://##; s#/#_#g')
  for r in 1 2 3; do
    python -m discovery_agent.test_agent "$url" > "aaa130_s3_${arm}_${slug}_r${r}.log" 2>&1
  done
}
run_site "https://agrobook.hu" &
run_site "https://kk.coach" &
run_site "https://www.aboutyou.hu" &
wait
echo "ARM ${arm} DONE"
