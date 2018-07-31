import sys
import json


def read_json(path):
    data = None
    try:
        with open(path, "r") as f:
            data = json.loads(f.read())
    except FileNotFoundError:
        pass
    return data


def confirmation(msg):
    print(msg)
    choice = input("Accept? ")
    choice = choice.strip().lower()
    return choice == "y" or choice == "yes"


def pretty(data):
    return json.dumps(data, indent=2)


def user_error(msg):
    sys.exit("Error: {}".format(msg))
