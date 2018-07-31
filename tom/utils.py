import json


def confirmation(msg):
    print(msg)
    choice = input("Accept? ")
    choice = choice.strip().lower()
    return choice == "y" or choice == "yes"


def pretty(data):
    return json.dumps(data, indent=2)
