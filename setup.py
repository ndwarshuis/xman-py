from setuptools import setup, find_packages

setup(
    name="xman",
    version="0.0.1",
    description="contextual xcape manager",
    packages=find_packages(),
    python_requires=">=3.5",
    install_requires=["systemd-python>=234", "python-xlib>=0.25"],
    entry_points={"console_scripts": ["xman=xman.main:main"]},
)
