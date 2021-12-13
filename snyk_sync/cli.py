from pydantic.typing import update_field_forward_refs
import typer
import datetime
import os
import json
import yaml
import snyk
import api
import logging


from __version__ import __version__

from os import environ

from pathlib import Path
from github import Github, Repository
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from pprint import pprint

from models.repositories import Repo, Project, Tag
from models.sync import SnykWatchList, Settings
from models.organizations import Orgs, Org, Target

from api import RateLimit

from utils import yopen, jopen, search_projects, newer, jwrite, default_settings

app = typer.Typer(add_completion=False)

s = Settings()

watchlist = SnykWatchList()

# DEBUG_LEVEL = environ["SNYK_SYNC_DEBUG_LEVEL"] or "INFO"

logging.basicConfig(level="INFO")


def settings_callback(ctx: typer.Context, param: typer.CallbackParam, value: str):

    if value and value != param.default:
        return value
    else:
        setting = default_settings(param.name, value, param.default, ctx)
        return setting


@app.callback(
    invoke_without_command=True,
    no_args_is_help=False,
)
def main(
    ctx: typer.Context,
    conf: Path = typer.Option(
        default="snyk-sync.yaml",
        file_okay=True,
        dir_okay=False,
        writable=False,
        readable=True,
        resolve_path=True,
        envvar="SNYK_SYNC_CONFIG",
    ),
    cache_dir: Optional[Path] = typer.Option(
        default=None,
        exists=True,
        file_okay=False,
        dir_okay=True,
        writable=True,
        readable=True,
        resolve_path=True,
        help="Cache location",
        envvar="SNYK_SYNC_CACHE_DIR",
        callback=settings_callback,
    ),
    cache_timeout: int = typer.Option(
        default=60,
        help="Maximum cache age, in minutes",
        envvar="SNYK_SYNC_CACHE_TIMEOUT",
        callback=settings_callback,
    ),
    forks: bool = typer.Option(
        default=False,
        help="Check forks for import.yaml files",
        envvar="SNYK_SYNC_FORKS",
        callback=settings_callback,
    ),
    targets_dir: Optional[Path] = typer.Option(
        default=None,
        exists=True,
        file_okay=False,
        dir_okay=True,
        writable=True,
        readable=True,
        resolve_path=True,
        envvar="SNYK_SYNC_TARGETS_DIR",
        callback=settings_callback,
    ),
    tags_dir: Optional[Path] = typer.Option(
        default=None,
        exists=True,
        file_okay=False,
        dir_okay=True,
        writable=True,
        readable=True,
        resolve_path=True,
        envvar="SNYK_SYNC_TAGS_DIR",
        callback=settings_callback,
    ),
    snyk_orgs_file: Optional[Path] = typer.Option(
        default=None,
        exists=True,
        file_okay=True,
        dir_okay=False,
        writable=False,
        readable=True,
        resolve_path=True,
        help="Snyk orgs to watch",
        envvar="SNYK_SYNC_ORGS",
        callback=settings_callback,
    ),
    default_org: str = typer.Option(
        default=None,
        help="Default Snyk Org to use from Orgs file.",
        envvar="SNYK_SYNC_DEFAULT_ORG",
        callback=settings_callback,
    ),
    default_int: str = typer.Option(
        default=None,
        help="Default Snyk Integration to use with Default Org.",
        envvar="SNYK_SYNC_DEFAULT_INT",
        callback=settings_callback,
    ),
    instance: str = typer.Option(
        default=None,
        help="Default Snyk Integration to use with Default Org.",
        envvar="SNYK_SYNC_INSTANCE",
        callback=settings_callback,
    ),
    snyk_token: UUID = typer.Option(
        default=None,
        help="Snyk access token, if not loaded from Env it will attempt to load from first group",
        envvar="SNYK_TOKEN",
        callback=settings_callback,
    ),
    force_sync: bool = typer.Option(
        False,
        "--sync",
        help="Forces a sync regardless of cache status",
        callback=settings_callback,
    ),
    github_token: str = typer.Option(
        default=None,
        help="GitHub access token, if not set here will load from ENV VAR named in snyk-sync.yaml",
        envvar="GITHUB_TOKEN",
        callback=settings_callback,
    ),
):

    # We keep this as the global settings hash
    global s
    global watchlist

    s = Settings.parse_obj(ctx.params)

    if ctx.invoked_subcommand is None:
        typer.echo("Snyk Sync invoked with no subcommand, executing all", err=True)
        if status() is False:
            sync()


