#!/usr/bin/python
from setuptools import setup, find_packages

setup(
    name='virt-who-tui',
    version='0.1',
    description='A Text-based user interface for configuring virt-who.',
    author='Hao Chang Yu',
    author_email='hyu@redhat.com',
    license='GPLv2+',
    url='https://github.com/hao-yu/virt-who-tui.git',
    packages=find_packages(),
    entry_points={
        'console_scripts': [
            'virt-who-tui = virt_who_tui.__main__:main',
        ]
    },
)
