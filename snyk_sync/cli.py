from pydantic.typing import update_field_forward_refs
import typer
import time
import os
import json
import yaml
import snyk

from pathlib import Path
from github import Github, Repository
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID

from models import SnykWatchList, Repo, Project, Settings, Tag
from utils import yopen, jopen, search_projects, RateLimit, newer

app = typer.Typer()

s = Settings()

watchlist = SnykWatchList()


@app.callback(invoke_without_command=True)
def main(
        ctx: typer.Context,
        cache_dir: Path = typer.Option(
            default='cache',
            exists=True,
            file_okay=False,
            dir_okay=True,
            writable=True,
            readable=True,
            resolve_path=True,
            help="Cache location",
            envvar="SNYK_WATCHER_CACHE_DIR",
        ), 
        cache_timeout: int = typer.Option(
            default=60,
            help="Maximum cache age, in minutes",
            envvar="SNYK_WATCHER_CACHE_TIMEOUT",
        ),
        forks: bool = typer.Option(
            default=False,
            help="Check forks for import.yaml files",
            envvar="SNYK_WATCHER_FORKS"
        ), 
        conf: Path = typer.Option(
            default='snyk_watcher.yaml',
            exists=True,
            file_okay=True,
            dir_okay=False,
            writable=False,
            readable=True,
            resolve_path=True,
            envvar="SNYK_WATCHER_CONFIG",
        ),
        targets_file: Optional[Path] = typer.Option(
            default=None,
            exists=True,
            file_okay=True,
            dir_okay=False,
            writable=True,
            readable=True,
            resolve_path=True,
            envvar="SNYK_WATCHER_TARGETS_FILE",
        ),
        snyk_orgs_file: Optional[Path] = typer.Option(
            default=None,
            exists=True,
            file_okay=True,
            dir_okay=False,
            writable=False,
            readable=True,
            resolve_path=True,
            help='Snyk orgs to watch',
            envvar="SNYK_WATCHER_SNYK_ORGS",
        ),
        default_org: str = typer.Option(
            default=None,
            help="Default Snyk Org to use from Orgs file.",
            envvar="SNYK_WATCHER_DEFAULT_ORG",
        ),
        default_int: str = typer.Option(
            default=None,
            help="Default Snyk Integration to use with Default Org.",
            envvar="SNYK_WATCHER_DEFAULT_INT",
        ),
        snyk_group: UUID = typer.Option(
            ...,
            help="Group ID, required but will scrape from ENV",
            envvar="SNYK_GROUP",
        ), 
        snyk_token: UUID = typer.Option(
            ...,
            help="Snyk access token",
            envvar="SNYK_TOKEN",
        ), 
        github_token: str = typer.Option(
            ...,
            help="GitHub access token",
            envvar="GITHUB_TOKEN",
        )
    ):

    # We keep this as the global settings hash
    global s
    global watchlist

    # s_dict = dict.fromkeys([o for o in dir() if o != 'ctx'])

    # for k in s_dict:
    #     s_dict[k] = vars()[k]

    # why are we creating a dict and then loading it?
    

    # updating a global var
    # this is a lazy way of stripping all the data from the inputs into the settings we care about
    s = Settings.parse_obj(vars())
    
    conf_dir = os.path.dirname(str(s.conf))
    conf_file = yopen(s.conf)


    if s.targets_file is None:
        s.targets_file = Path(f'{conf_dir}/{conf_file["targets_file_name"]}')
    
    if s.snyk_orgs_file is None:
        s.snyk_orgs_file = Path(f'{conf_dir}/{conf_file["orgs_file"]}')

    s.github_orgs = conf_file['github_orgs']

    if s.default_org is None:
        s.default_org = conf_file['default']['orgName']
    
    if s.default_int is None:
        s.default_int = conf_file['default']['integrationName']
    

    s.snyk_orgs = yopen(s.snyk_orgs_file)

    s.default_org_id = s.snyk_orgs[s.default_org]['orgId']
    s.default_int_id = s.snyk_orgs[s.default_org]['integrations'][s.default_int]

    if ctx.invoked_subcommand is None:
        typer.echo("Snyk Watcher invoked with no subcommand, executing all")
        if status() is False:
            sync()


