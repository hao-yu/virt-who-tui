import re
import sys
import tempfile
import subprocess
import socket
import platform
import logging
import StringIO
import rhsm.config as rhsm_config
from binascii import hexlify
from virtwho.virt import Virt
from virtwho.virt.vdsm import Vdsm
from virtwho.virt.virt import VirtError
from virtwho.config import Config, InvalidOption
from virtwho.password import Password
from ConfigParser import SafeConfigParser
from multiprocessing import Event, Queue
from virt_who_tui.sm_manager import RhsmManager, Sat5Manager

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
        "Red Hat Customer Portal": "rhsm",
        "Subscription Asset Manager": "rhsm",
        "Red Hat Satellite 6": "rhsm",
        "Red Hat Satellite 5": "sat",
    }

    SM = [
        "Red Hat Customer Portal",
        "Red Hat Satellite 6",
        "Subscription Asset Manager",
        "Red Hat Satellite 5",
    ]

    HYPERVISOR_IDS = ["uuid", "hostname", "hwuuid"]

    VIRT_FIELDS  = ["type", "server", "username", "password", "env", "owner", "encrypted_password", "hypervisor_id"]
    SAT_FIELDS   = ["sat_server", "sat_username", "sat_password", "sat_encrypted_password"]
    RHSM_FIELDS  = [
        "rhsm_hostname",
        "rhsm_prefix",
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

    PORTAL_URL = "subscription.rhsm.redhat.com"
    PORTAL_PREFIX = "/subscription"
    SAT6_PREFIX = "/rhsm"
    SAM_PREFIX = "/sam/api"
    CONFIG_DIR = "/etc/virt-who.d"
    LOG_FILE = "/var/log/virt-who-tui.log"

    def __init__(self):
        self.config_name = None
        self.smType = None
        self.smType_label = None
        self.encrypt_pass = True
        self.sat_encrypt_pass = True
        self.rhsm_encrypt_pass = True
        self._rhsm_config = rhsm_config.initConfig(rhsm_config.DEFAULT_CONFIG_PATH)

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

    def host_is_registered(self):
        return self.host_is_registered_to_portal() or \
            self.host_is_registered_to_satellite6() or \
            self.host_is_registered_to_sam()

    def host_is_registered_to_portal(self):
        rhsm_host = self._rhsm_config.get('server', 'hostname')
        if rhsm_host == self.PORTAL_URL:
            return True
        return False

    def host_is_registered_to_satellite6(self):
        prefix = self._rhsm_config.get('server', 'prefix')
        if prefix == self.SAT6_PREFIX:
            return True
        return False

    def host_is_registered_to_sam(self):
        prefix = self._rhsm_config.get('server', 'prefix')
        if prefix == self.SAM_PREFIX:
            return True
        return False

    def clear_rhsm_config(self):
        for field in self.RHSM_FIELDS:
            setattr(self, field, None)

    def set_rhsm_prefix(self):
        if self.rhsm_hostname and not self.rhsm_prefix:
            if self.smType_label == "Red Hat Satellite 6":
                self.rhsm_prefix = self.SAT6_PREFIX
            elif self.smType_label == "Red Hat Customer Portal":
                self.rhsm_prefix = self.PORTAL_PREFIX
            elif self.smType_label == "Subscription Asset Manager":
                self.rhsm_prefix = self.SAM_PREFIX

    def humanize_type(self):
        for k, v in self.VIRT_MAP.iteritems():
            if v == self.type:
                return k
        raise InvalidOption("'%s' is not a supported hypervisor backend." % self.type)

    def validate_integer(self, field):
        val = getattr(self, field)
        if val and not val.isdigit():
            raise InvalidOption("%s must be an integer." % field.replace("rhsm_", "").replace("sat_", "").title())

    def validate_config_name(self):
        if not self.config_name:
            raise InvalidOption("Please enter a name for your configuration")
        elif self.config_name.lower() == "default":
            raise InvalidOption("'default' is not a valid configuration name. Please enter other name.")

    def validate_virt_type(self):
        if not self.type:
            raise InvalidOption("Please specify a hypervisor backend.")
        elif self.type not in self.SUPPORTED_VIRT:
            raise InvalidOption("'%s' is not a supported hypervisor backend." % self.type)

    def validate_sm_type(self):
        if not self.smType:
            raise InvalidOption("Please specify where the host/guest associations should be reported.")

    def validate_rhsm_config(self):
        if self.smType != "rhsm":
            return

        for field in ["rhsm_hostname", "rhsm_username", "rhsm_password"]:
            if not getattr(self, field):
                raise InvalidOption("%s is required." % field.replace("rhsm_", "").title())

        for field in ["rhsm_port", "rhsm_proxy_port"]:
            self.validate_integer(field)

    def validate_satellite_config(self):
        if self.smType != "sat":
            return

        for field in ["sat_server", "sat_username", "sat_password"]:
            if not getattr(self, field):
                raise InvalidOption("%s is required." % field.replace("sat_", "").title())

    def validate_virt_config(self):
        self.validate_virt_type()
        if not self.server and self.type not in ['libvirt', 'vdsm', 'fake']:
            raise InvalidOption("Server is required.")

        if ((self.smType == 'rhsm') and (
                (self.type in ('esx', 'rhevm', 'hyperv', 'xen')) or
                (self.type == 'libvirt' and self.server))):
            if not self.env:
                raise InvalidOption("Environment is required.")
            elif not self.owner:
                raise InvalidOption("Organization is required.")

        if self.type == 'libvirt':
            if self.server:
                if ('ssh://' in self.server or '://' not in self.server) and self.password:
                    raise InvalidOption("Password authentication doesn't work with ssh transport on libvirt backend, please copy your public ssh key to the remote machine.")

    def get_sm_manager(self, config):
        return RhsmManager(self.logger, config) if self.smType == "rhsm" else Sat5Manager(self.logger, config)

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
            # Prevent any warning messages to be printed out to the screen. For example:
            # certificate warning. Print them to the log instead.
            out = StringIO.StringIO()
            orig_stdout = sys.stdout
            orig_stderr = sys.stderr
            sys.stdout = out
            sys.stderr = out
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
            self.logger.info(out.getvalue())
            sys.stdout = orig_stdout
            sys.stderr = orig_stderr
            virt.extra_errors.close()
            virt.extra_errors = None

        return errors

    def _encrypt_password(self, field, password, encrypt_password=True):
        # Make sure the encrypt password field is resetted because we don't want to
        # store old encrypted password if the password has changed.
        setattr(self, field, None)

        # Encrypt the password only if the user want to do so
        if not password or not encrypt_password:
            return

        setattr(self, field, hexlify(Password.encrypt(password)))
        getattr(self, field)

    def encrypt_passwords(self):
        self._encrypt_password("sat_encrypted_password", self.sat_password, self.sat_encrypt_pass)
        self._encrypt_password("rhsm_encrypted_password", self.rhsm_password, self.rhsm_encrypt_pass)
        self._encrypt_password("encrypted_password", self.password, self.encrypt_pass)

    def filename(self):
        filename = ".".join([self.config_name.lower().replace(" ", "_"), "conf"])
        return "/".join([self.CONFIG_DIR, filename])

    def to_ini(self):
        config = self.get_config(True)
        with open(self.filename(), 'wb') as fh:
            config.write(fh)

    def get_config(self, file=False):
        config = None
        parser = SafeConfigParser()
        parser.add_section(self.config_name)

        self.set_rhsm_prefix()

        for field in self.all_fields:
            # Don't want to print clear text password in the file
            if file:
                if field == "sat_password" and self.sat_encrypt_pass or \
                    field == "rhsm_password" and self.rhsm_encrypt_pass or \
                    field == "rhsm_proxy_password" and self.rhsm_encrypt_pass or \
                    field == "password" and self.encrypt_pass:
                    continue

            # Based on the validation codes in virt-who:
            # - Environment is not used in non-remote libvirt connection
            # - Owner is not used in non-remote libvirt connection
            # Thus, force owner and env to None
            if self.type == 'libvirt' and not self.server and field in ["owner", "env"]:
                continue

            value = getattr(self, field)
            if value:
                parser.set(self.config_name, field, value)

        for section in parser.sections():
            config = Config.fromParser(section, parser)

        if file:
            return parser
        else:
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
