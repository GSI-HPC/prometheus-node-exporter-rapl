# prometheus-node-exporter-rapl

An RPM that lets the `rapl` collector of
[node_exporter](https://github.com/prometheus/node_exporter) read the
RAPL energy counters on EL9 nodes, without making the counters
world-readable and without giving the exporter broad capabilities.

Since Linux 5.10 (CVE-2020-8694, "PLATYPUS") every powercap zone's
`energy_uj` is mode `0400 root`, because reading the counter at a high
rate is a power side channel. node_exporter treats the resulting
*permission denied* as "no data": the collector reports success, logs
only at debug level and simply emits no `node_rapl_*` series. The usual
workaround, `chmod 0444` at boot, re-opens what the kernel closed for
every local user. This package instead creates a dedicated `rapl` group,
has that group granted read access to each zone's counter whenever the
zone appears (boot, module reload), and puts
`prometheus-node-exporter.service` into the group. Nothing else on the
node gains access.

It installs four files:

| Installed file | Purpose |
|---|---|
| `/usr/lib/sysusers.d/prometheus-node-exporter-rapl.conf` | Creates the system group `rapl`. |
| `/usr/lib/udev/rules.d/60-prometheus-node-exporter-rapl.rules` | Tags every powercap zone that has an `energy_uj` attribute for systemd and asks it to start `prometheus-node-exporter-rapl@.service` for that zone. |
| `/usr/lib/systemd/system/prometheus-node-exporter-rapl@.service` | Per-zone oneshot: `chgrp rapl` and `chmod 0440` on the zone's `energy_uj`. The instance name is the zone's escaped sysfs path. |
| `/usr/lib/systemd/system/prometheus-node-exporter.service.d/rapl.conf` | `SupplementaryGroups=rapl` for the exporter, whatever `User=` its unit uses. |

## Requirements

| Requirement | Detail |
|---|---|
| OS | EL9 (packaged and tested for Rocky Linux 9; also builds on EL10 and current Fedora). systemd 252 or later, which is what EL9 ships: that release is where systemd started re-running an inactive wanted unit when a device it is already listed on gets another add event, which the package scriptlet and module reloads rely on. |
| node_exporter | 1.2.1 or later, which is when the collector started treating *permission denied* as "no data" (prometheus/node_exporter#2092). EPEL 9 ships 1.3.1 as `golang-github-prometheus-node-exporter`, with the unit `prometheus-node-exporter.service` this package configures. The package does not depend on it: the drop-in is inert without the unit, and a node_exporter from another source with the same unit name works as well. |
| CPU / kernel | Any platform the `intel_rapl_common` driver supports: Intel, and AMD Zen from Linux 5.11 (Rocky 9's 5.14 has it). Zones show up as `/sys/class/powercap/intel-rapl:*` on both; some Intel platforms add `intel-rapl-mmio:*`, which is handled the same way. |
| SELinux | Any mode. The stock targeted policy is why the permissions are applied by a systemd service instead of a udev `RUN+=` program; see [How it works](#how-it-works). No policy module ships or is needed. |

## Install

```console
# dnf install ./prometheus-node-exporter-rapl-<version>-1.el9.noarch.rpm   # from the GitHub release
```

That is the whole procedure on a running node. The package scriptlets
create the group, replay the udev add event for every zone that already
exists (so the counters get their group and mode immediately), and mark
`prometheus-node-exporter.service` for a restart, which systemd's own RPM
file trigger performs at the end of the transaction, after the drop-in is
in place. An exporter that is not running is left alone; a node without
the unit installs cleanly and does nothing.

Verify: every zone and sub-zone shows group `rapl` and mode `0440`, the
exporter process lists the group's GID (compare `getent group rapl`),
and the series are exported.

```console
# ls -l /sys/class/powercap/*/energy_uj
-r--r----- 1 root rapl 4096 Sep  7 10:00 /sys/class/powercap/intel-rapl:0/energy_uj
-r--r----- 1 root rapl 4096 Sep  7 10:00 /sys/class/powercap/intel-rapl:0:0/energy_uj
...
# grep ^Groups /proc/$(systemctl show -p MainPID --value prometheus-node-exporter.service)/status
Groups: 991
# curl -s localhost:9100/metrics | grep ^node_rapl_
node_rapl_core_joules_total{index="0",path="/sys/class/powercap/intel-rapl:0:0"} 1.2345678e+06
node_rapl_package_joules_total{index="0",path="/sys/class/powercap/intel-rapl:0"} 2.3456789e+06
...
```

In Prometheus, `node_rapl_package_joules_total{instance="<host>:9100"}`
exists and `node_scrape_collector_success{collector="rapl"}` is 1. Note
that the latter is 1 *with or without* access, so it cannot serve as the
alert; use `absent(node_rapl_package_joules_total)` per node instead.

Reboot one node and repeat the `ls`. If the mode is back to
`-r-------- root root`, the rule did not fire; see
[Troubleshooting](#troubleshooting).

## How it works

Every RAPL zone and sub-zone (`intel-rapl:0`, `intel-rapl:0:0`,
`intel-rapl:1`, ...) is its own device in the `powercap` subsystem, so one
udev rule without globbing covers all of them; the parent control-type
device (`intel-rapl`) has no `energy_uj` and is skipped by the `ATTR`
match. sysfs attribute files accept `chgrp`/`chmod`, but the change is
lost on reboot and whenever the `intel_rapl_*` modules are reloaded, since
the zones are re-created. Applying it from the device's `add` event
covers both.

The permissions are not applied by udev itself. sysfs attributes are not
device nodes, so udev's `GROUP=`/`MODE=` keys cannot address them, and a
`RUN+="chgrp ..."` program runs in the `udev_t` SELinux domain, which the
stock RHEL 9 targeted policy allows to read and write sysfs files but not
to change their attributes (`dev_rw_sysfs`, no `setattr`). Under enforcing
mode that `chgrp` is denied. So the rule only tags the zone for systemd
and names a template unit in `SYSTEMD_WANTS`:

```udev
ACTION!="remove", SUBSYSTEM=="powercap", ATTR{energy_uj}=="?*", \
  TAG+="systemd", ENV{SYSTEMD_WANTS}+="prometheus-node-exporter-rapl@.service"
```

systemd instantiates a template named that way with the device's escaped
sysfs path, so `intel-rapl:0` starts
`prometheus-node-exporter-rapl@sys-devices-virtual-powercap-intel\x2drapl-intel\x2drapl:0.service`,
whose `%f` specifier expands back to
`/sys/devices/virtual/powercap/intel-rapl/intel-rapl:0`. The instance runs
`chgrp rapl` and `chmod 0440` on that path's `energy_uj` as root, in a
hardened oneshot with `CapabilityBoundingSet=CAP_CHOWN` and no network. A
service started from `init_t` without a policy of its own runs as
`unconfined_service_t`, which may change sysfs attributes; the same
pattern systemd uses for `systemd-backlight@.service`. The instance does
not stay active after it finishes. A module reload re-creates the zone
devices, so their device units go through dead → plugged again and pull
the instances in a second time; and since systemd 252 a repeated `add`
event on an already plugged device restarts a listed wanted unit that is
not active, which is what the `udevadm trigger` in the package scriptlet
relies on.

The exporter side is a single drop-in line, `SupplementaryGroups=rapl`.
It is additive and independent of the unit's `User=`, so it works with
whatever the exporter package sets, `DynamicUser=yes` included, and it
survives upgrades of that package because it lives in the vendor drop-in
directory rather than in the unit file.

## Security model

Only the `rapl` group gains read access to `energy_uj`, and the only
member of that group is the exporter process. The counter files stay
owned by root with mode `0440`. The per-zone service runs as root because
the files are root-owned sysfs attributes, but with its capability
bounding set reduced to `CAP_CHOWN`, no network, a read-only view of the
file system apart from `/sys`, and a system-call filter
(`systemd-analyze security` rates it 1.5, "OK").

Granting the group read access does re-expose a coarse version of the
side channel to anything that can query the exporter, because
node_exporter re-reads `energy_uj` on **every** HTTP request to
`/metrics`, not only on the Prometheus scrape interval. Make sure the
exporter port is reachable only from the Prometheus servers (firewall) or
protect it with `--web.config.file` (TLS / basic auth). At normal scrape
intervals (15 to 60 s) the exported data itself is harmless.

## Troubleshooting

| Symptom | Likely cause | Check |
|---|---|---|
| `ls -l` shows `-r-------- root root` after install | udev did not see the rule, or systemd did not start the instances | `udevadm test /sys/class/powercap/intel-rapl:0 2>&1 \| grep -E 'SYSTEMD_WANTS\|TAGS'` must list the template; `journalctl -u 'prometheus-node-exporter-rapl@*'` shows the instances and their errors; `udevadm control --reload && udevadm trigger --subsystem-match=powercap --action=add` re-runs them |
| Same, after a reboot | An instance failed (the journal says why), or the zones never got their add event through udev | `journalctl -b -u 'prometheus-node-exporter-rapl@*'`; `systemctl list-units --failed 'prometheus-node-exporter-rapl@*'`; `udevadm info /sys/class/powercap/intel-rapl:0 \| grep -E 'SYSTEMD_WANTS\|TAGS'` shows what udev recorded for the zone |
| Files are `root rapl 0440` but no `node_rapl_*` series | Exporter not restarted since the drop-in was installed, or the group was deleted | `grep ^Groups /proc/$(systemctl show -p MainPID --value prometheus-node-exporter.service)/status`; `systemctl cat prometheus-node-exporter.service` shows the drop-in; `getent group rapl`; `systemctl restart prometheus-node-exporter` |
| Exporter fails to start: `Failed to determine supplementary groups` | Group `rapl` missing while the drop-in is present | `systemd-sysusers` (re-creates it from the shipped file) |
| `node_scrape_collector_success{collector="rapl"}` is 0 | A different error than permissions: the collector reports *permission denied* as success without data | `journalctl -u prometheus-node-exporter \| grep 'collector failed' \| grep rapl` |
| No `/sys/class/powercap/intel-rapl*` at all | `intel_rapl_common` not loaded or platform unsupported (virtual machine, old CPU) | `lsmod \| grep intel_rapl`; `modprobe intel_rapl_msr`; `dmesg \| grep -i rapl` |
| SELinux AVC denials mentioning `sysfs_t` and `setattr` | A local `RUN+="chgrp"` rule from an earlier manual setup is still installed | Remove the manual rule (`/etc/udev/rules.d/60-powercap-rapl.rules` or similar); the package needs no policy module |

A collector `success` of 1 together with missing series is the expected
signature of a permission problem; a `success` of 0 is something else.

## Uninstall

```console
# dnf remove prometheus-node-exporter-rapl
```

This removes the rule, the template and the drop-in, and restarts a
running exporter so it drops the group. Counters that were already
changed keep `0440 root:rapl` until the next boot or module reload; to
reset them immediately:

```console
# chmod 0400 /sys/class/powercap/*/energy_uj
# chgrp root /sys/class/powercap/*/energy_uj
```

The `rapl` group is left in place, as system groups created by
sysusers.d always are; `groupdel rapl` removes it. A manual
`systemctl edit` override of the exporter unit is untouched either way.

## Alternatives considered

| Approach | Verdict |
|---|---|
| `chmod 0444` at boot via `sysfsutils` `/etc/sysfs.conf` (the workaround commonly quoted in prometheus/node_exporter#1892) | Works, but makes the counter readable to every local user, re-opening what the kernel closed. Requires listing each zone path explicitly. |
| udev `RUN+="chgrp rapl /sys%p/energy_uj"` | The most direct form of this package's idea, and it works with SELinux disabled or permissive. Under enforcing mode `udev_t` cannot `setattr` `sysfs_t` files, so it needs a policy module granting that to every `RUN+=` program on the box. The systemd hand-off costs one extra hop and needs no policy. |
| `systemd-tmpfiles` `z` lines plus `ExecStartPre=+systemd-tmpfiles --create <file>` in the unit | Equivalent least-privilege result without udev. Must use `/sys/devices/virtual/powercap/*/*/energy_uj` (and one more `/*` level for sub-zones) because tmpfiles does not follow the symlinks in `/sys/class`. Does not re-apply on module reload. |
| `AmbientCapabilities=CAP_DAC_READ_SEARCH` on the exporter unit | Also works, but lets node_exporter read any file on the system. |
| `--no-collector.rapl` | Correct choice if RAPL data is not needed (e.g. BMC/IPMI already reports CPU power). Removes the question entirely. |

## Verified interface facts

Recorded here so operators and reviewers do not need to re-derive them.
Re-verify against the versions actually deployed.

- Linux ≥ 5.10 creates `energy_uj` with mode `0400` (CVE-2020-8694);
  RHEL 9's 5.14 kernel has it. `name` and `max_energy_range_uj` stay
  `0444`. Each zone and sub-zone is a separate device of subsystem
  `powercap` under `/sys/devices/virtual/powercap/`, with symlinks for
  all of them, sub-zones included, directly in `/sys/class/powercap/`.
- node_exporter ≥ 1.2.1 returns `ErrNoData` on `EACCES` from either the
  zone listing or an `energy_uj` read (`collector/rapl_linux.go`), so the
  collector counts as successful; earlier versions logged an error per
  scrape. The counter is read on every `/metrics` request.
- RHEL 9 targeted policy (fedora-selinux/selinux-policy, branch `c9s`):
  `udev.te` gives `udev_t` `dev_rw_sysfs`, whose `rw_files_pattern`
  carries no `setattr`; `init.te` has `unconfined_server_domtrans(init_t)`,
  so a `bin_t` executable started by systemd runs as
  `unconfined_service_t`, an unconfined domain.
- systemd: `SYSTEMD_WANTS` with a template name instantiates it with the
  escaped sysfs path (systemd.device(5)); `%f` is the unescaped instance
  with `/` prepended (systemd.unit(5)). A device unit that goes from dead
  to plugged (first appearance, module reload) starts its Wants= through
  the retroactive dependency logic in `src/core/unit.c`. For a device
  that is already plugged, `device_add_udev_wants()` in
  `src/core/device.c` starts newly listed wanted units since v239 and,
  since v252, also listed units that are not active; before v252 a
  repeated `udevadm trigger` on an already plugged zone did nothing. The
  man page's remark that Wants= is only acted on when a device first
  becomes active predates both.
- rpm/systemd on EL9: the `systemd` package's
  `%transfiletriggerin -- /usr/lib/systemd/system` runs
  `systemd-update-helper system-reload-restart`, which is
  `systemctl daemon-reload` followed by `systemctl reload-or-restart
  --marked`; the marked-jobs D-Bus call uses `try-restart` semantics, so
  an inactive exporter is not started by the package scriptlets.

## AI usage disclosure

This project was developed with the help of an AI coding assistant,
Anthropic's Claude. Packaging, CI and documentation were drafted with it
and are reviewed and tested by the maintainers before they are committed.
Commit messages carry no AI attribution by project policy (see
[CONTRIBUTING.md](CONTRIBUTING.md)); this section is the project-level
disclosure instead.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), in particular the Conventional
Commits requirement, the self-contained-commit-message rule and the
signed-commit, fast-forward merge policy. Licensed under
[Apache-2.0](LICENSE); see [NOTICE](NOTICE).
