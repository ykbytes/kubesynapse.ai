"""kubesynapse Python SDK setup."""

from pathlib import Path

from setuptools import find_packages, setup

setup(
    name="kubesynapse-sdk",
    version="0.1.0",
    description="Python SDK for the kubesynapse Kubernetes AI platform",
    long_description=Path("README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    author="kubesynapse Team",
    author_email="team@kubesynapse.ai",
    url="https://github.com/ykbytes/kubesynapse.ai",
    packages=find_packages(exclude=["tests*"]),
    python_requires=">=3.10",
    install_requires=[
        "httpx>=0.27.0",
        "pydantic>=2.0.0",
    ],
    extras_require={
        "sync": ["nest-asyncio>=1.5.0"],
        "dev": [
            "pytest>=8.0.0",
            "pytest-asyncio>=0.23.0",
            "pytest-cov>=4.0.0",
            "ruff>=0.4.0",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: System :: Systems Administration",
    ],
    keywords="kubernetes ai agents llm sdk kubesynapse",
)
