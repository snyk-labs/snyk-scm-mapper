from github import Github
from github.ContentFile import ContentFile
from github.PaginatedList import PaginatedList

GH_PAGE_LIMIT = 100
gh = Github('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', per_page=GH_PAGE_LIMIT)

search = f"org:snyk-playground path:.snyk.d filename:import language:yaml"
searchtest = gh.search_code(query=search)

for file in searchtest:
    print(file.repository.html_url)