@app.command()
def sync(
    show_rate_limit: bool = typer.Option(
        False,
        "--show-rate-limit",
        help="Display GH rate limit status between each batch of API calls",
    )
):
    """
    Force a sync of the local cache of the GitHub / Snyk data.
    """

    global watchlist
    global s

    typer.echo("Sync starting", err=True)

    load_conf()

    # flush the watchlist
    # watchlist = SnykWatchList()

    GH_PAGE_LIMIT = 100

    gh = Github(s.github_token, per_page=GH_PAGE_LIMIT)

    rate_limit = RateLimit(gh, GH_PAGE_LIMIT)

    client = snyk.SnykClient(
        str(s.snyk_token), user_agent=f"pysnyk/snyk_services/sync/{__version__}", tries=2, delay=1
    )

    v3client = api.SnykV3Client(
        str(s.snyk_token), user_agent=f"pysnyk/snyk_services/sync/{__version__}", tries=2, delay=1
    )

    if s.github_orgs is not None:
        gh_orgs = list(s.github_orgs)
    else:
        gh_orgs = list()

    rate_limit.update(show_rate_limit)

    exclude_list = []

    typer.echo("Getting all GitHub repos", err=True)

    for gh_org_name in gh_orgs:
        gh_org = gh.get_organization(gh_org_name)
        gh_repos = gh_org.get_repos(type="all", sort="updated", direction="desc")
        gh_repos_count = gh_repos.totalCount

        rate_limit.add_calls(gh_repos_count)

        pages = gh_repos_count // GH_PAGE_LIMIT

        if (gh_repos_count % GH_PAGE_LIMIT) > 0:
            pages += 1

        with typer.progressbar(
            length=pages, label=f"Processing {gh_repos_count} repos in {gh_org_name}: "
        ) as gh_progress:

            for r in range(0, pages):

                rate_limit.check()

                for gh_repo in gh_repos.get_page(r):

                    watchlist.add_repo(gh_repo)

                gh_progress.update(1)

    # print(exclude_list)
    rate_limit.update(show_rate_limit)

    import_yamls = []
    for gh_org in gh_orgs:
        search = f"org:{gh_org} path:.snyk.d filename:import language:yaml"
        import_repos = gh.search_code(query=search)
        rate_limit.add_calls(import_repos.totalCount)
        rate_limit.check("search")
        import_repos = [y for y in import_repos if y.repository.id not in exclude_list and y.name == "import.yaml"]
        import_yamls.extend(import_repos)

    rate_limit.update(show_rate_limit)

    # we will likely want to put a limit around this, as we need to walk forked repose and try to get import.yaml
    # since github won't index a fork if it has less stars than upstream

    forks = [f for f in watchlist.repos if f.fork]
    forks = [y for y in forks if y.id not in exclude_list]

    if s.forks is True and len(forks) > 0:
        typer.echo(f"Scanning {len(forks)} forks for import.yaml", err=True)

        rate_limit.add_calls(len(forks) * 2)
        rate_limit.check()

        with typer.progressbar(forks, label="Scanning: ") as forks_progress:
            for fork in forks_progress:
                f_owner = fork.source.owner
                f_name = fork.source.name
                f_repo = gh.get_repo(f"{f_owner}/{f_name}")
                try:
                    f_yaml = f_repo.get_contents(".snyk.d/import.yaml")
                    yaml_repo = watchlist.get_repo(f_repo.id)
                    if yaml_repo:
                        yaml_repo.parse_import(f_yaml, instance=s.instance)
                except:
                    pass

        typer.echo(f"Have {len(import_yamls)} Repos with an import.yaml", err=True)
        rate_limit.update(show_rate_limit)

    if len(import_yamls) > 0:
        typer.echo(f"Loading import.yaml for non fork-ed repos", err=True)

        with typer.progressbar(import_yamls, label="Scanning: ") as import_progress:
            for import_yaml in import_progress:

                r_id = import_yaml.repository.id

                import_repo = watchlist.get_repo(r_id)

                if import_repo:
                    import_repo.parse_import(import_yaml, instance=s.instance)

    rate_limit.update(show_rate_limit)

    # this calls our new Orgs object which caches and populates Snyk data locally for us
    all_orgs = Orgs(cache=str(s.cache_dir), groups=s.snyk_groups)

    select_orgs = [str(o["orgId"]) for k, o in s.snyk_orgs.items()]

    typer.echo(f"Updating cache of Snyk projects", err=True)

    all_orgs.refresh_orgs(client, v3client, origin="github-enterprise", selected_orgs=select_orgs)

    all_orgs.save()

    typer.echo("Scanning Snyk for projects originating from GitHub Enterprise Repos", err=True)
    for r in watchlist.repos:
        found_projects = all_orgs.find_projects_by_repo(r.full_name, r.id)
        for p in found_projects:
            r.add_project(p)

    watchlist.save(cachedir=str(s.cache_dir))
    typer.echo("Sync completed", err=True)

    if show_rate_limit is True:
        rate_limit.total()

    del all_orgs

    typer.echo(f"Total Repos: {len(watchlist.repos)}", err=True)


