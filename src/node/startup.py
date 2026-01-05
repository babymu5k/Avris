from termcolor import colored
import os
import json


def greeter(path: str, AddressGen):
    if os.path.exists(path):
        data = json.load(open(path, "r"))
        a = AddressGen()
        address = a.Validate(data["address"])
        if address:
            print(colored(f"Welcome back {data['address']}!", "green"))
    else:
        print(colored("Invalid address in config.json :(", "red"))
        CreateNew(path, AddressGen)


def CreateNew(path, AddressGen):
    print(colored(f"Do you wish to create a new address?", "blue"))
    c = input("(Y/N) >>> ").lower()
    if c == "y":
        a = AddressGen()
        account = a.Generate()
        wallet_data = {"address": account["address"], "seed": account["seed"]}
        with open(path, "w") as wallet_file:
            json.dump(wallet_data, wallet_file, indent=4)
        print(colored(f"Wallet details saved to '{path}'", "green"))
    else:
        exit(0)
