import poetry_version  # type: ignore
from importlib_metadata import version  # type: ignore

__title__ = "snyk-watcher"
__description__ = "A tool to keep a map between a GitHub Org and a Snyk Group."
__license__ = "MIT"
try:
    __version__ = version("snyk-watcher")
except:
    __version__ = poetry_version.extract(source_file=__file__)