@app.command()
def status():
    """
    Return if the cache is out of date
    """
    global watchlist
    global s

    if s.force_sync:
        typer.echo("Sync forced, ignoring cache status", err=True)
        return False

    typer.echo("Checking cache status", err=True)

    if os.path.exists(f"{s.cache_dir}/sync.json"):
        sync_data = jopen(f"{s.cache_dir}/sync.json")
    else:
        return False

    last_sync = datetime.strptime(sync_data["last_sync"], "%Y-%m-%dT%H:%M:%S.%f")

    in_sync = True

    if s.cache_timeout is None:
        timeout = 0
    else:
        timeout = float(str(s.cache_timeout))

    if last_sync < datetime.utcnow() - timedelta(minutes=timeout):
        typer.echo("Cache is out of date and needs to be updated", err=True)
        in_sync = False
    else:
        typer.echo(f"Cache is less than {s.cache_timeout} minutes old", err=True)

    typer.echo("Attempting to load cache", err=True)
    try:
        cache_data = jopen(f"{s.cache_dir}/data.json")
        for r in cache_data:
            watchlist.repos.append(Repo.parse_obj(r))

    except KeyError as e:
        typer.echo(e)

    typer.echo("Cache loaded successfully", err=True)

    watchlist.default_org = s.default_org
    watchlist.snyk_orgs = s.snyk_orgs

    return in_sync


