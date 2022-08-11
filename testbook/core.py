import os, yaml, re, csv

from jinja2 import Environment
from jinja2 import FileSystemLoader

def rel2abs(file, *args):
    file = os.path.realpath(file)
    if os.path.isfile(file):
        file = os.path.dirname(file)
    return os.path.abspath(os.path.join(file, *args))

TEMPLATE_DIR = rel2abs(__file__, "..", "resources", "templates")

def parse_tree(dir, outdir, config):
    struct = read_structure(dir)
    render_structure(struct, outdir, config)


def read_structure(dir):
    nav = {}
    for root, dirs, files in os.walk(dir):
        for name in files:
            path = os.path.join(root, name)
            with open(path) as f:
                tests = yaml.load(f.read(), Loader=yaml.CLoader)
                if tests["suite"] not in nav:
                    nav[tests["suite"]] = {}
                if tests["testset"] not in nav[tests["suite"]]:
                    nav[tests["suite"]][tests["testset"]] = {}
                nav[tests["suite"]][tests["testset"]] = []
                for test in tests["tests"]:
                    nav[tests["suite"]][tests["testset"]].append({
                        "title": test["title"],
                        "file": path
                    })

    struct = []
    suites = sorted(list(nav.keys()))   # alphabetically organise suites
    for s in suites:
        testsets = sorted(list(nav[s].keys()))  # alphabetically organise testsets
        tsstruct = []
        for ts in testsets:
            tests = nav[s][ts]  # tests remain in file defined order
            tsstruct.append({
                "testset": ts,
                "tests": tests
            })

        struct.append({
            "suite": s,
            "testsets": tsstruct
        })

    return struct


def render_structure(struct, outdir, config):
    for suite in struct:
        for testset in suite["testsets"]:
            render_testset(struct, suite["suite"], testset, outdir, config)


def render_testset(struct, suite_name, testset, outdir, config):
    files = []
    for test in testset["tests"]:
        if test["file"] not in files:
            files.append(test["file"])

    tests = []
    for f in files:
        with open(f) as g:
            data = yaml.load(g.read(), Loader=yaml.CLoader)
        tests += data["tests"]

    id = safe_id(suite_name + "__" + testset["testset"])

    create_out_dir(outdir)

    testset_csv(outdir, id, tests, config)

    env = Environment(autoescape=True)
    env.loader = FileSystemLoader([TEMPLATE_DIR])
    env.globals["safe_id"] = safe_id

    template = env.get_template("testset.html")
    page = template.render(
        tests=tests,
        struct=struct,
        suite_name=suite_name,
        testset_name=testset["testset"],
        id_prefix=id,
        application_base=config.get("application_base", ""),
        resource_base=config.get("resource_base", ""),
        testbook_base=config.get("testbook_base", "")
    )

    outfile = os.path.join(outdir, id + ".html")
    with open(outfile, "w", encoding="utf-8") as f:
        f.write(page)


def testset_csv(outdir, id, tests, config):
    filename = id + ".csv"
    outfile = os.path.join(outdir, filename)
    with open(outfile, "w") as f:
        writer = csv.writer(f)
        writer.writerow(["Step Number", "User/User Role", "Action", "Expected Test Results", "Testers feedback on script"])
        writer.writerow([])

        idx = 0
        for test in tests:
            idx += 1

            rows = []
            rows.append([idx, "", test["title"]])

            step_id = 0
            for step in test.get("steps", []):
                step_id += 1
                id = str(idx) + "." + str(step_id)

                desc = step.get("step", "")
                if "path" in step:
                    desc += "\n\n{base}{path}".format(base=config.get("application_base", ""), path=step.get("path"))
                if "resource" in step:
                    desc += "\n\nTest Resource: {base}{path}".format(base=config.get("resource_base", ""), path=step.get("resource"))

                result = ""
                for r in step.get("results", []):
                    result += "* {r}\n".format(r=r)

                rows.append([
                    id,
                    test.get("context", {}).get("role", ""),
                    desc,
                    result
                ])

            rows.append([])

            writer.writerows(rows)


def create_out_dir(outdir):
    if not os.path.exists(outdir):
        os.makedirs(outdir)


def safe_id(s):
    basic = s.lower().replace(" ", "_")
    return "".join([c for c in basic if re.match(r'\w', c)])
