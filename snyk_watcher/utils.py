import json
import yaml


def jprint(something):
    print(json.dumps(something, indent=2))

def jopen(filename):
    with open(filename, "r") as the_file:
        data = the_file.read()
    return json.loads(data)

def yopen(filename: str):
    with open(filename, "r") as the_file:
        data = the_file.read()
    return yaml.safe_load(data)