@app.command()
def targets(
    save_targets: bool = typer.Option(False, "--save", help="Write targets to disk, otherwise print to stdout"),
    force_default: bool = typer.Option(False, "--force-default", help="Forces all Org's to default"),
):
    """
    Returns valid input for api-import to consume
    """
    global s
    global watchlist

    if status() == False:
        sync()
    else:
        load_conf()

    all_orgs = Orgs(cache=str(s.cache_dir), groups=s.snyk_groups)

    all_orgs.load()

    target_list = []

    for r in watchlist.repos:
        if r.needs_reimport(s.default_org, s.snyk_orgs):
            for branch in r.get_reimport(s.default_org, s.snyk_orgs):
                if branch.project_count() == 0:

                    if force_default:
                        org_id = s.snyk_orgs[s.default_org]["orgId"]
                        int_id = s.snyk_orgs[s.default_org]["integrations"]["github-enterprise"]
                    else:
                        org_id = branch.org_id
                        int_id = branch.integrations["github-enterprise"]

                    source = r.source.get_target()

                    source["branch"] = branch.name

                    target = {
                        "target": source,
                        "integrationId": int_id,
                        "orgId": org_id,
                    }

                    target_list.append(target)

    final_targets = list()

    for group in s.snyk_groups:
        orgs = all_orgs.get_orgs_by_group(group)

        o_ids = [str(o.id) for o in orgs]

        g_targets = {"name": group["name"], "targets": list()}

        g_targets["targets"] = [t for t in target_list if str(t["orgId"]) in o_ids]

        final_targets.append(g_targets)

    if save_targets is True:
        typer.echo(f"Writing targets to {s.targets_dir}", err=True)
        if os.path.isdir(f"{s.targets_dir}") is not True:
            typer.echo(f"Creating directory to {s.targets_dir}", err=True)
            os.mkdir(f"{s.targets_dir}")
        for targets in final_targets:
            file_name = f"{s.targets_dir}/{targets.pop('name')}.json"
            if len(targets["targets"]) > 50:
                minimize = True
            else:
                minimize = False

            if jwrite(targets, file_name, minimize):
                typer.echo(f"Wrote {file_name} Successfully", err=True)
            else:
                typer.echo(f"Failed to Write {file_name}", err=True)
    else:
        typer.echo(json.dumps(final_targets, indent=2))


@app.command()
def tags(
    update_tags: bool = typer.Option(False, "--update", help="Updates tags on projects instead of outputting them"),
    save_tags: bool = typer.Option(False, "--save", help="Write tags to disk, otherwise print to stdout"),
):
    """
    Returns list of project id's and the tags said projects are missing
    """
    global s
    global watchlist

    v1client = snyk.SnykClient(
        str(s.snyk_token), user_agent=f"pysnyk/snyk_services/sync/{__version__}", tries=1, delay=1
    )

    if status() == False:
        sync()
    else:
        load_conf()

    all_orgs = Orgs(cache=str(s.cache_dir), groups=s.snyk_groups)

    all_orgs.load()

    needs_tags = list()

    for group in s.snyk_groups:

        group_tags = {"name": group["name"], "tags": list()}

        orgs = all_orgs.get_orgs_by_group(group)

        o_ids = [str(o.id) for o in orgs]

        group_tags["tags"] = watchlist.get_proj_tag_updates(o_ids)

        needs_tags.append(group_tags)

    # now we iterate over needs_tags by group and save out a per group tag file

    for g_tags in needs_tags:
        if g_tags["tags"]:
            if update_tags is True:
                typer.echo(f"Checking if {g_tags['name']} projects need tag updates", err=True)

                snyk_token = all_orgs.get_token_for_group(g_tags["name"])

                setattr(v1client, "token", snyk_token)

                for p in g_tags["tags"]:
                    p_path = f"org/{p['org_id']}/project/{p['project_id']}"
                    p_tag_path = f"{p_path}/tags"

                    p_live = json.loads(v1client.get(p_path).text)

                    tags_to_post = [t for t in p["tags"] if t not in p_live["tags"]]

                    if len(tags_to_post) > 0:
                        typer.echo(f"Updating {g_tags['name']} project {p_live['name']} tags", err=True)
                        for tag in tags_to_post:
                            try:
                                v1client.post(p_tag_path, tag)
                            except snyk.errors.SnykHTTPError as e:
                                if e.code == 422:
                                    typer.echo(f"Error: Tag for project already exists")
                                else:
                                    raise Exception(f"snyk api returned code: {e.code}")

            if save_tags is True:
                typer.echo(f"Writing {g_tags['name']} tag updates to {s.tags_dir}")
                if os.path.isdir(f"{s.tags_dir}") is not True:
                    typer.echo(f"Creating directory {s.tags_dir}", err=True)
                    os.mkdir(f"{s.tags_dir}")
                file_name = f"{s.tags_dir}/{g_tags['name']}.json"
                if jwrite(g_tags["tags"], file_name):
                    typer.echo(f"Wrote {file_name} Successfully", err=True)
                else:
                    typer.echo(f"Failed to Write {file_name}", err=True)

            if not save_tags and not update_tags:
                typer.echo(json.dumps(g_tags["tags"], indent=2))

        else:
            typer.echo(f"No {g_tags['name']} projects require tag updates", err=True)


