# Metallic domain readiness — October 19, 2026

## Current state

The owner designated **metallic.club** as the Metallic domain. Read-only registry,
DNS, and web checks between **2026-10-19 22:22 and 22:23 UTC** (5:22–5:23 PM
America/Chicago) confirmed registration at Porkbun and the registrar's parking
configuration. These observations do not establish a deployed Metallic website,
game server, control plane, or remote-desktop connection.

| Observation | Result at the recorded time |
| --- | --- |
| Registrar | Porkbun, IANA registrar ID 1861. |
| Registration | 2026-10-19 22:04:15 UTC; 5:04:15 PM America/Chicago. |
| Recorded expiration | 2027-10-19 22:04:15 UTC. Renewal settings were not inspected. |
| Authoritative DNS | `curitiba.ns.porkbun.com`, `fortaleza.ns.porkbun.com`, `maceio.ns.porkbun.com`, and `salvador.ns.porkbun.com`. |
| HTTP apex | Returned HTTP 200 with Porkbun's Coming Soon parking page. |
| HTTPS apex | Not verified. The inspection path returned 503 with an upstream connection failure; the cause of an origin or certificate problem was not established. |
| Wildcard | `*.metallic.club` returned `CNAME pixie.porkbun.com`, TTL 600 seconds. |
| Queried project hostnames | `rc`, `mc`, `rb`, `px`, and `progress` resolved to the parking destination. A successful DNS answer did not mean those products were deployed. |
| Minecraft service record | `_minecraft._tcp.mc.metallic.club` returned a parking CNAME and no SRV answer. |
| Other apex checks | No AAAA, CAA, or DS answer was returned. RDAP reported `delegationSigned: false`. |

These are dated observations, not a continuous monitor. The code catalog's
`dns_verified` field remains false because it does not perform a live DNS check
or verify a product destination. The observations above belong to this report.
The domain's registration is independent of application hosting and GitHub
repository access. No registrar account settings, renewal preferences, public
origin addresses, private addresses, or credentials are recorded here.

## Canonical products

The owner's October 19 naming instruction establishes the following meanings:

| Product | Meaning |
| --- | --- |
| Metallic-RC | Our own Rec Room. |
| Metallic-MC | Minecraft. |
| Metallic-RB | Roblox Rec Room. |
| Metallic-PX | Progress. |

The live repository catalog is documented in
[Metallic project names](METALLIC_PROJECT_NAMES.md). Product labels identify the
work; stable GitHub repository IDs identify its repository across a rename. A
domain or product name never grants repository permissions.

## Optional hostname layout — not configured

This layout is a proposal for later deployment configuration, not an assertion
that the services exist or that these hostnames are ready for players:

| Proposed hostname | Intended role |
| --- | --- |
| `metallic.club` | Public Metallic hub. |
| `rc.metallic.club` | Metallic-RC public information or application entry. |
| `mc.metallic.club` | Metallic-MC public entry; web and game protocols require separate configuration. |
| `rb.metallic.club` | Metallic-RB information or launch page. |
| `px.metallic.club` | Metallic-PX progress site. |

No DNS records were changed for this report. Do not replace loopback control-plane
addresses with these names. Neither the domain purchase nor this table identifies
an approved public game ingress, private management endpoint, or remote-access
destination.

## Integration requirements

1. Identify the intended public web destination and its required DNS records.
   Porkbun can retain authoritative DNS; a nameserver migration is not inherently
   required. Edit only the reviewed records that conflict with the selected
   destination, and retain unrelated mail or verification records.
2. If Metallic-PX uses GitHub Pages with `px.metallic.club`, verify `metallic.club`
   in the owner's GitHub account using GitHub's supplied TXT challenge. Configure
   the custom hostname in that repository's Pages settings before pointing DNS
   at GitHub. The subdomain CNAME target is `oncoursemail.github.io`, with no
   `/Metallic-PX/` path. Use an explicit hostname, not a GitHub Pages wildcard.
3. Metallic-PX is generated from private progress data. For publishing from a
   source branch, preserve the `CNAME` file in the generator's output. For a
   custom Actions deployment, use the Pages settings contract; GitHub documents
   that a source-tree `CNAME` file is not required for that mode. Check the actual
   publishing mode before changing the generator.
4. Verify fresh DNS answers, HTTPS, redirects, and relative asset paths after
   configuration. A parked page or successful name resolution is not an
   acceptance test for a Metallic product.
5. Configure Minecraft and native-game transport against the actual protected
   ingress assignment. Public web routing does not establish game-protocol
   support. Keep operator APIs private and retain the existing network review.

The selected public website destination and authorized registrar account access
are still needed before applying records. This report does not start that work,
enable a connector, change GitHub permissions, or expose an origin address.

## Repository evidence inspected

- Metallic-MC main `cc1e9f91b5d17e8ddb242bc09a812de1ed59f22a`:
  [infrastructure status](https://github.com/oncoursemail/Metallic-MC/blob/cc1e9f91b5d17e8ddb242bc09a812de1ed59f22a/infra/README.md),
  [loopback configuration example](https://github.com/oncoursemail/Metallic-MC/blob/cc1e9f91b5d17e8ddb242bc09a812de1ed59f22a/.env.example),
  [security boundaries](https://github.com/oncoursemail/Metallic-MC/blob/cc1e9f91b5d17e8ddb242bc09a812de1ed59f22a/docs/security.md), and
  [offline edge audit scope](https://github.com/oncoursemail/Metallic-MC/blob/cc1e9f91b5d17e8ddb242bc09a812de1ed59f22a/docs/edge-audit.md).
- Metallic-RC main `20abe16e8137874615c4cd04fe8c3d4986d0ed6c`:
  [infrastructure design and lab limits](https://github.com/oncoursemail/Metallic-RC/blob/20abe16e8137874615c4cd04fe8c3d4986d0ed6c/docs/METALLIC_OWN_INFRASTRUCTURE_2026.md).
- Metallic-PX main `135dc99e8a047827b6bf4474df0563413c2931aa`:
  [generated progress-site documentation](https://github.com/oncoursemail/Metallic-PX/blob/135dc99e8a047827b6bf4474df0563413c2931aa/README.md).

Those snapshots describe the inspected repository state. They are not a complete
inventory of deployed machines or later branch changes.

## Primary sources

- [Authoritative registry record](https://rdap.nic.club/domain/metallic.club)
- [IANA .club delegation and RDAP service](https://www.iana.org/domains/root/db/club.html)
- [Nameserver query](https://dns.google/resolve?name=metallic.club&type=NS)
- [Wildcard CNAME query](https://dns.google/resolve?name=*.metallic.club&type=CNAME)
- [Minecraft SRV query](https://dns.google/resolve?name=_minecraft._tcp.mc.metallic.club&type=SRV)
- [HTTP apex inspected](http://metallic.club)
- [Porkbun: edit DNS records](https://kb.porkbun.com/article/68-how-to-edit-dns-records)
- [GitHub: manage a Pages custom domain](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)
- [GitHub: verify a Pages custom domain](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages)
