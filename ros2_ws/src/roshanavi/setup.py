import glob
import os

from setuptools import find_packages, setup

package_name = 'roshanavi'


def static_files():
    """Built web UI (web/ -> roshanavi/static, gitignored) shipped as package data."""
    root = os.path.join(package_name, 'static')
    files = []
    for current, _dirs, names in os.walk(root):
        rel = os.path.relpath(current, package_name)
        files += [os.path.join(rel, name) for name in names]
    return files

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    package_data={package_name: static_files()},
    include_package_data=True,
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob.glob('launch/*.launch.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='aoki',
    maintainer_email='yuya.aoki.0928@gmail.com',
    description='Topic visualization, dummy input injection and scenario checks for ROS 2',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'server = roshanavi.main:main',
            'dummy = roshanavi.dummy_node:main',
        ],
    },
)