@app.command()
def sync():
    """
    Force a sync of the local cache of the GitHub / Snyk data.
    """

    global watchlist
    global s

    typer.echo("Sync starting")

    # flush the watchlist
    #watchlist = SnykWatchList()

    gh = Github(s.github_token)

    rate_limit = RateLimit(gh)

    client = snyk.SnykClient(str(s.snyk_token))

    if s.github_orgs is not None:
        gh_orgs = list(s.github_orgs)
    else:
        gh_orgs = list()

    rate_limit.update(True)

    exclude_list=[]

    typer.echo("Getting all GitHub repos")
    with typer.progressbar(gh_orgs, label="Processing: ") as gh_progress:
        for gh_org in gh_progress:
            gh_repos = gh.search_repositories(f'org:{gh_org} fork:true')
            for gh_repo in gh_repos:
                #print(watchlist.has_repo(gh_repo.id))
                if watchlist.has_repo(gh_repo.id) == False:
                    # i know there is a better way to do this
                    tmp_repo = {
                        "fork": gh_repo.fork,
                        "name": gh_repo.name,
                        "owner": gh_repo.owner.login,
                        "branch": gh_repo.default_branch,
                        "url": gh_repo.html_url,
                        "project_base": gh_repo.full_name,
                    }
                    tmp_target = Repo(
                        source=tmp_repo,
                        url=gh_repo.html_url,
                        fork=gh_repo.fork,
                        id=gh_repo.id,
                        updated_at=str(gh_repo.updated_at)
                    )
                    watchlist.repos.append(tmp_target)

                elif newer(watchlist.get_repo(gh_repo.id).updated_at, str(gh_repo.updated_at)):
                    tmp_repo = {
                        "fork": gh_repo.fork,
                        "name": gh_repo.name,
                        "owner": gh_repo.owner.login,
                        "branch": gh_repo.default_branch,
                        "url": gh_repo.html_url,
                        "project_base": gh_repo.full_name,
                    }
                    watchlist.get_repo(gh_repo.url).source=tmp_repo,
                    watchlist.get_repo(gh_repo.url).url=gh_repo.html_url,
                    watchlist.get_repo(gh_repo.url).fork=gh_repo.fork,
                    watchlist.get_repo(gh_repo.url).id=gh_repo.id,
                    watchlist.get_repo(gh_repo.url).updated_at=str(gh_repo.updated_at)
                else:
                    exclude_list.append(gh_repo.id)

    #print(exclude_list)
    rate_limit.update(True)

    import_yamls = []
    for gh_org in gh_orgs:
        search = f'org:{gh_org} path:.snyk.d'
        import_repos = gh.search_code(query=search)
        import_repos = [y for y in import_repos if y.repository.id not in exclude_list]
        import_yamls.extend([y for y in import_repos if y.name == 'import.yaml'])

    rate_limit.update(True)

    for the_yaml in import_yamls:
        print(the_yaml.sha)

    # we will likely want to put a limit around this, as we need to walk forked repose and try to get import.yaml
    # since github won't index a fork if it has less stars than upstream

    forks = [f for f in watchlist.repos if f.fork()]
    forks = [y for y in forks if y.id not in exclude_list]

    if s.forks and len(forks) > 0:
        typer.echo(f"Scanning {len(forks)} forks for import.yaml")

        with typer.progressbar(forks, label="Scanning: ") as forks_progress:
            for fork in forks_progress:
                f_owner = fork.source.owner
                f_name = fork.source.name
                f_repo = gh.get_repo(f'{f_owner}/{f_name}')
                try:
                    f_yaml = f_repo.get_contents('.snyk.d/import.yaml')
                    import_yamls.append(f_yaml)
                except:
                    pass
        
        typer.echo(f"Have {len(import_yamls)} Repos with an import.yaml")
        rate_limit.update(True)

    if len(import_yamls) > 0:
        typer.echo(f"Scanning repos for import.yaml")

        with typer.progressbar(import_yamls, label="Scanning: ") as import_progress:
            for import_yaml in import_progress:
                r_yaml = yaml.safe_load(import_yaml.decoded_content)
                r_url = import_yaml.repository.id
                #print(r_url)
                if 'orgName' in r_yaml.keys():
                    watchlist.get_repo(r_url).org = r_yaml['orgName']
                
                if 'tags' in r_yaml.keys():
                    for k,v in r_yaml['tags'].items():
                        tmp_tag = {
                            'key': k,
                            'value': v
                        }
                        watchlist.get_repo(r_url).tags.append(Tag.parse_obj(tmp_tag))

    rate_limit.update(True)

    # we are only searching for orgs declared in the snyk-orgs.yaml file
    # this means projects could exist in other snyk orgs we're not watching
    org_ids = [ s.snyk_orgs[o]['orgId'] for o in s.snyk_orgs ]

    typer.echo("Scanning Snyk for projects originating from GitHub Repos")
    with typer.progressbar(watchlist.repos, label="Scanning: ") as project_progress:
        for r in project_progress:
            for snyk_org in org_ids:
                # print(r.source.project_base)
                p_resp = search_projects(
                    r.source.project_base, str(s.default_int), client, snyk_org
                )
                for p in p_resp["projects"]:
                    p["org_id"] = p_resp["org"]["id"]
                    p["org_name"] = p_resp["org"]["name"]
                    r.add_project(Project.parse_obj(p))

    watchlist.save(cachedir=str(s.cache_dir))
    typer.echo("Sync completed")

    rate_limit.total()
    typer.echo(f'Total Repos: {len(watchlist.repos)}')
    




