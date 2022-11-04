import json
import logging
from datetime import datetime
from logging import exception
from os import environ
from os import path
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Dict
from typing import Optional
from typing import Union
from typing import cast

import backoff
import requests
import typer
import yaml
from github import Github
from github.GithubException import RateLimitExceededException
from github.Organization import Organization
from github.PaginatedList import PaginatedList
from models.sync import Repo
from models.sync import Settings
from models.sync import SnykWatchList
from retry.api import retry_call
from typer import Context


V3_VERS = "2021-08-20~beta"
USER_AGENT = "pysnyk/snyk_services/snyk_scm_mapper"

logger = logging.getLogger(__name__)
logging.basicConfig(filename="snyk_scm_mapper.log", filemode="w", encoding="utf-8")


def jprint(something):
    print(json.dumps(something, indent=2))


def jopen(filename):
    with open(filename, "r") as the_file:
        data = the_file.read()
    return json.loads(data)


def jwrite(data, filename, minimize: bool = False):
    try:
        with open(filename, "w") as the_file:
            if minimize:
                the_file.write(json.dumps(data, separators=(",", ":")))
            else:
                the_file.write(json.dumps(data, indent=2))
            return True
    except:
        return False


def yopen(filename):
    with open(filename, "r") as the_file:
        data = the_file.read()
    return yaml.safe_load(data)


def newer(cached: str, remote: str) -> bool:
    # 2021-08-25T13:37:43Z

    cache_ts = datetime.strptime(cached, "%Y-%m-%d %H:%M:%S")
    remote_ts = datetime.strptime(remote, "%Y-%m-%d %H:%M:%S")

    # print(cache_ts, remote_ts)

    return bool(remote_ts < cache_ts)


def make_v3_get(endpoint, token):
    V3_API = "https://api.snyk.io/v3"
    USER_AGENT = "pysnyk/snyk_services/target_sync"

    client = requests.Session()
    client.headers.update({"Authorization": f"token {token}"})
    client.headers.update({"User-Agent": USER_AGENT})
    client.headers.update({"Content-Type": "application/vnd.api+json"})
    url = f"{V3_API}/{endpoint}"
    return client.get(url)


def v3_get(endpoint, token, delay=1):
    result = retry_call(make_v3_get, fkwargs={"endpoint": endpoint, "token": token}, tries=3, delay=delay)
    return result


def get_org_targets(org: dict, token: str) -> list:

    print(f"getting {org['id']} / {org['slug']} targets")
    targets_raw = v3_get(f"orgs/{org['id']}/targets?version={V3_VERS}", token)

    targets_resp = targets_raw.json()

    targets = targets_resp["data"]

    return targets


def get_org_projects(org: dict, token: str) -> dict:

    print(f"getting {org['id']} / {org['slug']} projects")

    try:
        first_resp = v3_get(f"orgs/{org['id']}/projects?version={V3_VERS}", token)
    except Exception as e:
        print(f"{org['id']} project lookup failed with {e}")
        orgs_resp: Dict = {"data": []}
        return orgs_resp

    orgs_resp = first_resp.json()

    all_pages = list()
    all_pages.extend(orgs_resp["data"])

    while "links" in orgs_resp.keys():
        if "next" in orgs_resp["links"].keys():
            first_resp = v3_get(orgs_resp["links"]["next"], token)
            orgs_resp = first_resp.json()
            if "data" in orgs_resp.keys():
                all_pages.extend(orgs_resp["data"])
        else:
            orgs_resp.pop("links")

    orgs_resp["data"] = all_pages

    return orgs_resp


def search_projects(base_name, origin, client, snyk_token, org_in: dict):

    org: Dict = dict()

    org["id"] = org_in["orgId"]
    org["slug"] = list(org_in)[0]

    query = {"filters": {"origin": origin, "name": base_name}}
    path = f"org/{org['id']}/projects"

    return json.loads(client.post(path, query).text)


def to_camel_case(snake_str):
    components = snake_str.split("_")
    # We capitalize the first letter of each component except the first one
    # with the 'title' method and join them together.
    return components[0] + "".join(x.title() for x in components[1:])


