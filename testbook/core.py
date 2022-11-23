import os, yaml, re, csv
import shutil, zipfile

from jinja2 import Environment
from jinja2 import FileSystemLoader


def rel2abs(file, *args):
    file = os.path.realpath(file)
    if os.path.isfile(file):
        file = os.path.dirname(file)
    return os.path.abspath(os.path.join(file, *args))


TEMPLATE_DIR = rel2abs(__file__, "resources", "templates")
ASSETS_DIR = rel2abs(__file__, "resources", "assets")


def parse_tree(dir, outdir, config):
    struct = read_structure(dir)
    render_structure(struct, outdir, config)


def read_structure(dir):
    nav = {}
    for root, dirs, files in os.walk(dir):
        for name in files:
            path = os.path.join(root, name)
            with open(path) as f:
                try:
                    tests = yaml.load(f.read(), Loader=yaml.CLoader)
                except:
                    print("Error loading from {x}".format(x=path))
                    raise

                if tests["suite"] not in nav:
                    nav[tests["suite"]] = {}
                if tests["testset"] not in nav[tests["suite"]]:
                    nav[tests["suite"]][tests["testset"]] = []
                for test in tests["tests"]:
                    nav[tests["suite"]][tests["testset"]].append({
                        "test_id": safe_id(test["title"]),
                        "test_path": safe_id(tests["suite"]) + "/" + safe_id(tests["testset"]) + "/" + safe_id(test["title"]),
                        "test_path_id": safe_id(tests["suite"]) + "__" + safe_id(tests["testset"]) + "__" + safe_id(test["title"]),
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
                "testset_id": safe_id(ts),
                "testset_path": safe_id(s) + "/" + safe_id(ts),
                "testset_path_id": safe_id(s) + "__" + safe_id(ts),
                "tests": tests
            })

        struct.append({
            "suite": s,
            "suite_id": safe_id(s),
            "testsets": tsstruct
        })

    return struct


def render_structure(struct, outdir, config):
    for suite in struct:
        for testset in suite["testsets"]:
            render_testset(struct, suite["suite"], testset, outdir, config)


def _process_includes(tests, fragments):
    for t in tests:
        steps = t.get("steps", [])
        subs = {}
        for i in range(len(steps)):
            step = steps[i]
            if "include" in step:
                fragment = step["include"].get("fragment")
                if not fragment:
                    raise Exception("Include step with no fragment identified")
                replacements = fragments.get(fragment)
                if not replacements:
                    raise Exception("Fragment {x} requested but not defined".format(x=fragment))
                subs[i] = replacements

        if len(subs) > 0:
            keys = sorted(list(subs.keys()), reverse=True)
            for k in keys:
                v = subs[k]
                steps = steps[:k] + v + steps[k+1:]
            t["steps"] = steps


def render_testset(struct, suite_name, testset, outdir, config):
    files = []
    for test in testset["tests"]:
        if test["file"] not in files:
            files.append(test["file"])

    tests = []
    fragments = {}
    for f in files:
        with open(f) as g:
            data = yaml.load(g.read(), Loader=yaml.CLoader)
        tests += data["tests"]
        fragments.update(data.get("fragments", {}))

    _process_includes(tests, fragments)

    id = safe_id(suite_name + "__" + testset["testset"])

    create_out_dir(outdir)

    testset_csv(outdir, id, tests, config, testset, suite_name)
    zip_of_all(outdir, config)

    env = Environment(autoescape=True)
    env.loader = FileSystemLoader([TEMPLATE_DIR])
    env.globals["safe_id"] = safe_id

    template = env.get_template("index.html")
    page = template.render(
        struct=struct,
        testbook_base=config.get("testbook_base", "")
    )

    outfile = os.path.join(outdir, "index.html")
    with open(outfile, "w", encoding="utf-8") as f:
        f.write(page)

    template = env.get_template("testset.html")
    page = template.render(
        tests=tests,
        struct=struct,
        suite_name=suite_name,
        testset_name=testset["testset"],
        id=id,
        id_prefix=get_id_prefix(id),
        application_base=config.get("application_base", ""),
        resource_base=config.get("resource_base", ""),
        testbook_base=config.get("testbook_base", "")
    )

    outfile = os.path.join(outdir, id + ".html")
    with open(outfile, "w", encoding="utf-8") as f:
        f.write(page)

    assets_out = os.path.join(outdir, "assets")
    if os.path.exists(assets_out):
        shutil.rmtree(assets_out)
    shutil.copytree(ASSETS_DIR, assets_out)


