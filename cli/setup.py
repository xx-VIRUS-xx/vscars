from setuptools import setup, find_packages

setup(
    name="vscars",
    version="1.0.0",
    description="VSCARS CLI — connect your machine to the VSCARS platform",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "websockets>=12.0",
        "requests>=2.28",
    ],
    entry_points={
        "console_scripts": [
            "vscars=vscars.cli:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