def default_settings(
    name: Optional[str], value: str, default: Union[Any, Callable[[], Any], None], context: Context
) -> Settings:
    """
    We want a self / auto configuring experience for Snyk Sync, but also allow for options to be passed from ENV, CLI, OR a config file.
    CLI overrides ENV, and typer handles that for us. But we want CLI and ENV to override the config file, so we need to load that value
    Also we have a lot of relativistic values, ie the tags directory is in the root of the folder containing the config file
    So if tag_dir isn't set by CLI or ENV, it ends up here. Then if it's not set in the conf file, we want to return the directory of the
    conf file + /tags
    """

    # Since we've removed the typer check for the conf file, we have to ensure it exists here

    if context.invoked_subcommand == "autoconf":
        if name == "conf":
            if Path(value).exists is False:
                new_conf = {"schema": 2}
                Path(value).write_text(yaml.safe_dump(new_conf))
            elif Path(value).is_dir():
                raise Exception(f"Snyk Sync config file: {value} is a directory, it needs to be yaml file")

    settings = context.params

    # we're likely never called, but just in case,
    # if there is already a value and it's not the
    # default value it wins, it was set by CLI or ENV
    if value != default:
        return value

    if "conf" in settings.keys():
        conf_file = Path(settings["conf"])
    else:
        conf_file = Path("snyk-sync.yaml")

    if conf_file.exists():
        auto_conf = False
    else:
        auto_conf = True

    s: dict = {}

    if not auto_conf:
        s = yopen(conf_file)

    # here we return whatever we find in the conf file
    if name in s.keys():
        return s[name]

    # everything below here is dynamic handling of values

    if name == "snyk_orgs_file":
        if "orgs_file" in s.keys():
            return s["orgs_file"]
        else:
            return gen_path(conf_file, "snyk-orgs.yaml")

    # pretty much we want to break here and not do magic in the case of autoconf
    if auto_conf:
        return value

    # our directories are always 'dirname'_dir
    if "_dir" in str(name):

        dirname: str = str(name).split("_")[0]

        the_dir_path = gen_path(conf_file, dirname)

        if not auto_conf:
            ensure_dir(the_dir_path)

        return the_dir_path

    if name == "snyk_token":

        token_env_name = s["snyk"]["groups"][0]["token_env_name"]

        if token_env_name in environ.keys():
            token = environ[token_env_name]
        else:
            raise Exception(f"Environment Variable {token_env_name} for {name}is not set properly and required")

        return token

    if name == "github_token":

        token_env_name = s["github_token_env_name"]

        if token_env_name in environ.keys():
            token = environ[token_env_name]
        else:
            raise Exception(f"Environment Variable {token_env_name} for {name}is not set properly and required")

        return token

    if name == "default_org":
        return s["default"]["orgName"]

    if name == "default_int":
        return s["default"]["integrationName"]

    return default


def gen_path(parent_file: Path, child: str):
    the_path_string = f"{parent_file.parent}/{child}"

    return Path(the_path_string)


def ensure_dir(directory: Path) -> bool:
    if not directory.exists():
        try:
            directory.mkdir()
            return True
        except Exception as e:
            raise Exception(f"Error attempting to create {directory}: {e}")
    elif directory.is_file():
        raise Exception(f"Expected {directory} to be a directory, but is a file")
    else:
        # the directory exists and is OK
        return True


def load_watchlist(cache_dir: Path) -> SnykWatchList:
    tmp_watchlist = SnykWatchList()
    cache_data_errors = []

    # such data paths should be set as script-wide variables in the future
    # as these are accessed in various places
    data_json_path = f"{cache_dir}/data.json"

    try:
        cache_data = jopen(data_json_path)
    except Exception as e:
        print(f"WARNING: could not load cache data from file {data_json_path}: {repr(e)}")
        return tmp_watchlist

    for repo in cache_data:
        try:
            tmp_watchlist.repos.append(Repo.parse_obj(repo))
        except Exception as e:
            cache_data_error_string = f"Error {repr(e)} attempting to parse import.yaml in repo {repo['url']}"
            # print(f"{cache_data_error_string}")
            cache_data_errors.append(cache_data_error_string)

    if cache_data_errors:
        print(f"{len(cache_data_errors)} errors when loading cache, please see log for details")
        for cache_data_error in cache_data_errors:
            logger.warning(f"{cache_data_error}")

    return tmp_watchlist


def update_client(old_client, token):
    old_client.api_token = token
    old_client.api_headers["Authorization"] = f"token {old_client.api_token}"
    old_client.api_post_headers = old_client.api_headers

    return old_client


def filter_chunk(chunk, exclude_list):
    return [y for y in chunk if y.repository.id not in exclude_list and y.name == "import.yaml"]


# Function wrappers for GitHub API calls. Here we simply wrap the original call in a function which is decorated with
# a "backoff". This will catch rate limit exceptions and automatically retry the function.
@backoff.on_exception(backoff.expo, RateLimitExceededException)
def get_page_wrapper(pg_list: PaginatedList, page_number: int, show_rate_limit: bool = False):
    try:
        return pg_list.get_page(page_number)
    except RateLimitExceededException as e:
        if not show_rate_limit:
            typer.echo("GitHub rate limit was hit.. backing off...")
        raise e


@backoff.on_exception(backoff.expo, RateLimitExceededException)
def get_organization_wrapper(gh: Github, gh_org_name: str, show_rate_limit: bool = False):
    try:
        return gh.get_organization(gh_org_name)
    except RateLimitExceededException as e:
        if not show_rate_limit:
            typer.echo("GitHub rate limit was hit.. backing off...")
        raise e


@backoff.on_exception(backoff.expo, RateLimitExceededException)
def get_repos_wrapper(gh_org: Organization, type: str, sort: str, direction: str, show_rate_limit: bool = False):
    try:
        return gh_org.get_repos(type=type, sort=sort, direction=direction)
    except RateLimitExceededException as e:
        if not show_rate_limit:
            typer.echo("GitHub rate limit was hit.. backing off...")
        raise e
