from setuptools import setup, find_packages
import sys

# ~~Setup:Core~~

setup(
    name = 'testbook',
    version = '0.0.1',
    packages = find_packages(),
    install_requires = [],
    url = 'http://cottagelabs.com/',
    author = 'Cottage Labs',
    author_email = 'richard@cottagelabs.com',
    description = 'For managing functional tests',
    license = 'Apache2',
    classifiers = [],
    entry_points = {
        'console_scripts': [
            'testbook=testbook.cli:main',
        ],
    }
)