import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'ping1d_driver'

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
    description='ROS 2 driver node for Blue Robotics Ping / Ping2 echosounders (Ping1D protocol, serial/UDP, with simulator).',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'ping1d_node = ping1d_driver.ping1d_node:main',
        ],
    },
)