@app.command()
def autoconf(
    snykorg: str = typer.Argument(..., help="The Snyk Org Slug to use"),
    githuborg: str = typer.Argument(..., help="The Github Org to use"),
):
    """
    Autogenerates a configuration template given an orgname

    This requires an existing snyk-sync.yaml and snyk-orgs.yaml, which it will overwrite
    """
    global s

    client = snyk.SnykClient(str(s.snyk_token), user_agent=f"pysnyk/snyk_services/sync/{__version__}")

    conf = dict()
    conf["schema"] = 2
    conf["github_orgs"] = [str(githuborg)]
    conf["snyk"] = dict()
    conf["snyk"]["groups"] = list()
    conf["default"] = dict()
    conf["default"]["orgName"] = snykorg
    conf["default"]["integrationName"] = "github-enterprise"

    typer.echo(f"Generating configuration based on Snyk Org: {snykorg} and Github Org: {githuborg} ", err=True)

    orgs = client.get("orgs").json()

    my_org = [o for o in orgs["orgs"] if o["slug"] == snykorg][0]

    my_group_id = my_org["group"]["id"]

    my_group_name = str(my_org["group"]["name"])

    typer.echo(f"Detected Snyk Group: {my_group_name}", err=True)

    my_group_slug = "".join(filter(lambda x: x.isalnum() or x.isspace(), my_group_name.lower()))
    my_group_slug = "-".join(my_group_slug.split())

    typer.echo(f"Snyk Group: {my_group_name} slug is: {my_group_slug}", err=True)

    group = {"name": my_group_slug, "id": my_group_id, "token_env_name": "SNYK_TOKEN"}

    conf["snyk"]["groups"].append(group)

    group_orgs = api.v1_get_pages(f"group/{my_group_id}/orgs", client, "orgs")

    snyk_orgs = dict()

    with typer.progressbar(group_orgs["orgs"], label="Retrieving every Orgs integration details: ") as orgs:
        for org in orgs:

            org_int = client.get(f"org/{org['id']}/integrations").json()

            if "github-enterprise" in org_int:
                snyk_orgs[org["slug"]] = dict()
                snyk_orgs[org["slug"]]["orgId"] = org["id"]
                snyk_orgs[org["slug"]]["integrations"] = org_int

    if s.conf.write_text(yaml.safe_dump(conf)):
        typer.echo(f"Wrote Snyk Syncconfiguration to: {s.conf.as_posix()}", err=True)

    if s.snyk_orgs_file.write_text(yaml.safe_dump(snyk_orgs)):
        typer.echo(f"Wrote Snyk Orgs data for the Group: {my_group_slug} to: {s.snyk_orgs_file.as_posix()}", err=True)


def load_conf():

    global s
    global watchlist

    conf_file = yopen(s.conf)

    # below are two settings we actually want to load from the file only, since they are too complicated to load other ways

    s.github_orgs = conf_file["github_orgs"]

    s.snyk_groups = conf_file["snyk"]["groups"]

    s.snyk_orgs = yopen(s.snyk_orgs_file)

    watchlist.default_org = s.default_org
    watchlist.snyk_orgs = s.snyk_orgs

    # Load our per group service token, which are set as custom env paths

    for group in s.snyk_groups:
        env_var = group["token_env_name"]
        if env_var in environ.keys():
            group["snyk_token"] = environ[env_var]
        else:
            raise Exception(f"Environment Variable {env_var} is not set properly and required")


if __name__ == "__main__":
    app()
