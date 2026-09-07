# SPDX-License-Identifier: Apache-2.0
# Packaged following the Fedora systemd packaging guidelines. The package
# carries no code: a sysusers.d group, a udev rule, a systemd template unit
# and a drop-in for prometheus-node-exporter.service.

# The unit this package configures; owned by the EPEL node_exporter package
# (golang-github-prometheus-node-exporter), which is deliberately not a
# dependency: the drop-in is inert without the unit.
%global exporter_unit prometheus-node-exporter.service

# The drop-in reaches the exporter only through a restart. Mark the unit
# instead of restarting it in the scriptlet: systemd's file trigger runs
# daemon-reload and then try-restarts marked units at the end of the
# transaction, once the drop-in is in place (the path
# %%systemd_postun_with_restart takes for a package's own units). An
# exporter that is not running is left alone, and a unit that is not
# installed is skipped.
%global mark_exporter_restart \
if [ -d /run/systemd/system ] && [ -x /usr/lib/systemd/systemd-update-helper ] && \
   [ "$(systemctl show -p LoadState --value %{exporter_unit} 2>/dev/null)" = loaded ]; then \
    /usr/lib/systemd/systemd-update-helper mark-restart-system-units %{exporter_unit} || : \
fi

Name:           prometheus-node-exporter-rapl
Version:        0.1.0
Release:        1%{?dist}
Summary:        RAPL energy counter access for node_exporter's rapl collector

License:        Apache-2.0
URL:            https://github.com/GSI-HPC/%{name}
Source0:        %{url}/archive/v%{version}/%{name}-%{version}.tar.gz
# The sysusers file is also in the tarball (packaging/systemd/), but %%pre
# has to read it at spec parse time, before %%prep unpacks anything, so it
# is a source of its own that the SRPM carries next to the tarball. A
# relative path into the tree would silently resolve against rpmbuild's
# working directory and leave an empty %%pre on rebuild elsewhere.
Source1:        %{name}.sysusers

BuildArch:      noarch

BuildRequires:  systemd-rpm-macros
%{?sysusers_requires_compat}
# The mechanism is a udev rule handing powercap zones to systemd; both are
# also what the scriptlets call (udevadm, systemd-update-helper).
Requires:       systemd
Requires:       systemd-udev

%description
Lets the rapl collector of Prometheus node_exporter read the RAPL energy
counters without making them world-readable and without granting the
exporter broad capabilities. Since Linux 5.10 (CVE-2020-8694) every
powercap zone's energy_uj is mode 0400 root, and node_exporter then
silently exports no node_rapl_* series. This package creates a dedicated
"rapl" group, ships a udev rule that has systemd apply group read access
to every zone's counter whenever the zone appears (boot, module reload),
and a drop-in that puts prometheus-node-exporter.service into that group.
It targets the EPEL node_exporter package, whose unit carries that name,
but does not depend on it: the drop-in is inert without the unit.

%prep
%autosetup

%build
# Nothing to build: configuration files only.

%install
install -D -m 0644 -vp %{SOURCE1} \
    %{buildroot}%{_sysusersdir}/%{name}.conf
install -D -m 0644 -vp packaging/udev/60-%{name}.rules \
    %{buildroot}%{_udevrulesdir}/60-%{name}.rules
install -D -m 0644 -vp packaging/systemd/%{name}@.service \
    %{buildroot}%{_unitdir}/%{name}@.service
install -D -m 0644 -vp packaging/systemd/%{exporter_unit}.d/rapl.conf \
    %{buildroot}%{_unitdir}/%{exporter_unit}.d/rapl.conf

# On Fedora, rpm creates the group from the sysusers.d file itself and the
# compat macro is defined empty, which would leave an empty %%pre; EL9 and
# EL10 still create the group through the generated scriptlet. The group
# has to exist before %%post asks systemd to chgrp counters to it.
%if 0%{?rhel}
%pre
%sysusers_create_compat %{SOURCE1}
%endif

%post
%udev_rules_update
# Zones that already exist saw their add event before the rule was
# installed. Replaying it makes systemd start one template instance per
# zone now. The explicit reload first: udevd picks up changed rule
# directories on its own, but rate-limited to once per three seconds,
# and the systemd package's file trigger reloads only at the end of the
# transaction, after this scriptlet. Without a running udev (container,
# chroot) there is nothing to apply to.
if [ -e /run/udev/control ]; then
    udevadm control --reload >/dev/null 2>&1 || :
    udevadm trigger --subsystem-match=powercap --action=add >/dev/null 2>&1 || :
fi
%{mark_exporter_restart}

%postun
%udev_rules_update
# On removal (not upgrade): drop the rule from the running udevd (the
# systemd package has no file trigger for removed rules), and restart the
# exporter the same way as on install so it drops the supplementary
# group. Counters that were already chgrp'd keep their mode until the
# next boot or module reload; README.md shows how to reset them.
if [ $1 -eq 0 ]; then
    if [ -e /run/udev/control ]; then
        udevadm control --reload >/dev/null 2>&1 || :
    fi
%{mark_exporter_restart}
fi

%files
%license LICENSE NOTICE
%doc README.md CHANGELOG.md
%{_sysusersdir}/%{name}.conf
%{_udevrulesdir}/60-%{name}.rules
%{_unitdir}/%{name}@.service
%dir %{_unitdir}/%{exporter_unit}.d
%{_unitdir}/%{exporter_unit}.d/rapl.conf

%changelog
* Mon Sep 07 2026 Dennis Klein <d.klein@gsi.de> - 0.1.0-1
- Initial package: rapl group, udev rule handing powercap zones to a systemd
  template unit that grants the group read access to energy_uj, and a
  SupplementaryGroups drop-in for prometheus-node-exporter.service
