import logging
import time
from datetime import datetime
from typing import Dict

from __version__ import __version__
from github import Github
from pydantic import BaseModel
from snyk import SnykClient  # type: ignore


logger = logging.getLogger(__name__)


class V3Projects(BaseModel):
    pass


class V3Targets(BaseModel):
    pass


class V3Target(BaseModel):
    pass


def cleanup_path(path: str):
    if path[0] != "/":
        return f"/{path}"
    else:
        return path


def cleanup_url(path: str):
    if "https://app.snyk.io/api/v1/" in path:
        path = path.replace("https://app.snyk.io/api/v1/", "")

    return path


def ensure_version(path: str, version: str) -> str:
    query = path.split("/")[-1]

    if "version" in query.lower():
        return path
    else:
        if "?" in query and query[-1] != "&" and query[-1] != "?":
            logger.debug("ensure_version Case 1")
            return f"{path}&version={version}"
        elif query[-1] == "&" or query[-1] == "?":
            logger.debug("ensure_version Case 2")
            return f"{path}version={version}"
        else:
            logger.debug("ensure_version Case 3")
            return f"{path}?version={version}"


def v1_get_pages(
    path: str, v1_client: SnykClient, list_name: str, per_page_key: str = "perPage", per_page_val: int = 100
) -> Dict:
    """
    For paged resources on the v1 api that use links headers
    """

    if path[-1] != "?" and "&" not in path:
        path = f"{path}?"

    path = f"{path}&{per_page_key}={per_page_val}"

    resp = v1_client.get(path)

    page = resp.json()

    return_page = page

    while "next" in resp.links:
        url = resp.links["next"]["url"]

        url = cleanup_url(url)

        resp = v1_client.get(url)

        page = resp.json()

        return_page[list_name].extend(page[list_name])

    return return_page
