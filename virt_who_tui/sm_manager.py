import xmlrpclib
from contextlib import contextmanager
from requests.exceptions import ConnectionError
from virtwho.manager import ManagerError, ManagerFatalError
from virtwho.manager import Manager

class SmManager(object):
    """
    This is just a thin wrapper for virtwho.manager class
    """

    def __init__(self, logger, config):
        self.logger = logger
        self.config = config
        self.sm_manager = Manager.fromOptions(logger, config, config)
        self.connection = None

    def connect(self):
        self.sm_manager._connect(self.config)

    def logout(self):
        pass

    @contextmanager
    def sm_error_handler(self, errors):
        try:
            yield
        except Exception as e:
            if issubclass(e.__class__, ManagerError) or \
                issubclass(e.__class__, ManagerFatalError) or \
                isinstance(e, ConnectionError) or \
                xmlrpclib.ProtocolError or \
                xmlrpclib.Fault:

                errors.append(repr(e))
            elif isinstance(e, socket.error):
                errors.append(repr(e))
                errors.append("Please make sure the server port is open.")
            else:
                raise e

class RhsmManager(SmManager):
    def connect(self):
        super(RhsmManager, self).connect()
        self.connection = self.sm_manager.connection

class Sat5Manager(SmManager):
    def connect(self):
        super(Sat5Manager, self).connect()
        if hasattr(self.sm_manager, 'server_xmlrpc'):
            self.connection = self.sm_manager.server_xmlrpc
        else:
            self.connection = self.sm_manager.server
        username = self.config.sat_username
        password = self.config.sat_password
        self.session = self.connection.auth.login(username, password)

    def logout(self):
        if self.session:
            self.connection.auth.logout(self.session)
