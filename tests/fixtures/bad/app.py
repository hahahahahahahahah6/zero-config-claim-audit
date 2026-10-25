import tomllib
import configparser
with open("settings.toml", "rb") as stream:
    settings = tomllib.load(stream)
parser = configparser.ConfigParser()
with open("service.ini") as stream:
    parser.read_file(stream)
