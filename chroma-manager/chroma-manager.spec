%{?systemd_requires}
BuildRequires: systemd

%{!?name: %global name chroma-manager}
%{?!version: %global version %(%{__python} -c "from scm_version import PACKAGE_VERSION; sys.stdout.write(PACKAGE_VERSION)")}
%{?!package_release: %global package_release 1}
%{?!python_sitelib: %global python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; import sys; sys.stdout.write(get_python_lib())")}

# The install directory for the manager
%{?!manager_root: %global manager_root /usr/share/chroma-manager}

Summary: The Intel Manager for Lustre Monitoring and Administration Interface
Name: %{name}
Version: %{version}
Release: %{package_release}%{?dist}
Source0: %{name}-%{version}.tar.gz
Source1: chroma-host-discover-init.sh
Source2: logrotate.cfg
Source3: chroma-config.1.gz
Source4: iml-corosync.service
Source5: iml-gunicorn.service
Source6: iml-http-agent.service
Source7: iml-job-scheduler.service
Source8: iml-lustre-audit.service
Source9: iml-manager.target
Source10: iml-plugin-runner.service
Source11: iml-power-control.service
Source12: iml-realtime.service
Source13: iml-settings-populator.service
Source14: iml-stats.service
Source15: iml-syslog.service
Source16: iml-view-server.service

License: MIT
Group: Development/Libraries
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-buildroot
Prefix: %{_prefix}
Vendor: Intel Corporation <iml@intel.com>
Url: http://lustre.intel.com/
BuildRequires: python-setuptools
BuildRequires: ed
Requires: python-setuptools
Requires: python-prettytable
Requires: python-dse
Requires: python2-jsonschema < 0.9.0
Requires: python-ordereddict
Requires: python-uuid
Requires: python-paramiko
Requires: python2-kombu >= 3.0.19
Requires: python-daemon
Requires: python-requests >= 2.6.0
Requires: python-networkx
Requires: python2-httpagentparser
Requires: python-gunicorn
Requires: pygobject2
Requires: postgresql-server
Requires: python-psycopg2
Requires: rabbitmq-server
Requires: ntp
Requires: Django >= 1.4, Django < 1.5
Requires: Django-south >= 0.7.4
Requires: django-tastypie = 0.9.16
Requires: django-picklefield
Requires: chroma-manager-cli = %{version}-%{release}
Requires: iml_sos_plugin
Requires: policycoreutils-python
Requires: python2-gevent >= 1.0.1
Requires: system-config-firewall-base
Requires: nodejs >= 1:6.9.4-2
Requires: iml-gui
Requires: iml-srcmap-reverse
Requires: iml-online-help
Requires: iml-device-scanner-aggregator
Requires: createrepo
Requires: python2-toolz
Conflicts: chroma-agent
Requires(post): selinux-policy-targeted
Obsoletes: httpd
Obsoletes: mod_proxy_wstunnel
Obsoletes: mod_wsgi
Obsoletes: mod_ssl
Obsoletes: nodejs-active-x-obfuscator
Obsoletes: nodejs-bunyan
Obsoletes: nodejs-commander
Obsoletes: nodejs-nan
Obsoletes: nodejs-primus
Obsoletes: nodejs-primus-emitter
Obsoletes: nodejs-primus-multiplex
Obsoletes: nodejs-request
Obsoletes: nodejs-socket.io
Obsoletes: nodejs-socket.io-client
Obsoletes: nodejs-ws
Obsoletes: nodejs-tinycolor
Obsoletes: nodejs-extendable
Obsoletes: nodejs-xmlhttprequest
Obsoletes: nodejs-dotty
Obsoletes: nodejs-tough-cookie
Obsoletes: nodejs-options
Obsoletes: nodejs-punycode
Obsoletes: nodejs-load
Obsoletes: nodejs-json-stringify-safe
Obsoletes: nodejs-lodash
Obsoletes: nodejs-moment
Obsoletes: nodejs-q
Obsoletes: nodejs-qs
Obsoletes: nodejs-node-uuid
Obsoletes: nodejs-mime
Obsoletes: nodejs-base64id
Obsoletes: nodejs-policyfile
Obsoletes: nodejs-uritemplate
Obsoletes: nodejs-forever-agent
Obsoletes: nodejs-uglify-js
Obsoletes: nodejs-di
Obsoletes: nodejs-mv
Obsoletes: nodejs-json-mask
Obsoletes: nodejs-zeparser
Obsoletes: django-celery

Requires: fence-agents
Requires: fence-agents-virsh
Requires: nginx >= 1:1.11.6

%description
This is the Intel Manager for Lustre Monitoring and Administration Interface

%package libs
Summary: Common libraries for Chroma Server
Group: System/Libraries
Requires: python2-iml-common1.4
%description libs
This package contains libraries for Chroma CLI and Chroma Server.

%package cli
Summary: Command-Line Interface for Chroma Server
Group: System/Utility
Requires: chroma-manager-libs = %{version}-%{release} python-argparse python-requests >= 2.6.0 python-tablib python-prettytable
%description cli
This package contains the Chroma CLI which can be used on a Chroma server
or on a separate node.

%package integration-tests
Summary: Intel Manager for Lustre Integration Tests
Group: Development/Tools
Requires: python-requests >= 2.6.0 python-nose python-nose-testconfig python-paramiko python-ordereddict python2-iml-common1.4
Requires: Django >= 1.4, Django < 1.5
%description integration-tests
This package contains the Intel Manager for Lustre integration tests and scripts and is intended
to be used by the Chroma test framework.

%package devel
Summary: Contains stripped .py files
Group: Development
Requires: %{name} = %{version}-%{release}
%description devel
This package contains the .py files stripped out of the production build.

%pre
for port in 80 443; do
    if lsof -n -i :$port -s TCP:LISTEN; then
        echo "To install, port $port cannot be bound. Do you have Apache or some other web server running?"
        exit 1
    fi
done

%prep
%setup -n %{name}-%{version}
echo -e "/^DEBUG =/s/= .*$/= False/\nwq" | ed settings.py 2>/dev/null

%build
%{__python} setup.py -q build
# workaround setuptools inanity for top-level datafiles
cp -a chroma-manager.py build/lib
cp -a storage_server.repo build/lib
cp -a chroma-manager.conf.template build/lib
cp -a mime.types build/lib
cp -a agent-bootstrap-script.template build/lib

%install
%{__python} setup.py -q install --skip-build --root=%{buildroot}
install -d -p $RPM_BUILD_ROOT%{manager_root}
mv $RPM_BUILD_ROOT/%{python_sitelib}/* $RPM_BUILD_ROOT%{manager_root}
# Do a little dance to get the egg-info in place
mv $RPM_BUILD_ROOT%{manager_root}/*.egg-info $RPM_BUILD_ROOT/%{python_sitelib}
mkdir -p $RPM_BUILD_ROOT/etc/{init,logrotate,nginx/conf}.d
touch $RPM_BUILD_ROOT/etc/nginx/conf.d/chroma-manager.conf
cp %{SOURCE1} $RPM_BUILD_ROOT/etc/init.d/chroma-host-discover
mkdir -p $RPM_BUILD_ROOT/usr/share/man/man1
install %{SOURCE3} $RPM_BUILD_ROOT/usr/share/man/man1
install -m 644 %{SOURCE2} $RPM_BUILD_ROOT/etc/logrotate.d/chroma-manager
mkdir -p $RPM_BUILD_ROOT%{_unitdir}/
install -m 644 %{SOURCE4} $RPM_BUILD_ROOT%{_unitdir}/
install -m 644 %{SOURCE5} $RPM_BUILD_ROOT%{_unitdir}/
install -m 644 %{SOURCE6} $RPM_BUILD_ROOT%{_unitdir}/
install -m 644 %{SOURCE7} $RPM_BUILD_ROOT%{_unitdir}/
install -m 644 %{SOURCE8} $RPM_BUILD_ROOT%{_unitdir}/
install -m 644 %{SOURCE9} $RPM_BUILD_ROOT%{_unitdir}/
install -m 644 %{SOURCE10} $RPM_BUILD_ROOT%{_unitdir}/
install -m 644 %{SOURCE11} $RPM_BUILD_ROOT%{_unitdir}/
install -m 644 %{SOURCE12} $RPM_BUILD_ROOT%{_unitdir}/
install -m 644 %{SOURCE13} $RPM_BUILD_ROOT%{_unitdir}/
install -m 644 %{SOURCE14} $RPM_BUILD_ROOT%{_unitdir}/
install -m 644 %{SOURCE15} $RPM_BUILD_ROOT%{_unitdir}/
install -m 644 %{SOURCE16} $RPM_BUILD_ROOT%{_unitdir}/

# only include modules in the main package
for manager_file in $(find -L $RPM_BUILD_ROOT%{manager_root}/ -name "*.py"); do
    install_file=${manager_file/$RPM_BUILD_ROOT\///}
    echo "${install_file%.py*}.py*" >> manager.files
done

# only include modules in the cli package
for cli_file in $(find -L $RPM_BUILD_ROOT%{manager_root}/chroma_cli/ -name "*.py"); do
    install_file=${cli_file/$RPM_BUILD_ROOT\///}
    echo "${install_file%.py*}.py*" >> cli.files
done

# This is fugly, but it's cleaner than moving things around to get our
# modules in the standard path.
entry_scripts="/usr/bin/chroma-config /usr/bin/chroma"
for script in $entry_scripts; do
  ed $RPM_BUILD_ROOT$script <<EOF
/import load_entry_point/ a
sys.path.insert(0, "%{manager_root}")
.
w
q
EOF
done

%clean
rm -rf $RPM_BUILD_ROOT

%post
%{__python} $RPM_BUILD_ROOT%{manager_root}/scripts/production_nginx.py \
    $RPM_BUILD_ROOT%{manager_root}/chroma-manager.conf.template > /etc/nginx/conf.d/chroma-manager.conf

# Create chroma-config MAN Page
makewhatis

# set worker_processes to auto
sed -i '/^worker_processes /s/^/#/' /etc/nginx/nginx.conf
sed -i '1 i\worker_processes auto;' /etc/nginx/nginx.conf

# Start nginx which should present a helpful setup
# page if the user visits it before configuring Chroma fully
systemctl enable nginx

# Pre-create log files to set permissions
mkdir -p /var/log/chroma
chown -R nginx:nginx /var/log/chroma

# Only issue SELinux related commands if SELinux is enabled
sestatus| grep enabled &> /dev/null
if [ $(echo $?) == '0' ]; then
    echo "SELinux is enabled!"

    # This is required for opening connections between
    # nginx and rabbitmq-server
    setsebool -P httpd_can_network_connect 1 2>/dev/null

    # This is required because of bad behaviour in python's 'uuid'
    # module (see HYD-1475)
    setsebool -P httpd_tmp_exec 1 2>/dev/null

    # This is required for nginx to serve HTTP_API_PORT
    semanage port -a -t http_port_t -p tcp 8001
else
    echo "SELinux is disabled!"
fi


if [ $(systemctl is-active firewalld) == "active" ]; then
    for port in 80 443; do
        firewall-cmd --permanent --add-port=$port/tcp
        firewall-cmd --add-port=$port/tcp
    done
fi


echo "Thank you for installing Chroma.  To complete your installation, please"
echo "run \"chroma-config setup\""

%preun
%systemd_preun iml-manager.target
%systemd_preun iml-corosync.service
%systemd_preun iml-gunicorn.service
%systemd_preun iml-http-agent.service
%systemd_preun iml-job-scheduler.service
%systemd_preun iml-lustre-audit.service
%systemd_preun iml-plugin-runner.service
%systemd_preun iml-power-control.service
%systemd_preun iml-realtime.service
%systemd_preun iml-settings-populator.service
%systemd_preun iml-stats.service
%systemd_preun iml-syslog.service
%systemd_preun iml-view-server.service

if [ $1 -lt 1 ]; then
    #reset worker processes
    sed -i '/^worker_processes auto;/d' /etc/nginx/nginx.conf
    sed -i '/^#worker_processes /s/^#//' /etc/nginx/nginx.conf
fi

%postun
# Remove chroma-config MAN Page
rm -rf $RPM_BUILD_ROOT/usr/share/man/man1/%{SOURCE3}.gz

if [ $1 -lt 1 ]; then
    for port in 80 443; do
        firewall-cmd --permanent --remove-port=$port/tcp
        firewall-cmd --remove-port=$port/tcp
    done
    firewall-cmd --permanent --remove-port=123/udp
    firewall-cmd --remove-port=123/udp

    # clean out /var/lib/chroma
    if [ -d /var/lib/chroma ]; then
        rm -rf /var/lib/chroma
    fi
fi

%files -f manager.files
%defattr(-,root,root)
%{_bindir}/chroma-host-discover
%attr(0700,root,root)%{_bindir}/chroma-config
%dir %attr(0755,nginx,nginx)%{manager_root}
/etc/nginx/conf.d/chroma-manager.conf
%attr(0755,root,root)/etc/init.d/chroma-host-discover
%attr(0755,root,root)/usr/share/man/man1/chroma-config.1.gz
%attr(0644,root,root)/etc/logrotate.d/chroma-manager
%attr(0644,root,root)%{_unitdir}/iml-corosync.service
%attr(0644,root,root)%{_unitdir}/iml-gunicorn.service
%attr(0644,root,root)%{_unitdir}/iml-http-agent.service
%attr(0644,root,root)%{_unitdir}/iml-job-scheduler.service
%attr(0644,root,root)%{_unitdir}/iml-lustre-audit.service
%attr(0644,root,root)%{_unitdir}/iml-manager.target
%attr(0644,root,root)%{_unitdir}/iml-plugin-runner.service
%attr(0644,root,root)%{_unitdir}/iml-power-control.service
%attr(0644,root,root)%{_unitdir}/iml-realtime.service
%attr(0644,root,root)%{_unitdir}/iml-settings-populator.service
%attr(0644,root,root)%{_unitdir}/iml-stats.service
%attr(0644,root,root)%{_unitdir}/iml-syslog.service
%attr(0644,root,root)%{_unitdir}/iml-view-server.service
%attr(0755,root,root)%{manager_root}/manage.py
%{manager_root}/agent-bootstrap-script.template
%{manager_root}/chroma-manager.py
%{manager_root}/chroma-manager.conf.template
%{manager_root}/mime.types
%{manager_root}/ui-modules/node_modules/*
%{manager_root}/chroma_help/*
%{manager_root}/chroma_core/fixtures/*
%{manager_root}/polymorphic/COPYING
%config(noreplace) %{manager_root}/storage_server.repo
# Stuff below goes into the -cli/-lib packages
%exclude %{manager_root}/chroma_cli
%exclude %{python_sitelib}/*.egg-info/
# will go into the -tests packages
%exclude %{manager_root}/example_storage_plugin_package
%exclude %{manager_root}/tests
%doc licenses/*

%files libs
%{python_sitelib}/*.egg-info/*

%files -f cli.files cli
%defattr(-,root,root)
%{_bindir}/chroma

%files integration-tests
%defattr(-,root,root)
%{manager_root}/tests/__init__.py
%{manager_root}/tests/utils/*
%{manager_root}/tests/sample_data/*
%{manager_root}/tests/plugins/*
%{manager_root}/tests/integration/*
%{manager_root}/tests/integration/core/clear_ha_el?.sh
%attr(0755,root,root)%{manager_root}/tests/integration/run_tests
