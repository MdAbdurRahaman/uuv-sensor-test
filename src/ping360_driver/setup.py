import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'ping360_driver'

setup(
    name=package_name,
    version='1.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml', 'README.md']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='maintainer',
    maintainer_email='you@example.com',
    description='ROS 2 driver node for the Blue Robotics Ping360 scanning sonar (serial/UDP, with simulator).',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'ping360_node = ping360_driver.ping360_node:main',
        ],
    },
)
