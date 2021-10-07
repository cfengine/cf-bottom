import sys
import json
import hashlib


def read_json(path):
    data = None
    try:
        with open(path, "r") as f:
            data = json.loads(f.read())
    except FileNotFoundError:
        pass
    return data


def write_json(data, path, prettify=True):
    with open(path, "w") as f:
        f.write(pretty(data) if prettify else json.dumps(data))


def confirmation(msg):
    print(msg)
    choice = input("Accept? ")
    choice = choice.strip().lower()
    return choice == "y" or choice == "yes"


def pretty(data):
    return json.dumps(data, indent=2)


def user_error(msg):
    sys.exit("Error: {}".format(msg))


def email_sha256(email):
    hash = hashlib.sha256()
    hash.update(email.encode("utf-8"))
    hash = hash.hexdigest()
    data = read_json("tmp_emails.json")
    if not data:
        data = {}
    if email in data and data[email] == hash:
        return hash
    data[email] = hash
    write_json(data, "tmp_emails.json")
    return hash
