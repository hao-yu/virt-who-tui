import re
import sys
import tempfile
import subprocess
import socket
import platform
import logging
from requests.exceptions import ConnectionError
from virtwho.virt import Virt
from virtwho.virt.vdsm import Vdsm
from virtwho.virt.virt import VirtError
from virtwho.config import Config, InvalidOption
from virtwho.password import Password
from virtwho.manager import Manager, ManagerError, ManagerFatalError
from ConfigParser import SafeConfigParser
from multiprocessing import Event, Queue


class VirtConfig(object):
    SUPPORTED_VIRT = ('esx', 'rhevm', 'hyperv', 'xen', 'libvirt', 'vdsm')

    VIRT_MAP = {
        "ESX": "esx",
        "Hyper-V": "hyperv",
        "Libvirt": "libvirt",
        "RHEV-M": "rhevm",
        "Vdsm": "vdsm",
        "XEN": "xen",
    }

    SM_MAP = {
        "Red Hat Subscription Manager (RHSM)": "rhsm",
        "Satellite 5": "sat",
    }

    HYPERVISOR_IDS = ["uuid", "hostname", "hwuuid"]

    VIRT_FIELDS  = ["type", "server", "username", "password", "env", "owner", "encrypted_password", "hypervisor_id"]
    SAT_FIELDS   = ["sat_server", "sat_username", "sat_password", "sat_encrypted_password"]
    RHSM_FIELDS  = [
        "rhsm_hostname",
        "rhsm_port",
        "rhsm_username",
        "rhsm_password",
        "rhsm_encrypted_password",
        "rhsm_proxy_hostname",
        "rhsm_proxy_port",
        "rhsm_proxy_user",
        "rhsm_proxy_password",
        "rhsm_encrypted_proxy_password",
    ]

    CONFIG_DIR = "/etc/virt-who.d"
    LOG_FILE = "/var/log/virt-who-tui.log"

    def __init__(self):
        self.config_name = None
        self.smType = None
        self.smType_label = None
        self.encrypt_pass = True
        self.sat_encrypt_pass = True
        self.rhsm_encrypt_pass = True

        self.all_fields = self.VIRT_FIELDS + self.SAT_FIELDS + self.RHSM_FIELDS
        # pre-populate all the fields to empty string
        for field in self.all_fields:
            setattr(self, field, None)

        self.logger = logging.getLogger('virt-who-tui')
        hdlr = logging.FileHandler(self.LOG_FILE)
        self.logger.addHandler(hdlr)
        self.logger.setLevel(logging.DEBUG)

    def set_type_by_label(self, label):
        self.type = self.VIRT_MAP[label]

    def set_sm_type_by_label(self, label):
        self.smType = self.SM_MAP[label]

    def humanize_type(self):
        for k, v in self.VIRT_MAP.iteritems():
            if v == self.type:
                return k
        raise InvalidOption("'%s' is not a supported virtualization backend." % self.type)

    def validate_config_name(self):
        if not self.config_name:
            raise InvalidOption("Please enter a name for your configuration")
        elif self.config_name.lower() == "default":
            raise InvalidOption("'default' is not a valid configuration name. Please enter other name.")

    def validate_virt_type(self):
        if not self.type:
            raise InvalidOption("Please specify a virtualization backend.")
        elif self.type not in self.SUPPORTED_VIRT:
            raise InvalidOption("'%s' is not a supported virtualization backend." % self.type)

    def validate_sm_type(self):
        if not self.smType:
            raise InvalidOption("Please specify where the host/guest associations should be reported.")

    def validate_satellite_config(self):
        if self.smType != "sat":
            return
        elif not self.sat_server:
            raise InvalidOption("Please specify URL of Satellite 5.")
        elif not self.sat_username or not self.sat_password:
            raise InvalidOption("Please specify username and password of Satellite 5.")

    def validate_virt_config(self):
        self.validate_virt_type()
        if not self.server and self.type not in ['libvirt', 'vdsm', 'fake']:
            raise InvalidOption("Please specify URL of virtualization backend server.")

        if ((self.smType == 'rhsm') and (
                (self.type in ('esx', 'rhevm', 'hyperv', 'xen')) or
                (self.type == 'libvirt' and self.server))):
            if not self.env:
                raise InvalidOption("Please specify environment that '%s' belongs to." % self.type)
            elif not self.owner:
                raise InvalidOption("Please specify an organization.")

        if self.type == 'libvirt':
            if self.server:
                if ('ssh://' in self.server or '://' not in self.server) and self.password:
                    raise InvalidOption("Password authentication doesn't work with ssh transport on libvirt backend, please copy your public ssh key to the remote machine.")
            elif self.env:
                raise InvalidOption("Environment is not used in non-remote libvirt connection.")
            elif self.owner:
                raise InvalidOption("Owner is not used in non-remote libvirt connection.")

    def check_sm_connection(self, config):
        errors = []
        try:
            sm_manager = Manager.fromOptions(self.logger, config, config)
            sm_manager._connect(config)
            if self.smType == "sat":
                if hasattr(sm_manager, 'server_xmlrpc'):
                    server = 'server_xmlrpc'
                else:
                    server = 'server'
                session = getattr(sm_manager, server).auth.login(config.sat_username, config.sat_password)
                getattr(sm_manager, server).auth.logout(session)
        except Exception as e:
            if issubclass(e.__class__, ManagerError) or issubclass(e.__class__, ManagerFatalError) or isinstance(e, ConnectionError):
                errors.append(repr(e))
            else:
                raise e

        return errors

    def check_virt_connection(self, config):
        queue  = Queue()
        event  = Event()
        errors = []
        virt = Virt.fromConfig(self.logger, config)
        setattr(virt, 'extra_errors', tempfile.NamedTemporaryFile(prefix='vit-who-error'))

        # vdsm subprocess will output to stdout, so redirect it to a tempfile
        def _getLocalVdsName(tsPath):
            p = subprocess.Popen([
                '/usr/bin/openssl', 'x509', '-noout', '-subject', '-in',
                '%s/certs/vdsmcert.pem' % tsPath], stderr=virt.extra_errors, stdout=virt.extra_errors, close_fds=True)
            out, err = p.communicate()
            if p.returncode != 0:
                return '0'
            return re.search('/CN=([^/$\n]+)', out).group(1)

        if isinstance(virt, Vdsm):
            virt._getLocalVdsName = _getLocalVdsName

        try:
            # Perform a one shot report request to test the connection
            virt.start_sync(queue, event, None, True)
        except (VirtError, socket.error) as e:
            errors.append(repr(e))
            virt.extra_errors.seek(0)
            more_errors = virt.extra_errors.read()
            if more_errors:
                errors.append(more_errors)

            for error in errors:
                if re.search(r'Connection refused', error, re.I):
                    errors = ["Please make sure the server port is open."] + errors
                    break
        finally:
            virt.extra_errors.close()
            virt.extra_errors = None

        return errors

    def encrypt_password(self, field, password):
        if not password:
            return None
        field = Password.encrypt(password)
        return field

    def filename(self):
        filename = ".".join([self.config_name.lower().replace(" ", "_"), "conf"])
        return "/".join([self.CONFIG_DIR, filename])

    def parse_config(self):
        parser = SafeConfigParser()
        parser.add_section(self.config_name)

        if self.sat_encrypt_pass:
            self.encrypt_password(self.sat_encrypted_password, self.sat_password)

        if self.rhsm_encrypt_pass:
            self.encrypt_password(self.rhsm_encrypted_password, self.rhsm_password)
            self.encrypt_password(self.rhsm_encrypted_proxy_password, self.rhsm_proxy_password)

        if self.encrypt_pass:
            self.encrypt_password(self.encrypted_password, self.password)

        for field in self.all_fields :
            if field == "sat_password" and self.sat_encrypt_pass or \
                field == "rhsm_password" and self.rhsm_encrypt_pass or \
                field == "rhsm_proxy_password" and self.rhsm_encrypt_pass or \
                field == "password" and self.encrypt_pass:
                continue

            value = getattr(self, field)
            if value:
                parser.set(self.config_name, field, value)

        return parser

    def to_ini(self):
        with open(self.filename(), 'wb') as fh:
            self.parse_config().write(fh)

    def get_config(self):
        config = None
        parser = self.parse_config()
        for section in parser.sections():
            config = Config.fromParser(section, parser)
        return config

    def is_rhel6_or_below(self):
        dist = platform.dist()
        match = re.match("^([^.]+)", dist[1])
        if dist[0] in ["redhat", "centos"] and match and int(match.group(0)) < 7:
            return True
        return False

    def run_command(self, cmd):
        fh = tempfile.NamedTemporaryFile(prefix='vit-who-error')
        p = subprocess.Popen(cmd, stderr=fh, stdout=fh, close_fds=True)
        out, err = p.communicate()
        error = None
        if p.returncode != 0:
            fh.seek(0)
            error = fh.read()
        return error

    def start_virt_who(self):
        cmd = ["/bin/systemctl", "restart", "virt-who"]
        if self.is_rhel6_or_below():
            cmd = ["/usr/sbin/service", "virt-who", "restart"]
        return self.run_command(cmd)

    def enable_virt_who(self):
        cmd = ["/bin/systemctl", "enable", "virt-who"]
        if self.is_rhel6_or_below():
            cmd = ["/usr/sbin/chkconfig", "virt-who", "on"]
        return self.run_command(cmd)
