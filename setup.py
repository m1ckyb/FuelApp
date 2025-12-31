"""
Setup script for NSW Fuel Station App.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

# Read requirements
requirements = []
with open('requirements.txt') as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name='nsw-fuel-app',
    version='1.0.0',
    author='NSW Fuel Station App Contributors',
    description='A standalone app to monitor NSW fuel prices and store them in InfluxDB',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/m1ckyb/FuelApp',
    packages=find_packages(),
    install_requires=requirements,
    entry_points={
        'console_scripts': [
            'nsw-fuel-app=app.main:main',
        ],
    },
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
    ],
    python_requires='>=3.8',
)
