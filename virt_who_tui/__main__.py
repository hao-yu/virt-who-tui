#!/usr/bin/python

import sys
import os

from virt_who_tui.page import WelcomePage
from virt_who_tui.virt_config import VirtConfig
from virt_who_tui.display import TuiContainerDisplay

def main():
    if os.geteuid() != 0:
        print >>sys.stderr, "This application requires root permission. Please run it as root."
        sys.exit(1)

    virt_config = VirtConfig()
    container = TuiContainerDisplay(virt_config.logger, 80, 80)
    WelcomePage(container, input_data=virt_config).render()
    exitcode, error = container.run()

    if error:
        sys.stderr.write(error + "\n")

    sys.exit(exitcode)

if __name__=="__main__":
    main()
