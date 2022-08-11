import click

from testbook.core import parse_tree

@click.command()
@click.argument("dir")
@click.argument("out")
@click.option("-a", "--application")
@click.option("-r", "--resource")
@click.option("-t", "--testbook")
def main(dir, out, application="", resource="", testbook=""):
    config = {
        "application_base": application,
        "resource_base": resource,
        "testbook_base": testbook
    }
    parse_tree(dir, out, config)


if __name__ == "__main__":
    main()