def testset_csv(outdir, id, tests, config, testset, suite_name):
    filename = id + ".csv"
    outsubdir = os.path.join(outdir, "testset_csvs")
    create_out_dir(outsubdir)
    outfile = os.path.join(outsubdir, filename)

    id_prefix = get_id_prefix(id)

    with open(outfile, "w") as f:
        writer = csv.writer(f)
        writer.writerow(["Step Number", "User/User Role", "Action", "Expected Test Results", "Testers feedback on script"])

        headers = []
        headers.append([
            "~~~~~~~~~~",
            "~~~~~~~~~~",
            "~~~~~~~~~~",
            "~~~~~~~~~~"
        ])
        headers.append([
            "~~~~~~~~~~",
            "~~~~~~~~~~",
            "# " + suite_name + ": " + testset["testset"],
            "~~~~~~~~~~"
        ])
        headers.append([
            "~~~~~~~~~~",
            "~~~~~~~~~~",
            testset["testset_path"],
            "~~~~~~~~~~"
        ])
        headers.append([
            "~~~~~~~~~~",
            "~~~~~~~~~~",
            "~~~~~~~~~~",
            "~~~~~~~~~~"
        ])

        writer.writerows(headers)

        headers_dir = os.path.join(outdir, "headers")
        create_out_dir(headers_dir)
        headers_file = os.path.join(headers_dir, filename)
        with open(headers_file, "w") as g:
            hw = csv.writer(g)
            hw.writerows(headers)

        idx = 0
        for test in tests:
            idx += 1
            rows = test_rows(test, config, idx, id_prefix)

            individual_filename = safe_id(id + "__" + test["title"])
            individual_outdir = os.path.join(outdir, "test_csvs")
            create_out_dir(individual_outdir)
            individual_out = os.path.join(individual_outdir, individual_filename + ".csv")

            with open(individual_out, "w") as g:
                iw = csv.writer(g)
                iw.writerows(rows)

            writer.writerows(rows)
            writer.writerow([])


def test_rows(test, config, idx, id_prefix):
    step_id = 0
    rows = []
    rows.append([
        "----------",
        "----------",
        "----------",
        "----------"
    ])
    rows.append(["## " + id_prefix + "." + str(idx), "----------", "## " + test["title"], "----------"])

    for dependency in test.get("depends", []):
        dep = dependency.get("suite", "")
        if dependency.get("testset"):
            dep += " : " + dependency.get("testset")
        if dependency.get("test"):
            dep += " : " + dependency.get("test")
        rows.append([
            "Depends on " + dep,
            "",
            "",
            ""
        ])

    for setup in test.get("setup", []):
        rows.append([
            "",
            "",
            "Setup: " + setup,
            ""
        ])

    for step in test.get("steps", []):
        step_id += 1
        id = id_prefix + "." + str(idx) + "." + str(step_id) + "."

        desc = step.get("step", "")
        if "path" in step:
            desc += "\n\n{base}{path}".format(base=config.get("application_base", ""), path=step.get("path"))
        if "resource" in step:
            desc += "\n\nTest Resource: {base}{path}".format(base=config.get("resource_base", ""),
                                                             path=step.get("resource"))

        rows.append([
            id,
            test.get("context", {}).get("role", ""),
            desc,
            ""
        ])

        result_id = 0
        for r in step.get("results", []):
            result_id += 1
            rid = id + str(result_id) + "."
            rows.append([
                rid,
                test.get("context", {}).get("role", ""),
                "",
                r
            ])

    rows.append([
        "----------",
        "----------",
        "----------",
        "----------"
    ])

    return rows


def zip_of_all(outdir, config):
    zip = os.path.join(outdir, "all_tests.zip")
    testsets = os.path.join(outdir, "testset_csvs")

    with zipfile.ZipFile(zip, mode="w") as zf:
        for fn in os.listdir(testsets):
            zf.write(os.path.join(testsets, fn), arcname=fn)


def create_out_dir(outdir):
    if not os.path.exists(outdir):
        os.makedirs(outdir)


def safe_id(s):
    basic = s.lower().replace(" ", "_")
    return "".join([c for c in basic if re.match(r'\w', c)])


ID_REGISTRY = []
ID_PARTS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def get_id_prefix(id):
    if id not in ID_REGISTRY:
        ID_REGISTRY.append(id)
    loc = ID_REGISTRY.index(id)
    parts = numberToBase(loc, 26)
    return "".join([ID_PARTS[p] for p in parts])


def numberToBase(n, b):
    if n == 0:
        return [0]
    digits = []
    while n:
        digits.append(int(n % b))
        n //= b
    return digits[::-1]