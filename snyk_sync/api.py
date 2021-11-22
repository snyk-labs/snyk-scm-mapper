import json
import logging
from uuid import RESERVED_FUTURE, UUID
from tomlkit.items import DateTime
import yaml

import requests
from retry.api import retry_call

from pathlib import Path
from pprint import pprint
from dataclasses import dataclass
from datetime import datetime

from github import Github, Repository

from typing import Optional, List, Optional, TypedDict, Tuple, Dict

from pydantic import BaseModel, FilePath, ValidationError, root_validator, UUID4, Field, create_model

from snyk import SnykClient

from __version__ import __version__

logger = logging.getLogger(__name__)


class RateLimit:
    def __init__(self, gh: Github):
        self.core_limit = gh.get_rate_limit().core.limit
        self.search_limit = gh.get_rate_limit().search.limit
        # we want to know how many calls had been made before we created this object
        # calling this a tare
        self.core_tare = gh.get_rate_limit().core.limit - gh.get_rate_limit().core.remaining
        self.search_tare = gh.get_rate_limit().search.limit - gh.get_rate_limit().search.remaining
        self.core_calls = [0]
        self.search_calls = [0]
        self.gh = gh

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

    def total(self):
        print(f"GH RateLimit: Total Core Calls = {self.core_calls[-1]}")
        print(f"GH RateLimit: Total Search Calls = {self.search_calls[-1]}")


class V3Projects(BaseModel):
    pass


class V3Targets(BaseModel):
    pass


class V3Target(BaseModel):
    pass


class SnykV3Client(object):
    API_URL = "https://api.snyk.io/v3"
    V3_VERS = "2021-08-20~beta"
    USER_AGENT = f"pysnyk/snyk_services/sync/{__version__}"

    def __init__(
        self,
        token: str,
        url: Optional[str] = None,
        version: Optional[str] = None,
        user_agent: Optional[str] = USER_AGENT,
        debug: bool = False,
        tries: int = 1,
        delay: int = 1,
        backoff: int = 2,
    ):
        self.api_token = token
        self.api_url = url or self.API_URL
        self.api_vers = version or self.V3_VERS
        self.api_headers = {
            "Authorization": "token %s" % self.api_token,
            "User-Agent": user_agent,
        }
        self.api_post_headers = self.api_headers
        self.api_post_headers["Content-Type"] = "Content-Type: application/vnd.api+json"
        self.tries = tries
        self.backoff = backoff
        self.delay = delay

    def request(
        self,
        method,
        url: str,
        headers: object,
        params: object = None,
        json: object = None,
    ) -> requests.Response:

        resp: requests.Response

        resp = method(
            url,
            json=json,
            params=params,
            headers=headers,
        )

        if not resp or resp.status_code >= requests.codes.server_error:
            resp.raise_for_status()
        return resp

    def get(self, path: str, params: dict = {}) -> requests.Response:

        # path = ensure_version(path, self.V3_VERS)
        # path = cleanup_path(path)

        if "version" not in params.keys():
            params["version"] = self.V3_VERS

        params = {k: v for (k, v) in params.items() if v}

        # because python bool(True) != javascript bool(True) - True vs true
        for k, v in params.items():
            if isinstance(v, bool):
                params[k] = str(v).lower()

        url = f"{self.api_url}/{path}"
        logger.debug("GET: %s" % url)
        resp = retry_call(
            self.request,
            fargs=[requests.get, url, self.api_headers, params],
            tries=self.tries,
            delay=self.delay,
            backoff=self.backoff,
            logger=logger,
        )

        # logger.debug("RESP: %s" % resp.status_code)

        if not resp.ok:
            resp.raise_for_status()
        return resp

    def get_all_pages(self, path: str, params: dict = {}) -> List:
        """
        This is a wrapper of .get() that assumes we're going to get paginated results.
        In that case we really just want concated lists from each pages 'data'
        """

        # this is a raw primative but a higher level module might want something that does an
        # arbitrary path + origin=foo + limit=100 url construction instead before being sent here

        data = list()

        page = self.get(path, params).json()

        data.extend(page["data"])

        while "next" in page["links"].keys():
            next_url = page["links"]["next"]
            page = self.get(next_url).json()
            data.extend(page["data"])

        return data


def cleanup_path(path: str):
    if path[0] == "/":
        return path[1:]
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