@app.command()
def status():
    """
    Return if the cache is out of date
    """
    global watchlist

    typer.echo('Checking cache status')
    sync_data = jopen(f'{s.cache_dir}/sync.json')

    last_sync = datetime.strptime(sync_data['last_sync'], "%Y-%m-%dT%H:%M:%S.%f")

    in_sync = True

    if s.cache_timeout is None:
        timeout = 0
    else:
        timeout = float(str(s.cache_timeout))

    if last_sync < datetime.utcnow()-timedelta(minutes=timeout):
        typer.echo('Cache is out of date and needs to be updated')
        in_sync = False
    else:
        typer.echo(f'Cache is less than {s.cache_timeout} minutes old')

    typer.echo('Attempting to load cache')
    try:
        cache_data = jopen(f'{s.cache_dir}/data.json')
        for r in cache_data:
            watchlist.repos.append(Repo.parse_obj(r))

    except KeyError as e:
        typer.echo(e)
    
    typer.echo('Cache loaded successfully')

    return in_sync


@app.command()
def targets():
    """
    Returns valid input for api-import to consume
    """
    global s
    global watchlist

    if status() == False:
        sync()
    
    target_list = []
     
    for r in watchlist.repos:
        if len(r.projects) == 0 or r.needs_reimport(s.default_org):
            if r.org != 'default':
                 org_id = s.snyk_orgs[r.org]['orgId']
                 int_id = s.snyk_orgs[r.org]['orgId']
            else:
                org_id = s.default_org_id
                int_id = s.default_int_id

            target = {
                "target": r.source.get_target(),
                "integrationId": int_id,
                "orgId": org_id
            }

            target_list.append(target)


    print(json.dumps(target_list, indent=2))


@app.command()
def tags():
    """
    Returns list of project id's and the tags said projects are missing
    """
    global s
    global watchlist

    if status() == False:
        sync()
    
    has_tags = [r for r in watchlist.repos if r.has_tags()]

    needs_tags = []

    for repo in has_tags:
        for project in repo.projects:
            missing_tags = project.get_missing_tags(s.default_org, repo.tags)
            if len(missing_tags) > 0:
                missing_tags = [m.dict() for m in missing_tags]
                fix_project = {
                    "project_id": str(project.id),
                    "tags": missing_tags
                }
                needs_tags.append(fix_project)
    
    print(json.dumps(needs_tags, indent=2))
            






if __name__ == '__main__':
    app()