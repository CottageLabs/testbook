from setuptools import setup, find_packages

# ~~Setup:Core~~
setup(
    name='testbook',
    version='0.0.3',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "jinja2<3.1.0",
        "pyyaml==5.4.1",
        "click>=8.0.0",
        "MarkupSafe==2.0.1"
    ],
    url='https://cottagelabs.com/',
    author='Cottage Labs',
    author_email='richard@cottagelabs.com',
    description='For managing functional tests',
    license='Apache2',
    classifiers=[],
    entry_points={
        'console_scripts': [
            'testbook=testbook.cli:main',
        ],
    }
)
