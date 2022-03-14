import logging
import urllib.parse

import requests
import time
from retry.api import retry_call

from datetime import datetime

from github import Github

from typing import Optional, List, Optional, Dict

from pydantic import BaseModel

from snyk import SnykClient

from time import sleep

from __version__ import __version__

logger = logging.getLogger(__name__)


class RateLimit:
    def __init__(self, gh: Github, pages):
        self.core_limit = gh.get_rate_limit().core.limit
        self.search_limit = gh.get_rate_limit().search.limit
        # we want to know how many calls had been made before we created this object
        # calling this a tare
        self.core_tare = gh.get_rate_limit().core.limit - gh.get_rate_limit().core.remaining
        self.search_tare = gh.get_rate_limit().search.limit - gh.get_rate_limit().search.remaining
        self.gh = gh
        self.core_calls = [0]
        self.search_calls = [0]
        self.repo_count = 0
        self.pages = pages

    def update(self, display: bool = False):
        core_call = self.core_limit - self.core_tare - self.gh.get_rate_limit().core.remaining
        search_call = self.search_limit - self.search_tare - self.gh.get_rate_limit().search.remaining

        self.core_calls.append(core_call)
        self.search_calls.append(search_call)

        if display is True:
            core_diff = self.core_calls[-1] - self.core_calls[-2]
            search_diff = self.search_calls[-1] - self.search_calls[-2]
            print(f"GH RateLimit: Core Calls = {core_diff}")
            print(f"GH RateLimit: Search Calls = {search_diff}")

    def add_calls(self, repo_total: int):
        self.repo_count = repo_total

    def check(self, kind="core"):

        if kind == "core":
            rl = self.gh.get_rate_limit().core
        elif kind == "search":
            rl = self.gh.get_rate_limit().search

        expiration = rl.reset

        now = datetime.utcnow()

        reset_countdown = expiration - now

        remaining = rl.remaining

        needed_requests = (self.repo_count // self.pages) + 1

        if needed_requests > remaining:
            print(f"\n{needed_requests} requests needed and {remaining} remaining")
            print(f"Sleeping: {reset_countdown.seconds} seconds")
            time.sleep(int(reset_countdown.seconds))

    def total(self):
        print(f"GH RateLimit: Total Core Calls = {self.core_calls[-1]}")
        print(f"GH RateLimit: Total Search Calls = {self.search_calls[-1]}")


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
