#!/bin/sh
# In the lab container: compile McCheck and run jobs.jsonl through each version given -> stdout (one JSON per job)
cd /opt/lab && tar -xf /opt/lab.tar && javac -proc:none -d cls -cp "/srv/mc/1.21.11/cp/lib/*" McCheck.java 2>&1 | grep -v "^Note\|warning" | tail -3
jobs=${JOBS:-jobs.jsonl}
for v in "$@"; do
  m=/srv/mc/$v/server_mappings.txt; [ -f "$m" ] || m=""
  echo "== $v"
  java -Xmx1500m -cp "cls:/srv/mc/$v/cp/server.jar:/srv/mc/$v/cp/lib/*" starmc.McCheck $m < "$jobs" 2>err-$v.log
  grep -E "STDERR|Exception" err-$v.log | grep -v "^\s*at " | tail -4 | cut -c1-400
done
