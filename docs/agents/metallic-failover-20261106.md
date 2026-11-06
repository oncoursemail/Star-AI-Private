# metallic.club: two copies that look like one (2026-11-06)

Owner: if the primary goes down it should switch at once and show no difference; both copies stay the same by themselves;
storage must not grow.

Before: the standby's connector was off until the primary had failed two checks (up to about 30 s plus start), and each copy
kept its own trends, peaks and "people in Metallic", so numbers jumped on a switch.

Now (`server/metallic-site/failover/metallic-failover`, rewritten in Python to carry the data, see HOSTING.md section 5): both
connectors stay up; one writer runs metallic-live and publishes its live files in health.json; the other mirrors them over the
LAN, also while it has no internet. Downloads and recent launchers cross between copies. No change to the metallic-live binary,
to authorized_keys or to the firewall.

Seen: see the commit and the report of 2026-11-06. Tests: `tests/test_metallic_site.py -k failover` (8), one of them runs the real
check on two folders through a whole outage and return.

Not seen: a real primary loss with this code, and how many seconds Cloudflare takes to drop a silently dead connector (a request
sent to it in that time may fail). LAN port 8089 is still blocked by the hosts' firewall, so the link is SSH every 15 s.

Limits: a mirror can be up to 15 s behind the writer, so two requests answered by different copies can differ for that long.
Pages and release files are not mirrored: deploy to both.
