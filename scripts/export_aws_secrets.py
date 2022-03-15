import json

import subprocess

get_aws_data = "aws secretsmanager get-secret-value --secret-id snyk_sync_secrets --query SecretString"


def run_process(cmd):
    process = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    process.wait()
    data, err = process.communicate()
    if process.returncode == 0:
        return data.decode("utf-8")
    else:
        print("Error:", err)
    return ""


output = run_process(get_aws_data)

env_vars = json.loads(output)

if type(env_vars) is str:
    env_vars = json.loads(env_vars)

for k, v in env_vars.items():
    print(f'export {k}="{v}"')
