Name:           virt-who-tui
Version:        0.1
Release:        1%{?dist}
Summary:        A Text-based user interface for configuring virt-who
License:        GPLv2+
URL:            https://github.com/hao-yu/virt-who-tui.git
Source0:        %{name}-%{version}.tar.gz
BuildRoot:      %{_tmppath}/%{name}-%{version}-%{release}-root-%(%{__id_u} -n)
BuildArch:      noarch
BuildRequires:  python2-devel
BuildRequires:  python-setuptools
Requires:       python-setuptools
Requires:       virt-who
Requires:       python-urwid

%description
Virt-who TUI aims to simplify the complexity of settings up virt-who by guiding users step by step.

%prep
%setup -q

%build
%{__python2} setup.py build

%install
rm -rf $RPM_BUILD_ROOT
%{__python2} setup.py install --root %{buildroot}

%clean
rm -rf $RPM_BUILD_ROOT

%files
%defattr(-,root,root)
%doc README.md
%{_bindir}/virt-who-tui
%{python2_sitelib}/*


%changelog
