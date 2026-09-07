# Changelog

All notable changes to this project are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-07

### Added

- Noarch RPM granting node_exporter's `rapl` collector read access to the
  RAPL energy counters (`energy_uj`, mode `0400 root` since Linux 5.10,
  CVE-2020-8694) with least privilege: a dedicated system group `rapl`
  from sysusers.d, `0440 root:rapl` on every powercap zone's counter, and
  `SupplementaryGroups=rapl` for `prometheus-node-exporter.service`
  through a vendor drop-in that works with any `User=` setting of that
  unit.
- udev rule that tags every powercap zone carrying an `energy_uj`
  attribute (zones, sub-zones, `intel-rapl-mmio:*`) for systemd and has
  it instantiate `prometheus-node-exporter-rapl@.service` with the zone's
  sysfs path. The permissions are applied by that hardened root oneshot
  (`CapabilityBoundingSet=CAP_CHOWN`, no network, system-call filter)
  rather than by a udev `RUN+=` program, because the stock RHEL 9
  targeted policy does not let `udev_t` change sysfs file attributes;
  works in every SELinux mode without a policy module, and re-applies on
  module reload.
- Scriptlets that make `dnf install` the whole procedure on a running
  node: existing zones get their permissions through a replayed udev add
  event, and a running exporter is restarted once by systemd's RPM file
  trigger after the drop-in is in place (`try-restart` semantics; an
  inactive exporter is not started). Removal restarts the exporter the
  same way so it drops the group.
- CI: shellcheck, `udevadm verify`, `systemd-sysusers --dry-run`,
  `systemd-analyze verify` of the template, one instance and the
  drop-in, `systemd-analyze security` threshold; RPM builds on Rocky 9
  (required) plus Rocky 10 and Fedora (advisory) with an rpmlint policy
  check and an install/verify/remove test in each container; commitlint
  and self-contained-commit-message enforcement; release workflow
  producing RPM, SRPM and SHA256SUMS from a `vX.Y.Z` tag.
- Dependabot version updates for the workflow actions.

[Unreleased]: https://github.com/GSI-HPC/prometheus-node-exporter-rapl/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/GSI-HPC/prometheus-node-exporter-rapl/releases/tag/v0.1.0
